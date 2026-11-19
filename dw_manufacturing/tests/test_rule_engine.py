# -*- coding: utf-8 -*-
from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import DwCommon


@tagged("post_install", "-at_install", "dw_manufacturing")
class TestRuleEngine(DwCommon):
    """The component / quantity engine must be exact, safe and configurable."""

    def setUp(self):
        super().setUp()
        self.family = self.env["dw.product.family"].create({
            "name": "Test Fence",
            "code": "TFENCE",
            "product_kind": "fence",
            "quantity_method": "length",
            "company_id": self.company.id,
            "dimension_ids": self._dims(
                "length", "height", "post_count", "section_count",
                "post_spacing", "weld_length", "paint_area",
            ),
        })
        self.item = self.env["dw.opening"].create({
            "family_id": self.family.id,
            "finished_product_id": self.product_fence.id,
            "company_id": self.company.id,
            "length_mm": 20000.0,
            "height_mm": 2000.0,
            "post_spacing_mm": 2500.0,
            "quantity": 1.0,
        })

    # ------------------------------------------------------------------
    def test_01_derived_measurements(self):
        item = self.item
        self.assertAlmostEqual(item.length_m, 20.0)
        self.assertAlmostEqual(item.height_m, 2.0)
        self.assertAlmostEqual(item.area_m2, 40.0)
        self.assertAlmostEqual(item.perimeter_m, 44.0)
        self.assertAlmostEqual(item.total_length_m, 20.0)
        # 20 m at 2.5 m spacing -> 8 spans, 9 posts
        self.assertEqual(item.section_count, 8)
        self.assertEqual(item.post_count, 9)

    def test_02_single_variable_rule(self):
        rule = self.env["dw.component.rule"].create({
            "name": "Mesh by area",
            "family_id": self.family.id,
            "component_product_id": self.mat_mesh.id,
            "calc_method": "variable",
            "basis": "area",
            "factor": 1.0,
            "waste_percent": 10.0,
            "company_id": self.company.id,
        })
        # 40 m2 + 10 % waste
        self.assertAlmostEqual(rule.calculate_quantity(self.item), 44.0, places=6)

    def test_03_guided_formula_no_eval(self):
        """post_count x height x 1.05 built from ordered typed terms."""
        rule = self.env["dw.component.rule"].create({
            "name": "Posts",
            "family_id": self.family.id,
            "component_product_id": self.mat_tube50.id,
            "calc_method": "formula",
            "company_id": self.company.id,
            "term_ids": [
                Command.create({"sequence": 1, "operand_type": "variable", "variable": "post_count"}),
                Command.create({"sequence": 2, "operator": "*", "operand_type": "variable", "variable": "height"}),
                Command.create({"sequence": 3, "operator": "*", "operand_type": "constant", "constant_value": 1.05}),
            ],
        })
        self.assertAlmostEqual(rule.calculate_quantity(self.item), 9 * 2.0 * 1.05, places=6)
        self.assertIn("Post Count", rule.formula_preview)

    def test_04_formula_operators_are_left_to_right(self):
        rule = self.env["dw.component.rule"].create({
            "name": "Steps minus one",
            "family_id": self.family.id,
            "component_product_id": self.mat_tube40.id,
            "calc_method": "formula",
            "company_id": self.company.id,
            "term_ids": [
                Command.create({"sequence": 1, "operand_type": "variable", "variable": "length"}),
                Command.create({"sequence": 2, "operator": "+", "operand_type": "constant", "constant_value": 4.0}),
                Command.create({"sequence": 3, "operator": "*", "operand_type": "constant", "constant_value": 2.0}),
            ],
        })
        # (20 + 4) * 2 = 48, strictly left to right, not 20 + (4 * 2)
        self.assertAlmostEqual(rule.calculate_quantity(self.item), 48.0, places=6)

    def test_05_division_by_zero_is_safe(self):
        rule = self.env["dw.component.rule"].create({
            "name": "Divide by empty variable",
            "family_id": self.family.id,
            "component_product_id": self.mat_tube40.id,
            "calc_method": "formula",
            "company_id": self.company.id,
            "term_ids": [
                Command.create({"sequence": 1, "operand_type": "variable", "variable": "length"}),
                Command.create({"sequence": 2, "operator": "/", "operand_type": "variable", "variable": "step_count"}),
            ],
        })
        self.assertEqual(rule.calculate_quantity(self.item), 0.0)

    def test_06_commercial_length_rounding(self):
        rule = self.env["dw.component.rule"].create({
            "name": "Rails in 6 m bars",
            "family_id": self.family.id,
            "component_product_id": self.mat_tube40.id,
            "calc_method": "variable",
            "basis": "length",
            "factor": 2.0,
            "round_commercial": True,
            "commercial_length_m": 6.0,
            "commercial_output": "length",
            "company_id": self.company.id,
        })
        # 40 m needed -> 7 bars of 6 m -> 42 m
        self.assertAlmostEqual(rule.calculate_quantity(self.item), 42.0, places=6)
        rule.commercial_output = "pieces"
        self.assertAlmostEqual(rule.calculate_quantity(self.item), 7.0, places=6)

    def test_07_rounding_modes_and_minimum(self):
        rule = self.env["dw.component.rule"].create({
            "name": "Rounded pieces",
            "family_id": self.family.id,
            "component_product_id": self.mat_hinge.id,
            "calc_method": "variable",
            "basis": "height",
            "factor": 1.3,
            "round_mode": "up",
            "company_id": self.company.id,
        })
        # 2.0 x 1.3 = 2.6 -> 3
        self.assertAlmostEqual(rule.calculate_quantity(self.item), 3.0)
        rule.round_mode = "down"
        self.assertAlmostEqual(rule.calculate_quantity(self.item), 2.0)
        rule.round_mode = "nearest"
        self.assertAlmostEqual(rule.calculate_quantity(self.item), 3.0)
        rule.round_mode = "none"
        rule.min_qty = 10.0
        self.assertAlmostEqual(rule.calculate_quantity(self.item), 10.0)

    def test_08_rounding_multiple(self):
        rule = self.env["dw.component.rule"].create({
            "name": "Sheet in half units",
            "family_id": self.family.id,
            "component_product_id": self.mat_sheet.id,
            "calc_method": "variable",
            "basis": "area",
            "factor": 0.13,
            "rounding_multiple": 0.5,
            "round_mode": "up",
            "company_id": self.company.id,
        })
        # 40 x 0.13 = 5.2 -> 5.5
        self.assertAlmostEqual(rule.calculate_quantity(self.item), 5.5, places=6)

    def test_09_conditions_gate_the_rule(self):
        rule = self.env["dw.component.rule"].create({
            "name": "Extra bracing on tall fences",
            "family_id": self.family.id,
            "component_product_id": self.mat_tube40.id,
            "calc_method": "variable",
            "basis": "length",
            "factor": 1.0,
            "company_id": self.company.id,
            "condition_ids": [
                Command.create({"variable": "height", "operator": ">", "value": 2.5}),
            ],
        })
        self.assertEqual(rule.calculate_quantity(self.item), 0.0)
        self.item.height_mm = 3000.0
        self.assertAlmostEqual(rule.calculate_quantity(self.item), 20.0)

    def test_10_conversion_factor_and_extra(self):
        rule = self.env["dw.component.rule"].create({
            "name": "Paint litres",
            "family_id": self.family.id,
            "component_product_id": self.mat_paint.id,
            "calc_method": "variable",
            "basis": "paint_area",
            "factor": 1.0,
            "conversion_factor": 0.125,
            "extra_qty": 0.0,
            "company_id": self.company.id,
        })
        expected = self.item.paint_area_m2 * 0.125
        self.assertAlmostEqual(rule.calculate_quantity(self.item), expected, places=6)
        rule.extra_qty = 2.0
        self.assertAlmostEqual(
            rule.calculate_quantity(self.item),
            (self.item.paint_area_m2 + 2.0) * 0.125,
            places=6,
        )

    def test_11_negative_values_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["dw.component.rule"].create({
                "name": "Bad rule",
                "family_id": self.family.id,
                "component_product_id": self.mat_tube40.id,
                "calc_method": "variable",
                "basis": "area",
                "factor": -1.0,
                "company_id": self.company.id,
            })

    def test_12_formula_needs_terms(self):
        with self.assertRaises(ValidationError):
            self.env["dw.component.rule"].create({
                "name": "Empty formula",
                "family_id": self.family.id,
                "component_product_id": self.mat_tube40.id,
                "calc_method": "formula",
                "company_id": self.company.id,
            })

    def test_13_engine_never_evaluates_code(self):
        """A string that looks like code can only ever be stored as a label."""
        rule = self.env["dw.component.rule"].create({
            "name": "__import__('os').system('echo pwned')",
            "family_id": self.family.id,
            "component_product_id": self.mat_tube40.id,
            "calc_method": "variable",
            "basis": "area",
            "factor": 1.0,
            "company_id": self.company.id,
        })
        self.assertAlmostEqual(rule.calculate_quantity(self.item), 40.0)
        # The engine exposes no field that carries an expression to evaluate.
        for field_name in ("basis", "calc_method"):
            self.assertIn(field_name, rule._fields)
        self.assertNotIn("expression", rule._fields)
        self.assertNotIn("python_code", rule._fields)

    def test_14_legacy_rule_still_matches(self):
        """Phase 1 rules have no family: they must keep matching by product."""
        legacy_item = self.env["dw.opening"].create({
            "finished_product_id": self.product_door.id,
            "company_id": self.company.id,
            "opening_type": "door",
            "width_mm": 1000.0,
            "height_mm": 2100.0,
            "quantity": 2.0,
        })
        legacy_rule = self.env["dw.component.rule"].create({
            "name": "Legacy perimeter rule",
            "finished_product_tmpl_id": self.product_door.product_tmpl_id.id,
            "opening_type": "door",
            "component_product_id": self.mat_tube40.id,
            "basis": "perimeter",
            "factor": 1.0,
            "waste_percent": 10.0,
            "company_id": self.company.id,
        })
        rules = self.env["dw.component.rule"]._rules_for_item(legacy_item)
        self.assertIn(legacy_rule, rules)
        self.assertAlmostEqual(
            legacy_rule.calculate_quantity(legacy_item), 6.2 * 1.1, places=6
        )


@tagged("post_install", "-at_install", "dw_manufacturing")
class TestFamilyWithoutConfiguration(DwCommon):
    """A family saved without dimensions or rules must never dead-end the user."""

    def setUp(self):
        super().setUp()
        # Exactly the situation reported from the field: a family created with a
        # name and a kind, but no dimension and no component rule.
        self.bare_family = self.env["dw.product.family"].create({
            "name": "Door 6x7",
            "code": "BARE",
            "product_kind": "door",
            "company_id": self.company.id,
        })
        self.item = self.env["dw.opening"].create({
            "family_id": self.bare_family.id,
            "finished_product_id": self.product_door.id,
            "company_id": self.company.id,
            "quantity": 1.0,
        })

    def test_01_dimensions_fall_back_to_the_product_kind_preset(self):
        self.assertTrue(self.bare_family.uses_default_dimensions)
        codes = self.item.visible_dimension_codes
        for code in ("width", "height", "thickness", "leaf_count"):
            self.assertIn(",%s," % code, codes, code)
        # A staircase-only dimension must not appear on a door.
        self.assertNotIn(",step_count,", codes)

    def test_02_unknown_kind_still_gets_a_usable_set(self):
        family = self.env["dw.product.family"].create({
            "name": "Something new", "code": "NEW1",
            "product_kind": "custom", "company_id": self.company.id,
        })
        item = self.env["dw.opening"].create({
            "family_id": family.id,
            "finished_product_id": self.product_door.id,
            "company_id": self.company.id,
            "quantity": 1.0,
        })
        for code in ("length", "width", "height"):
            self.assertIn(",%s," % code, item.visible_dimension_codes, code)

    def test_03_warning_explains_what_is_missing(self):
        warning = self.item.setup_warning
        self.assertTrue(warning)
        self.assertIn("Door 6x7", warning)
        self.assertEqual(self.item.family_rule_count, 0)

    def test_04_generate_components_gives_an_actionable_error(self):
        with self.assertRaises(UserError) as caught:
            self.item.action_generate_components()
        message = str(caught.exception)
        self.assertIn("Door 6x7", message)
        self.assertIn("Components tab", message)

    def test_05_manual_component_lines_unblock_the_flow(self):
        self.item.width_mm = 1800.0
        self.item.height_mm = 2100.0
        self.env["dw.opening.component"].create({
            "opening_id": self.item.id,
            "product_id": self.mat_tube40.id,
            "qty_per_unit": 8.0,
        })
        self.item.invalidate_recordset()
        # No rule exists, yet the button must now succeed instead of blocking.
        self.item.action_generate_components()
        self.assertEqual(len(self.item.component_line_ids), 1)
        self.assertAlmostEqual(self.item.material_cost, 8.0 * 15.0, places=2)
        self.assertFalse(
            "No component rule is defined" in (self.item.setup_warning or "")
        )

        order = self._make_sale_order()
        self.item.sale_order_id = order
        self.item.action_sync_quotation_line()
        self.assertEqual(self.item.state, "quoted")

    def test_06_applying_the_standard_set_fills_the_family(self):
        self.bare_family.action_apply_default_dimensions()
        self.assertTrue(self.bare_family.dimension_ids)
        self.assertFalse(self.bare_family.uses_default_dimensions)
        self.assertIn("width", self.bare_family.dimension_ids.mapped("code"))


@tagged("post_install", "-at_install", "dw_manufacturing")
class TestStageProgression(DwCommon):
    """The whole draft -> delivered path, with nothing ticked by hand."""

    def setUp(self):
        super().setUp()
        self.family = self.env["dw.product.family"].create({
            "name": "Progression Door", "code": "PROG",
            "product_kind": "door", "company_id": self.company.id,
            "dimension_ids": self._dims("width", "height"),
            "pricing_method": "cost_plus", "default_markup_percent": 25.0,
        })
        self.env["dw.component.rule"].create({
            "name": "Frame tube", "family_id": self.family.id,
            "component_product_id": self.mat_tube40.id,
            "component_kind": "material", "calc_method": "variable",
            "basis": "perimeter", "factor": 1.0,
            "company_id": self.company.id,
        })
        self.item = self.env["dw.opening"].create({
            "family_id": self.family.id,
            "finished_product_id": self.product_door.id,
            "company_id": self.company.id,
            "quantity": 1.0, "width_mm": 1000.0, "height_mm": 2100.0,
        })

    def test_01_generating_components_keeps_the_item_in_draft(self):
        self.item.action_generate_components()
        self.assertTrue(self.item.component_line_ids)
        # Generating the estimate is not a stage change: the item is still a draft.
        self.assertEqual(self.item.state, "draft")

    def test_02_syncing_the_quotation_line_moves_it_to_quoted(self):
        self.item.action_generate_components()
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        # Deliberately NOT ticking dw_is_manufacturing_quote by hand.
        self.assertFalse(order.dw_is_manufacturing_quote)
        self.item.sale_order_id = order
        self.item.action_sync_quotation_line()
        self.assertEqual(self.item.state, "quoted")
        self.assertTrue(self.item.sale_line_id)
        # Syncing flags the quotation, so the confirmation will carry the item.
        self.assertTrue(order.dw_is_manufacturing_quote)

    def test_03_confirming_the_quotation_confirms_the_item(self):
        self.item.action_generate_components()
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        self.item.sale_order_id = order
        self.item.action_sync_quotation_line()
        order.action_confirm()
        self.assertEqual(self.item.state, "confirmed")

    def test_04_an_untagged_order_still_carries_its_items(self):
        """Even when the line was attached without ever calling the sync button."""
        self.item.action_generate_components()
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        self.item.sale_order_id = order
        self.item.action_sync_quotation_line()
        order.dw_is_manufacturing_quote = False
        order.action_confirm()
        self.assertTrue(order.dw_is_manufacturing_quote)
        self.assertEqual(self.item.state, "confirmed")

    def test_05_manufacturing_order_needs_a_confirmed_item(self):
        self.item.action_generate_components()
        with self.assertRaises(UserError):
            # The sales order is still a draft quotation.
            order = self.env["sale.order"].create({"partner_id": self.partner.id})
            self.item.sale_order_id = order
            self.item.action_sync_quotation_line()
            self.item.action_create_manufacturing_order()

    def test_06_full_path_to_delivered(self):
        self.item.action_generate_components()
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        self.item.sale_order_id = order
        self.item.action_sync_quotation_line()
        order.action_confirm()
        for line in self.item.component_line_ids:
            self._stock(line.product_id, line.total_qty * 2)
        self.item.action_create_manufacturing_order()
        self.assertEqual(self.item.state, "production")
        self.assertTrue(self.item.bom_id, "the bill of materials is created on the way")
        self._produce(self.item.production_id)
        self.item.action_set_ready()
        self.assertEqual(self.item.state, "ready")
        self.item.action_set_delivered()
        self.assertEqual(self.item.state, "delivered")

    def test_07_an_item_with_no_quotation_can_still_be_produced(self):
        """A works order with no sale: confirm the item straight from the family."""
        self.item.action_generate_components()
        self.item.state = "confirmed"
        for line in self.item.component_line_ids:
            self._stock(line.product_id, line.total_qty * 2)
        self.item.action_create_manufacturing_order()
        self.assertEqual(self.item.state, "production")

    def test_08_syncing_onto_an_already_confirmed_order(self):
        """The order was confirmed before the item was ever synced."""
        self.item.action_generate_components()
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [Command.create({
                "product_id": self.product_door.id, "product_uom_qty": 1.0,
            })],
        })
        order.action_confirm()
        self.assertEqual(order.state, "sale")
        self.item.sale_order_id = order
        self.item.action_sync_quotation_line()
        # No confirmation is left to wait for, so the item lands on Confirmed.
        self.assertEqual(self.item.state, "confirmed")
        self.assertTrue(self.item.sale_line_id)
        self.assertEqual(self.item.sale_line_id.order_id, order)

    def test_09_a_locked_order_says_so(self):
        self.item.action_generate_components()
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        self.item.sale_order_id = order
        self.item.action_sync_quotation_line()
        order.action_confirm()
        order.locked = True
        with self.assertRaises(UserError):
            self.item.action_sync_quotation_line()

    def test_10_a_cancelled_order_says_so(self):
        self.item.action_generate_components()
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        self.item.sale_order_id = order
        order._action_cancel()
        with self.assertRaises(UserError):
            self.item.action_sync_quotation_line()
