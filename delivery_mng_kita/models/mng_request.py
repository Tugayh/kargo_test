# Copyright 2023 Kita Yazilim
# License LGPLv3 or later (https://www.gnu.org/licenses/lgpl-3.0).

import logging
import json
import requests
from datetime import datetime

from odoo import _
from odoo import api, fields
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)
TIMEOUT = 20
MNG_API_SERVICE = {
    "test": "https://testapi.mngkargo.com.tr/mngapi/api",
    "prod": "https://apizone.mngkargo.com.tr/mngapi/api",
}


class MngRequest:
    def __init__(
        self, carrier
    ):
        self.client_id = carrier.mng_api_client_id
        self.client_secret = carrier.mng_api_client_secret
        self.customerNumber = carrier.customerNumber
        self.password = carrier.password
        api_env = "prod" if carrier.prod_environment else "test"
        self.api_url = MNG_API_SERVICE[api_env]

    def _shipping_api_credentials(self):
        credentials = {
            'x-ibm-client-id': self.client_id,
            'x-ibm-client-secret': self.client_secret,
            'x-api-version': '',
            'content-type': "application/json",
            'accept': "application/json",
        }
        return credentials

    def _get_mng_token(self):
        payload = {
            "customerNumber": self.customerNumber,
            "password": self.password,
            "identityType":1
        }

        headers = self._shipping_api_credentials()
        url = self.api_url + "/token"
        status, response, asktime = self._do_request(url, params=payload, headers=headers, type='POST')
        if response.get('httpCode'):
            raise UserError(f'Hata Oluştu!, Token Alınamadı, {response.get("httpMessage")}')
        return f"Bearer {response.get('jwt')}"

    def _send_shipping(self, picking_vals):
        headers = self._shipping_api_credentials()
        headers.update({'Authorization': self._get_mng_token()})
        payload = picking_vals

        url = self.api_url + "/standardcmdapi/createOrder"
        status, response, asktime = self._do_request(url, params=payload, headers=headers, type='POST')
        
        return {
            "booking_id": response[0].get('orderInvoiceId'),
            "barcode": None,
        }

    def _cancel_shipment(self, reference=False):
        headers = self._shipping_api_credentials()
        headers.update({'Authorization': self._get_mng_token()})

        url = self.api_url + "/standardcmdapi/cancelorder/" + reference
        status, response, asktime = self._do_request(url, headers=headers, type='PUT')

        if status == 404:
            raise UserError(f'Hata Oluştu!, Kargo gönderi iptali yapılamadı, {response}')

        return True

    def _get_tracking_link(self, reference=False):
        if not reference:
            return False
        headers = self._shipping_api_credentials()
        headers.update({'Authorization': self._get_mng_token()})
        url = self.api_url + "/standardqueryapi/getshipmentstatus/" + reference

        status, response, asktime = self._do_request(url, headers=headers, type='GET')

        if status == 404:
            raise UserError(response)

        return response['trackingUrl']

    @api.model
    def _do_request(self, uri, params={}, headers={}, type='POST'):

        _logger.debug("Uri: %s - Type : %s - Headers: %s - Params : %s !", (uri, type, headers, params))
        ask_time = fields.Datetime.now()
        try:
            if type.upper() in ('GET', 'DELETE'):
                res = requests.request(type.lower(), uri, headers=headers, params=params, timeout=TIMEOUT)
            elif type.upper() in ('POST', 'PATCH', 'PUT'):
                res = requests.request(type.lower(), uri, json=params, headers=headers, timeout=TIMEOUT)
            else:
                raise Exception(_('Desteklenmeyen Metod [%s] not in [GET, POST, PUT, PATCH or DELETE]!') % (type))
            res.raise_for_status()
            status = res.status_code

            content_type = res.headers.get('Content-type')
            if int(status) in (204, 404):
                response = False
            elif bool(res.headers.get('Content-type')) and 'application/json' in content_type:
                response = res.json()
            elif bool(res.headers.get('Content-type')) and 'text/plain' in content_type:
                response = res.text
            else:
                response = res

            try:
                ask_time = datetime.strptime(res.headers.get('date'), "%a, %d %b %Y %H:%M:%S %Z")
            except:
                pass
        except requests.HTTPError as error:
            if error.response.status_code in (204, 404):
                status = error.response.status_code
                response = json.loads(res.text).get('error').get('description') if bool(json.loads(res.text).get('error')) else "Gönderi henüz takip edilebilir durumda değil"
            else:
                _logger.exception("Bad request MNG Kargo : %s !", error.response.text)
                msg = None
                if error.response.status_code in (401, 403, 410):
                    raise error

                if error.response.status_code in (400,500):
                    try:
                        msg = json.loads(error.response.text).get('error').get('description')
                    except Exception:
                        mgs = None
                raise UserError(msg or _("Bilinmeyen hata oluştu"))
        return (status, response, ask_time)