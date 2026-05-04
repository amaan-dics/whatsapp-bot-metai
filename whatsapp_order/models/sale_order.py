from odoo import models, api
import logging

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.model
    def create_from_whatsapp(self, phone, product_name, quantity):

        if not phone or not product_name:
            return {"error": "Missing phone or product"}

        _logger.info(f"WhatsApp Order: {phone} | {product_name} | {quantity}")

        # Partner
        partner = self.env['res.partner'].search([('phone', '=', phone)], limit=1)

        if not partner:
            partner = self.env['res.partner'].create({
                'name': phone,
                'phone': phone,
                'email': f"{phone}@wa.com"
            })

        # Product
        product = self.env['product.product'].search([
            ('name', '=', product_name)
        ], limit=1)

        if not product:
            return {"error": "Product not found"}

        # Order
        order = self.create({
            'partner_id': partner.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': quantity,
            })],
        })

        order.action_confirm()

        # Payment link
        website = self.env['website'].sudo().get_current_website()

        wizard = self.env['payment.link.wizard'].sudo().with_context(
            website_id=website.id
        ).create({
            'res_model': 'sale.order',
            'res_id': order.id,
            'amount': order.amount_total,
            'currency_id': order.currency_id.id,
        })

        return {
            "order_id": order.id,
            "payment_link": wizard.link or "NO_LINK"
        }