# -*- coding: utf-8 -*-
from odoo import Command
from odoo.tests.common import TransactionCase


class DwCommon(TransactionCase):
    """Shared fixtures for the Metal Fabrication test suite."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1
        )
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.supplier_location = cls.env.ref("stock.stock_location_suppliers")
        cls.production_location = cls.env["stock.location"].search(
            [("usage", "=", "production"), ("company_id", "in", [False, cls.company.id])],
            limit=1,
        )
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.uom_meter = cls.env.ref("uom.product_uom_meter")
        cls.uom_m2 = cls.env.ref("uom.product_uom_square_meter")
        cls.uom_kg = cls.env.ref("uom.product_uom_kgm")
        cls.uom_litre = cls.env.ref("uom.product_uom_litre")
        cls.uom_hour = cls.env.ref("uom.product_uom_hour")

        cls.partner = cls.env["res.partner"].create({"name": "Metal Test Customer"})

        # ---- Raw materials -------------------------------------------------
        cls.profile_shs40 = cls.env.ref("dw_manufacturing.profile_shs_40x40x2")
        cls.profile_shs50 = cls.env.ref("dw_manufacturing.profile_shs_50x50x2")
        cls.profile_sheet2 = cls.env.ref("dw_manufacturing.profile_sheet_2")
        cls.profile_pipe = cls.env.ref("dw_manufacturing.profile_pipe_48_3")

        cls.mat_tube40 = cls._make_material(
            "Steel Tube 40x40x2", cls.uom_meter, 15.0, cls.profile_shs40
        )
        cls.mat_tube50 = cls._make_material(
            "Steel Tube 50x50x2", cls.uom_meter, 20.0, cls.profile_shs50
        )
        cls.mat_pipe = cls._make_material(
            "Steel Pipe 48.3", cls.uom_meter, 25.0, cls.profile_pipe
        )
        cls.mat_sheet = cls._make_material(
            "Steel Sheet 2mm", cls.uom_m2, 60.0, cls.profile_sheet2
        )
        cls.mat_mesh = cls._make_material("Wire Mesh", cls.uom_m2, 22.0)
        cls.mat_paint = cls._make_material("Primer Paint", cls.uom_litre, 30.0)
        cls.mat_electrode = cls._make_material("Welding Electrode", cls.uom_kg, 18.0)
        cls.mat_hinge = cls._make_material("Heavy Hinge", cls.uom_unit, 12.0)
        cls.mat_lock = cls._make_material("Door Lock", cls.uom_unit, 90.0)
        cls.mat_customer = cls._make_material("Customer Supplied Glass", cls.uom_m2, 100.0)
        cls.mat_customer.product_tmpl_id.dw_is_customer_supplied = True

        cls.service_galv = cls.env["product.product"].create({
            "name": "Hot Dip Galvanizing Service",
            "type": "service",
            "standard_price": 4.0,
            "list_price": 6.0,
        })

        # ---- Finished products ---------------------------------------------
        cls.product_fence = cls._make_finished("Steel Fence")
        cls.product_stair = cls._make_finished("Steel Staircase")
        cls.product_door = cls._make_finished("Steel Door")
        cls.product_canopy = cls._make_finished("Steel Canopy")

        # ---- Work centers ---------------------------------------------------
        cls.wc_cutting = cls.env["mrp.workcenter"].create({
            "name": "Cutting Line", "costs_hour": 25.0, "company_id": cls.company.id,
        })
        cls.wc_welding = cls.env["mrp.workcenter"].create({
            "name": "Welding Bay", "costs_hour": 30.0, "company_id": cls.company.id,
        })
        cls.wc_painting = cls.env["mrp.workcenter"].create({
            "name": "Paint Booth", "costs_hour": 20.0, "company_id": cls.company.id,
        })

        cls.op_cutting = cls.env.ref("dw_manufacturing.operation_cutting")
        cls.op_welding = cls.env.ref("dw_manufacturing.operation_welding")
        cls.op_painting = cls.env.ref("dw_manufacturing.operation_painting")
        cls.op_assembly = cls.env.ref("dw_manufacturing.operation_assembly")
        cls.op_cutting.workcenter_id = cls.wc_cutting
        cls.op_welding.workcenter_id = cls.wc_welding
        cls.op_painting.workcenter_id = cls.wc_painting
        cls.op_assembly.workcenter_id = cls.wc_welding

        # ---- Labour rates ----------------------------------------------------
        cls.env["dw.labor.rate"].create([
            {
                "name": "Default fabrication labour",
                "company_id": cls.company.id,
                "hourly_cost": 20.0,
                "sequence": 50,
            },
            {
                "name": "Welder rate",
                "company_id": cls.company.id,
                "workcenter_id": cls.wc_welding.id,
                "hourly_cost": 35.0,
                "sequence": 10,
            },
        ])

        cls.dim = {
            dimension.code: dimension
            for dimension in cls.env["dw.dimension.field"].search([])
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @classmethod
    def _make_material(cls, name, uom, price, profile=None):
        values = {
            "name": name,
            "type": "consu",
            "is_storable": True,
            "uom_id": uom.id,
            "standard_price": price,
            "list_price": price,
        }
        if profile:
            values["dw_metal_profile_id"] = profile.id
        return cls.env["product.product"].create(values)

    @classmethod
    def _make_finished(cls, name):
        return cls.env["product.product"].create({
            "name": name,
            "type": "consu",
            "is_storable": True,
            "standard_price": 0.0,
        })

    @classmethod
    def _dims(cls, *codes):
        return [Command.set([cls.dim[code].id for code in codes])]

    def _stock(self, product, quantity, location=None):
        self.env["stock.quant"]._update_available_quantity(
            product, location or self.stock_location, quantity
        )

    def _receive(self, product, quantity, price_unit):
        """Real incoming move so inventory valuation is genuine (FIFO friendly).

        With no purchase order behind the receipt, Odoo 19 values an incoming
        move from the product cost at that moment, exactly as a manual receipt
        would, so the cost is set just before the move is done.
        """
        product.with_company(self.company).standard_price = price_unit
        move = self.env["stock.move"].create({
            "product_id": product.id,
            "product_uom_qty": quantity,
            "product_uom": product.uom_id.id,
            "location_id": self.supplier_location.id,
            "location_dest_id": self.stock_location.id,
            "company_id": self.company.id,
            "price_unit": price_unit,
        })
        move._action_confirm()
        move._action_assign()
        move.quantity = quantity
        move.picked = True
        move._action_done()
        return move

    def _make_sale_order(self):
        return self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "dw_is_manufacturing_quote": True,
        })

    def _produce(self, production, quantity=None):
        """Consume, produce and close a manufacturing order."""
        production.action_assign()
        production.qty_producing = quantity or production.product_qty
        for move in production.move_raw_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        production.button_mark_done()
        return production
