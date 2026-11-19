# -*- coding: utf-8 -*-
"""Actual costing: real valuation, labour, machine, scrap, overhead and the
guarantee that recomputation never duplicates a cost line."""

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import DwCommon


@tagged("post_install", "-at_install", "dw_manufacturing")
class TestActualCosting(DwCommon):

    def setUp(self):
        super().setUp()
        self.family = self.env["dw.product.family"].create({
            "name": "Cost Family",
            "code": "COSTF",
            "product_kind": "gate",
            "company_id": self.company.id,
            "dimension_ids": self._dims("width", "height", "weld_length", "paint_area"),
            "operation_ids": [
                Command.create({
                    "sequence": 10,
                    "operation_type_id": self.op_cutting.id,
                    "workcenter_id": self.wc_cutting.id,
                }),
                Command.create({
                    "sequence": 20,
                    "operation_type_id": self.op_welding.id,
                    "workcenter_id": self.wc_welding.id,
                }),
            ],
        })
        self.env["dw.component.rule"].create({
            "name": "Frame tube",
            "family_id": self.family.id,
            "company_id": self.company.id,
            "component_product_id": self.mat_tube40.id,
            "calc_method": "variable",
            "basis": "perimeter",
            "factor": 1.0,
        })
        self.order = self._make_sale_order()
        self.item = self.env["dw.opening"].create({
            "sale_order_id": self.order.id,
            "family_id": self.family.id,
            "finished_product_id": self.product_door.id,
            "width_mm": 2000.0,
            "height_mm": 2000.0,
            "quantity": 1.0,
        })
        self.item.action_generate_components()
        self.item.action_sync_quotation_line()
        self.order.action_confirm()

    def _build(self):
        self._stock(self.mat_tube40, 100.0)
        self.item.action_create_manufacturing_order()
        return self.item.production_id

    # ------------------------------------------------------------------
    def test_01_material_cost_from_stock_moves(self):
        production = self._build()
        self._produce(production)
        production._dw_recompute_actual_cost()
        lines = production.dw_cost_line_ids.filtered(lambda l: l.cost_type == "material")
        self.assertEqual(len(lines), 1)
        move = production.move_raw_ids
        self.assertEqual(lines.stock_move_id, move)
        # The line must equal the valued amount stored on the move itself,
        # which is Odoo 19's replacement for stock.valuation.layer.
        self.assertAlmostEqual(lines.amount, abs(move.value), places=2)
        self.assertAlmostEqual(lines.amount, 8.0 * 15.0, places=2)

    def test_02_fifo_valuation_is_used_not_standard_price(self):
        category = self.env["product.category"].create({
            "name": "FIFO metal",
            "property_cost_method": "fifo",
            "property_valuation": "real_time"
            if "property_valuation" in self.env["product.category"]._fields else "manual_periodic",
        })
        product = self.env["product.product"].create({
            "name": "FIFO tube",
            "type": "consu",
            "is_storable": True,
            "uom_id": self.uom_meter.id,
            "categ_id": category.id,
            "standard_price": 0.0,
        })
        self._receive(product, 10.0, 10.0)
        self._receive(product, 10.0, 20.0)

        self.env["dw.component.rule"].create({
            "name": "FIFO component",
            "family_id": self.family.id,
            "company_id": self.company.id,
            "component_product_id": product.id,
            "calc_method": "fixed",
            "fixed_qty": 15.0,
        })
        self.item.action_generate_components()
        production = self._build()
        self._produce(production)
        production._dw_recompute_actual_cost()

        line = production.dw_cost_line_ids.filtered(
            lambda l: l.product_id == product and l.cost_type == "material"
        )
        move = production.move_raw_ids.filtered(lambda m: m.product_id == product)
        # 10 units at 10 plus 5 units at 20 = 200, never 15 x standard_price
        self.assertAlmostEqual(line.amount, abs(move.value), places=2)
        self.assertAlmostEqual(line.amount, 200.0, places=2)

    def test_03_labour_and_machine_from_actual_time(self):
        production = self._build()
        for workorder in production.workorder_ids:
            workorder.duration = 120.0  # 2 hours each
        self._produce(production)
        production._dw_recompute_actual_cost()

        labour = production.dw_cost_line_ids.filtered(lambda l: l.cost_type == "labor")
        machine = production.dw_cost_line_ids.filtered(lambda l: l.cost_type == "machine")
        self.assertTrue(labour)
        self.assertTrue(machine)
        # Cutting uses the default rate (20/h), welding its specific rate (35/h)
        self.assertAlmostEqual(production.dw_labor_cost, 2 * 20.0 + 2 * 35.0, places=2)
        # Machine cost uses the work center hourly cost
        self.assertAlmostEqual(production.dw_machine_cost, 2 * 25.0 + 2 * 30.0, places=2)

    def test_04_machine_cost_can_be_switched_off(self):
        self.company.dw_workcenter_cost_is_total = True
        production = self._build()
        for workorder in production.workorder_ids:
            workorder.duration = 60.0
        self._produce(production)
        production._dw_recompute_actual_cost()
        self.assertEqual(production.dw_machine_cost, 0.0)
        self.assertTrue(production.dw_labor_cost > 0)

    def test_05_recompute_is_idempotent(self):
        production = self._build()
        for workorder in production.workorder_ids:
            workorder.duration = 45.0
        self._produce(production)

        production._dw_recompute_actual_cost()
        first_count = len(production.dw_cost_line_ids)
        first_total = production.dw_actual_cost

        for _index in range(4):
            production._dw_recompute_actual_cost()

        self.assertEqual(len(production.dw_cost_line_ids), first_count)
        self.assertAlmostEqual(production.dw_actual_cost, first_total, places=6)
        keys = production.dw_cost_line_ids.mapped("source_key")
        self.assertEqual(len(keys), len(set(keys)))

    def test_06_approved_lines_are_protected_and_audited(self):
        production = self._build()
        self._produce(production)
        production._dw_recompute_actual_cost()
        line = production.dw_cost_line_ids.filtered(lambda l: l.cost_type == "material")
        line.action_approve()
        original = line.amount

        # Force a different computed value and recompute.
        line.write({"amount": original})
        production.move_raw_ids.value = original + 500.0
        production._dw_recompute_actual_cost()

        line.invalidate_recordset()
        self.assertEqual(line.state, "approved")
        self.assertAlmostEqual(line.amount, original, places=2)
        self.assertTrue(line.revision_ids)
        self.assertAlmostEqual(line.revision_ids[0].new_amount, original + 500.0, places=2)

        # With the company option enabled the engine may update it.
        self.company.dw_allow_update_approved_cost = True
        production._dw_recompute_actual_cost()
        line.invalidate_recordset()
        self.assertAlmostEqual(line.amount, original + 500.0, places=2)

    def test_07_approved_lines_cannot_be_deleted(self):
        production = self._build()
        self._produce(production)
        production._dw_recompute_actual_cost()
        line = production.dw_cost_line_ids[0]
        line.action_approve()
        with self.assertRaises(UserError):
            line.unlink()

    def test_08_scrap_from_stock_adds_cost_scrap_from_wip_does_not(self):
        production = self._build()
        self._produce(production)

        scrap_from_stock = self.env["stock.scrap"].create({
            "product_id": self.mat_tube40.id,
            "scrap_qty": 3.0,
            "product_uom_id": self.mat_tube40.uom_id.id,
            "production_id": production.id,
            "location_id": self.stock_location.id,
            "company_id": self.company.id,
            "dw_reason_id": self.env.ref("dw_manufacturing.scrap_reason_cutting").id,
        })
        scrap_from_stock.action_validate()
        production._dw_recompute_actual_cost()

        scrap_lines = production.dw_cost_line_ids.filtered(lambda l: l.cost_type == "scrap")
        self.assertEqual(len(scrap_lines), 1)
        self.assertAlmostEqual(scrap_lines.amount, 3.0 * 15.0, places=2)
        self.assertTrue(scrap_lines.weight_kg > 0)

        scrap_from_wip = self.env["stock.scrap"].create({
            "product_id": self.mat_tube40.id,
            "scrap_qty": 1.0,
            "product_uom_id": self.mat_tube40.uom_id.id,
            "production_id": production.id,
            "location_id": self.production_location.id,
            "company_id": self.company.id,
            "dw_reason_id": self.env.ref("dw_manufacturing.scrap_reason_defect").id,
            "dw_approved": True,
        })
        scrap_from_wip.action_validate()
        production._dw_recompute_actual_cost()
        wip_line = production.dw_cost_line_ids.filtered(
            lambda l: l.source_key == "scrap:%s" % scrap_from_wip.id
        )
        self.assertEqual(wip_line.amount, 0.0, "Already consumed material must not be charged twice")
        self.assertTrue(wip_line.weight_kg > 0)

    def test_09_scrap_reason_can_require_approval(self):
        production = self._build()
        self._produce(production)
        scrap = self.env["stock.scrap"].create({
            "product_id": self.mat_tube40.id,
            "scrap_qty": 1.0,
            "product_uom_id": self.mat_tube40.uom_id.id,
            "production_id": production.id,
            "location_id": self.stock_location.id,
            "company_id": self.company.id,
            "dw_reason_id": self.env.ref("dw_manufacturing.scrap_reason_defect").id,
        })
        with self.assertRaises(UserError):
            scrap.action_validate()
        scrap.action_dw_approve()
        scrap.action_validate()
        self.assertEqual(scrap.state, "done")

    def test_10_expenses_and_overhead(self):
        production = self._build()
        self._produce(production)

        entry = self.env["dw.project.cost.entry"].create({
            "name": "Site delivery",
            "company_id": self.company.id,
            "project_id": self.order.dw_project_id.id,
            "production_id": production.id,
            "cost_type": "transport",
            "quantity": 1.0,
            "unit_price": 750.0,
        })
        production._dw_recompute_actual_cost()
        self.assertFalse(
            production.dw_cost_line_ids.filtered(lambda l: l.cost_type == "transport")
        )
        entry.action_approve()
        transport = production.dw_cost_line_ids.filtered(lambda l: l.cost_type == "transport")
        self.assertAlmostEqual(transport.amount, 750.0, places=2)

        self.env["dw.overhead.rule"].create({
            "name": "10 % of direct cost",
            "company_id": self.company.id,
            "method": "percent_direct",
            "rate": 10.0,
        })
        production._dw_recompute_actual_cost()
        overhead = production.dw_cost_line_ids.filtered(lambda l: l.cost_type == "overhead")
        self.assertEqual(len(overhead), 1)
        self.assertTrue(overhead.amount > 0)
        # Still idempotent with overhead in play.
        before = production.dw_actual_cost
        production._dw_recompute_actual_cost()
        self.assertAlmostEqual(production.dw_actual_cost, before, places=6)

    def test_11_customer_supplied_material_is_not_charged(self):
        self.env["dw.component.rule"].create({
            "name": "Customer glass",
            "family_id": self.family.id,
            "company_id": self.company.id,
            "component_product_id": self.mat_customer.id,
            "component_kind": "customer_supplied",
            "calc_method": "variable",
            "basis": "area",
            "factor": 1.0,
        })
        self.item.action_generate_components()
        line = self.item.component_line_ids.filtered(
            lambda l: l.product_id == self.mat_customer
        )
        self.assertEqual(line.estimated_total_cost, 0.0)

        self._stock(self.mat_customer, 100.0)
        production = self._build()
        self._produce(production)
        production._dw_recompute_actual_cost()
        cost_line = production.dw_cost_line_ids.filtered(
            lambda l: l.product_id == self.mat_customer
        )
        self.assertEqual(cost_line.amount, 0.0)

    def test_12_offcut_uses_standard_stock_moves(self):
        production = self._build()
        self._produce(production)
        offcut = self.env["dw.material.offcut"].create({
            "product_id": self.mat_tube40.id,
            "quantity": 1.5,
            "company_id": self.company.id,
            "production_id": production.id,
            "location_id": self.stock_location.id,
        })
        quantity_before = self.env["stock.quant"]._get_available_quantity(
            self.mat_tube40, self.stock_location
        )
        offcut.action_return_to_stock()
        quantity_after = self.env["stock.quant"]._get_available_quantity(
            self.mat_tube40, self.stock_location
        )
        self.assertAlmostEqual(quantity_after - quantity_before, 1.5, places=4)
        self.assertEqual(offcut.state, "available")
        self.assertEqual(offcut.move_ids.state, "done")
        self.assertTrue(offcut.barcode)

    def test_13_unique_source_key_constraint(self):
        production = self._build()
        self._produce(production)
        production._dw_recompute_actual_cost()
        line = production.dw_cost_line_ids[0]
        with self.assertRaises(Exception):
            with self.cr.savepoint():
                line.copy({"source_key": line.source_key})
                self.env.flush_all()
