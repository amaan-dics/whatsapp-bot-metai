# -*- coding: utf-8 -*-
"""
whatsapp_order/controllers/main.py

COMPLETE REPLACEMENT for your existing controller.
Adds /api/products and fixes /api/whatsapp/order.
"""

import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class WhatsAppController(http.Controller):

    @http.route(
        "/api/products",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def get_products(self, **kwargs):
        """
        Returns all sellable products as JSON.
        Called by the FastAPI bot to build the WhatsApp menu.
        """
        try:
            products = request.env["product.product"].sudo().search_read(
                domain=[("sale_ok", "=", True), ("active", "=", True)],
                fields=["id", "name", "list_price", "uom_id"],
                limit=100,
                order="name asc",
            )
            # uom_id comes as [id, "kg"] — flatten to just the string
            for p in products:
                if isinstance(p.get("uom_id"), (list, tuple)):
                    p["uom_id"] = p["uom_id"][1]

            _logger.info(f"[/api/products] Returning {len(products)} products")
            return request.make_response(
                json.dumps(products),
                headers=[("Content-Type", "application/json"),
                         ("Access-Control-Allow-Origin", "*")]
            )
        except Exception as e:
            _logger.error(f"[/api/products] Error: {e}")
            return request.make_response(
                json.dumps({"error": str(e)}),
                headers=[("Content-Type", "application/json")],
                status=500,
            )

    @http.route("/api/whatsapp/order", type="http", auth="public", methods=["POST"], csrf=False)
    def create_order(self, **kwargs):
        try:
            data = json.loads(request.httprequest.data)

            phone = data.get("phone")
            product_name = data.get("product")
            quantity = data.get("quantity", 1)

            result = request.env["sale.order"].sudo().create_from_whatsapp(
                phone=phone,
                product_name=product_name,
                quantity=quantity
            )

            return request.make_response(
                json.dumps(result),
                headers=[("Content-Type", "application/json")]
            )

        except Exception as e:
            return request.make_response(
                json.dumps({"error": str(e)}),
                headers=[("Content-Type", "application/json")],
                status=500
            )