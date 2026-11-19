# -*- coding: utf-8 -*-
"""Quality templates, checks, the mandatory gate and rework."""

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import DwCommon


@tagged("post_install", "-at_install", "dw_manufacturing")
class TestQuality(DwCommon):

    def setUp(self):
        super().setUp()
        self.family = self.env["dw.product.family"].create({
            "name": "Quality Family",
            "code": "QF",
            "product_kind": "door",
            "company_id": self.company.id,
            "dimension_ids": self._dims("width", "height", "leaf_count"),
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
        self.template = self.env["dw.quality.template"].create({
            "name": "Door final inspection",
            "family_id": self.family.id,
            "stage": "final",
            "is_mandatory": True,
            "company_id": self.company.id,
            "line_ids": [
                Command.create({
                    "sequence": 10,
                    "name": "Door width",
                    "measure_type": "numeric",
                    "uom_label": "mm",
                    "target_value": 1200.0,
                    "min_value": 1195.0,
                    "max_value": 1205.0,
                }),
                Command.create({
                    "sequence": 20,
                    "name": "Opens and closes smoothly",
                    "measure_type": "boolean",
                    "expected_boolean": True,
                }),
                Command.create({
                    "sequence": 30,
                    "name": "Paint colour",
                    "measure_type": "selection",
                    "allowed_values": "RAL 9010, RAL 7016",
                    "is_blocking": False,
                }),
            ],
        })
        self.order = self._make_sale_order()
        self.item = self.env["dw.opening"].create({
            "sale_order_id": self.order.id,
            "family_id": self.family.id,
            "finished_product_id": self.product_door.id,
            "width_mm": 1200.0,
            "height_mm": 2200.0,
            "quantity": 1.0,
        })
        self.item.action_generate_components()
        self.item.action_sync_quotation_line()
        self.order.action_confirm()
        self._stock(self.mat_tube40, 200.0)
        self.item.action_create_manufacturing_order()
        self.production = self.item.production_id

    # ------------------------------------------------------------------
    def test_01_checks_created_from_family_template(self):
        checks = self.production.dw_quality_check_ids
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks.template_id, self.template)
        self.assertEqual(len(checks.line_ids), 3)
        self.assertEqual(checks.result, "pending")
        self.assertEqual(self.production.dw_quality_state, "pending")

    def test_02_numeric_tolerance_pass_and_fail(self):
        check = self.production.dw_quality_check_ids
        width_line = check.line_ids.filtered(lambda l: l.name == "Door width")
        width_line.measured_value = 1200.0
        self.assertEqual(width_line.result, "pass")
        width_line.measured_value = 1250.0
        self.assertEqual(width_line.result, "fail")
        self.assertAlmostEqual(width_line.deviation, 50.0)

    def test_03_boolean_and_selection_tests(self):
        check = self.production.dw_quality_check_ids
        smooth = check.line_ids.filtered(lambda l: l.measure_type == "boolean")
        smooth.boolean_value = "no"
        self.assertEqual(smooth.result, "fail")
        smooth.boolean_value = "yes"
        self.assertEqual(smooth.result, "pass")

        colour = check.line_ids.filtered(lambda l: l.measure_type == "selection")
        colour.text_value = "RAL 5010"
        self.assertEqual(colour.result, "fail")
        colour.text_value = "RAL 9010"
        self.assertEqual(colour.result, "pass")

    def test_04_mandatory_check_blocks_mark_done(self):
        self.production.action_assign()
        self.production.qty_producing = self.production.product_qty
        for move in self.production.move_raw_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        with self.assertRaises(UserError):
            self.production.button_mark_done()

    def test_05_validation_flow_pass_then_close(self):
        check = self.production.dw_quality_check_ids
        for line in check.line_ids:
            if line.measure_type == "numeric":
                line.measured_value = 1200.0
            elif line.measure_type == "boolean":
                line.boolean_value = "yes"
            else:
                line.text_value = "RAL 9010"
        check.action_validate()
        self.assertEqual(check.result, "pass")
        self.assertEqual(check.release_decision, "release")
        self.assertEqual(self.production.dw_quality_state, "pass")
        self._produce(self.production)
        self.assertEqual(self.production.state, "done")
        self.assertEqual(self.item.state, "ready")

    def test_06_blocking_failure_creates_issue_and_rejects(self):
        check = self.production.dw_quality_check_ids
        for line in check.line_ids:
            if line.measure_type == "numeric":
                line.measured_value = 1400.0
            elif line.measure_type == "boolean":
                line.boolean_value = "yes"
            else:
                line.text_value = "RAL 9010"
        check.action_validate()
        self.assertEqual(check.result, "fail")
        self.assertEqual(check.release_decision, "reject")
        self.assertTrue(check.issue_ids)
        self.assertEqual(check.issue_ids.severity, "major")
        self.assertEqual(self.item.quality_state, "fail")
        with self.assertRaises(UserError):
            self.item.action_set_delivered()

    def test_07_non_blocking_failure_asks_for_rework(self):
        check = self.production.dw_quality_check_ids
        for line in check.line_ids:
            if line.measure_type == "numeric":
                line.measured_value = 1200.0
            elif line.measure_type == "boolean":
                line.boolean_value = "yes"
            else:
                line.text_value = "RAL 3000"
        check.action_validate()
        self.assertEqual(check.result, "rework")
        self.assertEqual(self.production.dw_quality_state, "rework")
        self.assertTrue(check.issue_ids)
        self.assertEqual(check.issue_ids.severity, "minor")

    def test_08_rework_cost_reaches_the_cost_ledger(self):
        check = self.production.dw_quality_check_ids
        for line in check.line_ids:
            if line.measure_type == "numeric":
                line.measured_value = 1200.0
            elif line.measure_type == "boolean":
                line.boolean_value = "yes"
            else:
                line.text_value = "RAL 3000"
        check.action_validate()
        issue = check.issue_ids
        issue.write({"rework_required": True, "rework_cost": 320.0})
        self.production._dw_recompute_actual_cost()
        rework_lines = self.production.dw_cost_line_ids.filtered(
            lambda l: l.cost_type == "rework"
        )
        self.assertEqual(len(rework_lines), 1)
        self.assertAlmostEqual(rework_lines.amount, 320.0, places=2)
        # Recomputing does not duplicate the rework line.
        self.production._dw_recompute_actual_cost()
        self.assertEqual(
            len(self.production.dw_cost_line_ids.filtered(lambda l: l.cost_type == "rework")), 1
        )

    def test_09_validated_check_cannot_be_deleted(self):
        check = self.production.dw_quality_check_ids
        for line in check.line_ids:
            if line.measure_type == "numeric":
                line.measured_value = 1200.0
            elif line.measure_type == "boolean":
                line.boolean_value = "yes"
            else:
                line.text_value = "RAL 9010"
        check.action_validate()
        with self.assertRaises(UserError):
            check.unlink()

    def test_10_gate_can_be_disabled_per_company(self):
        self.company.dw_block_on_quality_failure = False
        self._produce(self.production)
        self.assertEqual(self.production.state, "done")

    def test_11_alerts_are_raised(self):
        check = self.production.dw_quality_check_ids
        for line in check.line_ids:
            if line.measure_type == "numeric":
                line.measured_value = 1400.0
            elif line.measure_type == "boolean":
                line.boolean_value = "yes"
            else:
                line.text_value = "RAL 9010"
        check.action_validate()
        self.production._dw_scan_alerts()
        alerts = self.env["dw.alert"].search([
            ("production_id", "=", self.production.id),
            ("alert_type", "=", "quality_failure"),
        ])
        self.assertEqual(len(alerts), 1)
        # Scanning again keeps a single open alert.
        self.production._dw_scan_alerts()
        alerts = self.env["dw.alert"].search([
            ("production_id", "=", self.production.id),
            ("alert_type", "=", "quality_failure"),
        ])
        self.assertEqual(len(alerts), 1)
