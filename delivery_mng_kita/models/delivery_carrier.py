# Copyright 2023 Kıta Yazılım
# License LGPLv3 or later (https://www.gnu.org/licenses/lgpl-3.0).

from odoo import _, api, fields, models
from .mng_request import MngRequest


class DeliveryCarrier(models.Model):
    ''' A Shipping Provider

        In order to add your own external provider, follow these steps:

        1. Create your model MyProvider that _inherit 'delivery.carrier'
        2. Extend the selection of the field "delivery_type" with a pair
           ('<my_provider>', 'My Provider')
        3. Add your methods:
           <my_provider>_rate_shipment
           <my_provider>_send_shipping
           <my_provider>_get_tracking_link
           <my_provider>_cancel_shipment
           _<my_provider>_get_default_custom_package_code
           (they are documented hereunder)
        '''
    _inherit = "delivery.carrier"

    delivery_type = fields.Selection(selection_add=[("mng", "MNG Kargo")], ondelete={'mng': 'set fixed'})
    mng_api_client_id = fields.Char(string="Müşteri ID", help="Mng Kargo istemci kimliği")
    mng_api_client_secret = fields.Char(string="Müşteri Gizli Anahtarı", help="Mng Kargo istemci güvenlik anahtarı")    
    customerNumber = fields.Char(string="Müşteri No", help="Mng Kargo müşteri numarası")
    password = fields.Char(string="Şifre", help="Mng Kargo şifresi")

    def _prepare_mng_address(
        self,
        partner
    ):
        vals = {
            "id": partner.id,
            "name": partner.name,
            "vat": partner.vat,
            "street": partner.street,
            "postalCode": partner.zip,
            "city": partner.city,
            "stateCode": partner.state_id.code,
            "stateName": partner.state_id.name,
            "countryCode": partner.country_id.code,
            "preferredLanguage": self.env["res.lang"]._lang_get(partner.lang).iso_code,
        }
        if partner.email:
            vals["email"] = partner.email
        if partner.mobile:
            vals["mobilePhone"] = partner.mobile
        if partner.phone:
            vals["phone"] = partner.phone
        if partner.street2:
            vals["street2"] = partner.street2
        return vals

    def _mng_shipping_address(self, picking):
        address = picking.partner_id
        return self._prepare_mng_address(address)

    def _prepare_mng_shipping(self, picking):
        self.ensure_one()
        vals = {}
        partner_info = self._mng_shipping_address(picking)
        vals.update(
            {                
                "order":{
                    "referenceId": (picking.origin or picking.sale_id.name or picking.name).upper(),
                    "barcode": (picking.origin or picking.sale_id.name or picking.name).upper(),
                    "billOfLandingId": picking.name, #İrsaliye Numarası
                    "isCOD": 0, #Kapıda Ödeme mi?
                    "codAmount": 0, #Kapıda Ödeme Miktarı
                    "shipmentServiceType": 1, #1:STANDART_TESLİMAT, 7:GUNİCİ_TESLİMAT, 8:AKŞAM_TESLİMAT Gönderi Tipi
                    "packagingType": 4, #TODO 1:DOSYA, 2:Mİ, 3:PAKET, 4:KOLİ Kargo Cinsi
                    "content": "İçerik 1",
                    "smsPreference1": 1, #Kargo varış şubesine ulaştığında alıcıya SMS gitsin mi?
                    "smsPreference2": 0, #ilk hazırlandığında alıcıya SMS gitsin mi?
                    "smsPreference3": 1, #teslim edildiğinde göndericiye SMS gitsin mi?
                    "paymentType": 1, #1:GONDERICI_ODER, 2:ALICI_ODER
                    "deliveryType": 1, #1:ADRESE_TESLIM, 2:ALICISI_HABERLİ Teslim Şekli
                    "description": "Açıklama 1",
                    "marketPlaceShortCode": "",
                    "marketPlaceSaleCode": "",
                    "pudoId": ""
                },
                "orderPieceList":[
                    {
                        "barcode": line.product_id.barcode or "URUN_KODU",
                        "desi": line.product_id.volume/3000 if line.product_id.volume/3000 > 1 else 2,
                        "kg": int(line.product_id.weight) if line.product_id.weight >= 1 else 1,
                        "content": line.name
                    }
                   for line in picking.move_ids_without_package
                ],
                "recipient":{
                    "customerId": '',
                    "refCustomerId": partner_info.get('id'),
                    "cityCode": 0, #CBS Info API'den kod bilgisi alınabilir.
                    "cityName": partner_info['stateName'],
                    "districtName": partner_info['city'],
                    "districtCode": 0, #İlçe Kodu, CBS Info API'den kod bilgisi alınabilir.
                    "address": f"{partner_info.get('street')} {partner_info.get('street2', '')}",
                    "bussinessPhoneNumber": "",
                    "email": partner_info.get('email'),
                    "taxOffice": "",
                    "taxNumber": partner_info.get('vat'),
                    "fullName": picking.partner_id.name,
                    "homePhoneNumber": partner_info.get('phone'),
                    "mobilePhoneNumber": partner_info.get('mobilePhone')
                }
            }            
        )
        return vals

    def mng_send_shipping(self, pickings):
        mng_request = MngRequest(self)
        result = []
        for picking in pickings:
            vals = self._prepare_mng_shipping(picking)
            try:
                response = mng_request._send_shipping(vals)
            except Exception as e:
                raise (e)
            if not response:
                result.append(vals)
                continue
            vals["tracking_number"] = vals['order']['billOfLandingId'].replace('/','')

            attachment = []
            if response.get("barcode"):
                body = _("MNG Kargo Barkodu")
                attachment = [
                    (
                        "mng_label_{}.pdf".format(vals['order']['billOfLandingId'].replace('/','')),
                        response.get("barcode"),
                    )
                ]
                picking.message_post(body=body, attachments=attachment)
            result.append(vals)
        return result

    def mng_cancel_shipment(self, pickings):
        mng_request = MngRequest(self)
        for picking in pickings.filtered("carrier_tracking_ref"):
            try:
                mng_request._cancel_shipment((picking.origin or picking.sale_id.name or picking.name).upper())
            except Exception as e:
                raise (e)
        return True

    def mng_get_tracking_link(self, picking):
        mng_request = MngRequest(self)
        try:
            tracking_link = mng_request._get_tracking_link((picking.origin or picking.sale_id.name or picking.name).upper())
        except Exception as e:
            raise (e)
        return tracking_link
