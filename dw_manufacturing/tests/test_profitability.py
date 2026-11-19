# -*- coding: utf-8 -*-
"""Revenue recognition, credit notes, internal transfer value and the
profitability analysis views."""

from odoo import Command
from odoo.tests import tagged

from .common import DwCommon


@tagged("post_install", "-at_install", "dw_manufacturing")
class TestProfitability(DwCommon):

    def setUp(self):
        super().setUp()
        self.family = self.env["dw.product.family"].create({
            "name": "Profit Family",
            "code": "PF",
            "product_kind": "gate",
            "company_id": self.company.id,
            "dimension_ids": self._dims("width", "height"),
        })
        self.env["dw.component.rule"].create({
            "name": "Frame",
            "family_id": self.family.id,
            "company_id": self.company.id,
            "component_product_id": self.mat_tube40.id,
            "calc_method": "variable",
            "basis": "perimeter",
            "factor": 1.0,
        })

    def _make_item(self, relationship="external", price=5000.0):
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "dw_is_manufacturing_quote": True,
            "dw_relationship": relationship,
        })
        item = self.env["dw.opening"].create({
            "sale_order_id": order.id,
            "family_id": self.family.id,
            "finished_product_id": self.product_door.id,
            "width_mm": 2000.0,
            "height_mm": 2000.0,
            "quantity": 1.0,
            "selling_price_unit": price,
        })
        item.action_generate_components()
        item.selling_price_unit = price
        item.action_sync_quotation_line()
        order.action_confirm()
        return order, item

    # ------------------------------------------------------------------
    def test_01_quotation_is_not_revenue(self):
        order = self._make_sale_order()
        item = self.env["dw.opening"].create({
            "sale_order_id": order.id,
            "family_id": self.family.id,
            "finished_product_id": self.product_door.id,
            "width_mm": 2000.0,
            "height_mm": 2000.0,
            "quantity": 1.0,
            "selling_price_unit": 4000.0,
        })
        item.action_generate_components()
        item.action_sync_quotation_line()
        self.assertAlmostEqual(item.expected_revenue, 4000.0, places=2)
        self.assertEqual(item.invoiced_revenue, 0.0)
        self.assertEqual(item.actual_revenue, 0.0)

    def test_02_only_posted_invoices_count(self):
        order, item = self._make_item()
        invoice = order._create_invoices()
        item.invalidate_recordset()
        self.assertEqual(item.invoiced_revenue, 0.0, "A draft invoice is not revenue")
        invoice.action_post()
        item.invalidate_recordset()
        self.assertAlmostEqual(item.invoiced_revenue, 5000.0, places=2)
        self.assertAlmostEqual(item.actual_revenue, 5000.0, places=2)

    def test_03_credit_note_reduces_revenue(self):
        order, item = self._make_item()
        invoice = order._create_invoices()
        invoice.action_post()
        item.invalidate_recordset()
        self.assertAlmostEqual(item.invoiced_revenue, 5000.0, places=2)

        wizard = self.env["account.move.reversal"].with_context(
            active_model="account.move", active_ids=invoice.ids
        ).create({
            "journal_id": invoice.journal_id.id,
            "reason": "Partial return",
        })
        action = wizard.reverse_moves()
        credit_note = self.env["account.move"].browse(action["res_id"])
        credit_note.invoice_line_ids.filtered("sale_line_ids").write({"price_unit": 1500.0})
        credit_note.action_post()

        item.invalidate_recordset()
        self.assertAlmostEqual(item.invoiced_revenue, 3500.0, places=2)
        self.assertAlmostEqual(item.actual_revenue, 3500.0, places=2)

    def test_04_internal_work_produces_no_accounting_revenue(self):
        order, item = self._make_item(relationship="main_same_entity", price=8000.0)
        item.invalidate_recordset()
        self.assertEqual(item.actual_revenue, 0.0)
        self.assertAlmostEqual(item.internal_transfer_value, 8000.0, places=2)
        # Profit is measured against the transfer value, not an invented sale.
        self.assertAlmostEqual(
            item.actual_profit, 8000.0 - item.actual_cost, places=2
        )

    def test_05_separate_legal_entity_behaves_like_a_customer(self):
        order, item = self._make_item(relationship="main_separate_entity", price=6000.0)
        invoice = order._create_invoices()
        invoice.action_post()
        item.invalidate_recordset()
        self.assertAlmostEqual(item.actual_revenue, 6000.0, places=2)
        self.assertEqual(item.internal_transfer_value, 0.0)

    def test_06_project_and_order_roll_up(self):
        order, item = self._make_item(price=7000.0)
        self._stock(self.mat_tube40, 100.0)
        item.action_create_manufacturing_order()
        self._produce(item.production_id)
        item.production_id._dw_recompute_actual_cost()

        invoice = order._create_invoices()
        invoice.action_post()
        order.invalidate_recordset()
        item.invalidate_recordset()

        project = order.dw_project_id
        self.assertAlmostEqual(order.dw_actual_cost, item.actual_cost, places=2)
        self.assertAlmostEqual(project.dw_invoiced_revenue, 7000.0, places=2)
        self.assertAlmostEqual(project.dw_actual_cost, item.actual_cost, places=2)
        self.assertAlmostEqual(
            project.dw_actual_profit, 7000.0 - item.actual_cost, places=2
        )
        self.assertTrue(project.dw_completion_percent > 0)

    def test_07_standalone_project_expense_hits_project_cost(self):
        order, item = self._make_item()
        project = order.dw_project_id
        before = project.dw_actual_cost
        entry = self.env["dw.project.cost.entry"].create({
            "name": "Site crane rental",
            "company_id": self.company.id,
            "project_id": project.id,
            "cost_type": "rental",
            "quantity": 1.0,
            "unit_price": 2200.0,
        })
        entry.action_approve()
        project.invalidate_recordset()
        self.assertAlmostEqual(project.dw_actual_cost, before + 2200.0, places=2)

    def test_08_analysis_views_return_rows(self):
        order, item = self._make_item(price=9000.0)
        self._stock(self.mat_tube40, 100.0)
        item.action_create_manufacturing_order()
        self._produce(item.production_id)
        item.production_id._dw_recompute_actual_cost()
        invoice = order._create_invoices()
        invoice.action_post()

        self.env.flush_all()
        rows = self.env["dw.profitability.report"].search([("opening_id", "=", item.id)])
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows.invoiced_revenue, 9000.0, places=2)
        self.assertTrue(rows.actual_cost > 0)
        self.assertTrue(rows.cost_per_m2 > 0)

        variance = self.env["dw.cost.variance.report"].search([
            ("production_id", "=", item.production_id.id)
        ])
        self.assertEqual(len(variance), 1)
        self.assertAlmostEqual(variance.actual_cost, item.production_id.dw_actual_cost, places=2)

    def test_09_overhead_rule_methods(self):
        rule = self.env["dw.overhead.rule"].create({
            "name": "Per kg overhead",
            "company_id": self.company.id,
            "method": "per_kg",
            "rate": 1.5,
        })
        order, item = self._make_item()
        amount = rule._compute_amount(item)
        self.assertAlmostEqual(amount, item.planned_weight_kg * 1.5, places=4)

        rule.method = "percent_material"
        rule.rate = 20.0
        self.assertAlmostEqual(
            rule._compute_amount(item, material_cost=1000.0), 200.0, places=4
        )
        rule.method = "per_hour"
        rule.rate = 12.0
        self.assertAlmostEqual(rule._compute_amount(item, hours=3.0), 36.0, places=4)
        rule.method = "fixed"
        rule.rate = 500.0
        self.assertAlmostEqual(rule._compute_amount(item), 500.0, places=4)

    def test_10_estimate_uses_overhead_rule(self):
        rule = self.env["dw.overhead.rule"].create({
            "name": "10 percent of direct",
            "company_id": self.company.id,
            "method": "percent_direct",
            "rate": 10.0,
        })
        order, item = self._make_item()
        item.overhead_rule_id = rule
        item.invalidate_recordset()
        direct = (
            item.material_cost + item.labor_cost + item.machine_cost
            + item.subcontract_cost + item.contractor_cost + item.transport_cost
            + item.installation_cost + item.direct_expense_cost + item.manual_cost
        )
        self.assertAlmostEqual(item.overhead_cost, direct * 0.1, places=4)
        self.assertAlmostEqual(item.estimated_cost, direct * 1.1, places=4)

    def test_11_manual_estimate_items_need_approval(self):
        order, item = self._make_item()
        before = item.estimated_cost
        line = self.env["dw.opening.extra.cost"].create({
            "opening_id": item.id,
            "name": "Special tooling",
            "cost_type": "direct",
            "amount": 900.0,
        })
        item.invalidate_recordset()
        self.assertAlmostEqual(item.estimated_cost, before, places=2)
        line.action_approve()
        item.invalidate_recordset()
        self.assertAlmostEqual(item.estimated_cost, before + 900.0, places=2)
