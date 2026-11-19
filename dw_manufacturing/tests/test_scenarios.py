# -*- coding: utf-8 -*-
"""The four mandatory acceptance scenarios, run end to end."""

from odoo import Command
from odoo.tests import tagged

from .common import DwCommon


@tagged("post_install", "-at_install", "dw_manufacturing")
class TestScenarios(DwCommon):

    # ==================================================================
    # Scenario 1 - metal fence
    # ==================================================================
    def test_scenario_1_metal_fence(self):
        family = self.env["dw.product.family"].create({
            "name": "Metal Fence",
            "name_ar": "سياج معدني",
            "code": "FENCE",
            "product_kind": "fence",
            "quantity_method": "length",
            "weight_method": "components",
            "pricing_method": "cost_plus",
            "default_markup_percent": 30.0,
            "company_id": self.company.id,
            "default_product_id": self.product_fence.id,
            "dimension_ids": self._dims(
                "length", "height", "post_count", "section_count",
                "post_spacing", "weld_length", "paint_area", "galv_area",
            ),
            "required_dimension_ids": [Command.set([self.dim["length"].id, self.dim["height"].id])],
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
                Command.create({
                    "sequence": 30,
                    "operation_type_id": self.op_painting.id,
                    "workcenter_id": self.wc_painting.id,
                }),
            ],
        })

        # Component rules ------------------------------------------------
        self.env["dw.component.rule"].create([
            {
                "name": "Posts",
                "family_id": family.id,
                "company_id": self.company.id,
                "component_product_id": self.mat_tube50.id,
                "calc_method": "formula",
                "term_ids": [
                    Command.create({"sequence": 1, "operand_type": "variable", "variable": "post_count"}),
                    Command.create({"sequence": 2, "operator": "*", "operand_type": "variable", "variable": "height"}),
                    Command.create({"sequence": 3, "operator": "*", "operand_type": "constant", "constant_value": 1.2}),
                ],
                "waste_percent": 5.0,
            },
            {
                "name": "Horizontal rails",
                "family_id": family.id,
                "company_id": self.company.id,
                "component_product_id": self.mat_tube40.id,
                "calc_method": "formula",
                "term_ids": [
                    Command.create({"sequence": 1, "operand_type": "variable", "variable": "length"}),
                    Command.create({"sequence": 2, "operator": "*", "operand_type": "constant", "constant_value": 2.0}),
                ],
                "waste_percent": 5.0,
            },
            {
                "name": "Mesh infill",
                "family_id": family.id,
                "company_id": self.company.id,
                "component_product_id": self.mat_mesh.id,
                "calc_method": "variable",
                "basis": "area",
                "factor": 1.0,
                "waste_percent": 8.0,
            },
            {
                "name": "Paint",
                "family_id": family.id,
                "company_id": self.company.id,
                "component_product_id": self.mat_paint.id,
                "calc_method": "variable",
                "basis": "paint_area",
                "factor": 1.0,
                "conversion_factor": 0.125,
            },
            {
                "name": "Welding consumable",
                "family_id": family.id,
                "company_id": self.company.id,
                "component_product_id": self.mat_electrode.id,
                "calc_method": "variable",
                "basis": "weld_length",
                "factor": 0.12,
            },
        ])

        # Quotation -------------------------------------------------------
        order = self._make_sale_order()
        item = self.env["dw.opening"].create({
            "sale_order_id": order.id,
            "family_id": family.id,
            "finished_product_id": self.product_fence.id,
            "length_mm": 20000.0,
            "height_mm": 2000.0,
            "post_spacing_mm": 2500.0,
            "quantity": 1.0,
            "description": "Perimeter fence",
        })
        self.assertEqual(item.post_count, 9)
        self.assertEqual(item.section_count, 8)

        item.action_generate_components()
        self.assertEqual(len(item.component_line_ids), 5)
        posts = item.component_line_ids.filtered(lambda l: l.product_id == self.mat_tube50)
        self.assertAlmostEqual(posts.qty_per_unit, 9 * 2.0 * 1.2 * 1.05, places=6)
        rails = item.component_line_ids.filtered(lambda l: l.product_id == self.mat_tube40)
        self.assertAlmostEqual(rails.qty_per_unit, 20.0 * 2.0 * 1.05, places=6)
        mesh = item.component_line_ids.filtered(lambda l: l.product_id == self.mat_mesh)
        self.assertAlmostEqual(mesh.qty_per_unit, 40.0 * 1.08, places=6)
        self.assertTrue(item.material_cost > 0)
        self.assertEqual(len(item.operation_line_ids), 3)
        self.assertTrue(item.labor_cost > 0)
        self.assertTrue(item.machine_cost > 0)

        item.action_sync_quotation_line()
        self.assertTrue(item.sale_line_id)
        self.assertEqual(item.state, "quoted")

        order.action_confirm()
        self.assertEqual(item.state, "confirmed")
        self.assertTrue(order.dw_project_id)

        # Manufacturing ----------------------------------------------------
        for line in item.component_line_ids:
            self._stock(line.product_id, line.total_qty * 2)
        item.action_create_manufacturing_order()
        production = item.production_id
        self.assertTrue(production)
        self.assertEqual(production.dw_project_id, order.dw_project_id)
        self.assertEqual(len(production.bom_id.bom_line_ids), 5)

        # Labour and machine time
        for workorder in production.workorder_ids:
            workorder.duration = 60.0
        self._produce(production)
        self.assertEqual(production.state, "done")

        production._dw_recompute_actual_cost()
        self.assertTrue(production.dw_material_cost > 0)
        self.assertEqual(item.state, "ready")

        # Scrap and off-cut -------------------------------------------------
        scrap = self.env["stock.scrap"].create({
            "product_id": self.mat_tube40.id,
            "scrap_qty": 2.0,
            "product_uom_id": self.mat_tube40.uom_id.id,
            "production_id": production.id,
            "location_id": self.stock_location.id,
            "company_id": self.company.id,
            "dw_reason_id": self.env.ref("dw_manufacturing.scrap_reason_offcut").id,
        })
        scrap.action_validate()
        self.assertEqual(scrap.state, "done")
        self.assertTrue(scrap.dw_value > 0)

        offcut = self.env["dw.material.offcut"].create({
            "product_id": self.mat_tube40.id,
            "quantity": 2.0,
            "company_id": self.company.id,
            "scrap_id": scrap.id,
            "production_id": production.id,
            "opening_id": item.id,
            "location_id": self.stock_location.id,
            "length_mm": 2000.0,
        })
        offcut.action_return_to_stock()
        self.assertEqual(offcut.state, "available")
        self.assertTrue(offcut.move_ids)
        self.assertEqual(offcut.move_ids.state, "done")

        # Invoice and profitability -----------------------------------------
        invoice = order._create_invoices()
        invoice.action_post()
        item.invalidate_recordset()
        self.assertTrue(item.invoiced_revenue > 0)
        self.assertAlmostEqual(item.actual_revenue, item.invoiced_revenue, places=2)
        self.assertAlmostEqual(
            item.actual_profit, item.actual_revenue - item.actual_cost, places=2
        )
        project = order.dw_project_id
        self.assertTrue(project.dw_actual_cost > 0)
        self.assertAlmostEqual(project.dw_invoiced_revenue, item.invoiced_revenue, places=2)

    # ==================================================================
    # Scenario 2 - metal staircase with a sub-assembly
    # ==================================================================
    def test_scenario_2_metal_staircase(self):
        # Sub-assembly: one tread, produced from sheet
        tread = self._make_finished("Stair Tread")
        self.env["mrp.bom"].create({
            "product_tmpl_id": tread.product_tmpl_id.id,
            "product_id": tread.id,
            "product_qty": 1.0,
            "type": "normal",
            "company_id": self.company.id,
            "bom_line_ids": [
                Command.create({"product_id": self.mat_sheet.id, "product_qty": 0.3}),
            ],
        })

        family = self.env["dw.product.family"].create({
            "name": "Steel Staircase",
            "name_ar": "سلم معدني",
            "code": "STAIR",
            "product_kind": "staircase",
            "quantity_method": "unit",
            "weight_method": "components",
            "company_id": self.company.id,
            "dimension_ids": self._dims(
                "total_rise", "step_count", "step_height", "step_width",
                "width", "stair_angle", "weld_length", "paint_area",
            ),
            "required_dimension_ids": [
                Command.set([self.dim["total_rise"].id, self.dim["step_count"].id])
            ],
            "operation_ids": [
                Command.create({"sequence": 10, "operation_type_id": self.op_cutting.id}),
                Command.create({"sequence": 20, "operation_type_id": self.op_welding.id}),
                Command.create({"sequence": 30, "operation_type_id": self.op_assembly.id}),
                Command.create({"sequence": 40, "operation_type_id": self.op_painting.id}),
            ],
        })

        self.env["dw.component.rule"].create([
            {
                "name": "Stringers",
                "family_id": family.id,
                "company_id": self.company.id,
                "component_product_id": self.mat_tube50.id,
                "calc_method": "formula",
                "term_ids": [
                    Command.create({"sequence": 1, "operand_type": "variable", "variable": "stair_slope_length"}),
                    Command.create({"sequence": 2, "operator": "*", "operand_type": "constant", "constant_value": 2.0}),
                ],
                "waste_percent": 8.0,
            },
            {
                "name": "Treads",
                "family_id": family.id,
                "company_id": self.company.id,
                "component_product_id": tread.id,
                "component_kind": "subassembly",
                "calc_method": "variable",
                "basis": "step_count",
                "factor": 1.0,
                "round_mode": "up",
            },
            {
                "name": "Handrail",
                "family_id": family.id,
                "company_id": self.company.id,
                "component_product_id": self.mat_pipe.id,
                "calc_method": "formula",
                "term_ids": [
                    Command.create({"sequence": 1, "operand_type": "variable", "variable": "stair_slope_length"}),
                    Command.create({"sequence": 2, "operator": "*", "operand_type": "constant", "constant_value": 1.1}),
                ],
            },
            {
                "name": "Welding consumable",
                "family_id": family.id,
                "company_id": self.company.id,
                "component_product_id": self.mat_electrode.id,
                "calc_method": "variable",
                "basis": "weld_length",
                "factor": 0.15,
            },
        ])

        order = self._make_sale_order()
        item = self.env["dw.opening"].create({
            "sale_order_id": order.id,
            "family_id": family.id,
            "finished_product_id": self.product_stair.id,
            "total_rise_mm": 3200.0,
            "step_count": 16,
            "step_height_mm": 200.0,
            "step_width_mm": 280.0,
            "width_mm": 1200.0,
            "quantity": 1.0,
        })
        # Geometry: run = 16 x 0.28 = 4.48 m, rise = 3.2 m
        self.assertAlmostEqual(item.total_run_m, 4.48, places=4)
        self.assertAlmostEqual(item.stair_slope_length_m, 5.5057, places=3)
        self.assertAlmostEqual(item.stair_angle_deg, 35.5, places=1)

        item.action_generate_components()
        treads = item.component_line_ids.filtered(lambda l: l.product_id == tread)
        self.assertEqual(treads.component_kind, "subassembly")
        self.assertAlmostEqual(treads.qty_per_unit, 16.0)
        self.assertTrue(item.theoretical_weight_kg > 0)

        item.action_sync_quotation_line()
        order.action_confirm()

        for line in item.component_line_ids:
            self._stock(line.product_id, line.total_qty * 3)
        self._stock(self.mat_sheet, 100.0)

        item.action_create_manufacturing_order()
        production = item.production_id
        self.assertEqual(len(production.workorder_ids), 4)

        planned = production.dw_planned_minutes
        for workorder in production.workorder_ids:
            workorder.duration = workorder.duration_expected * 1.2
        self._produce(production)
        production._dw_recompute_actual_cost()

        self.assertTrue(production.dw_actual_minutes > planned)
        self.assertTrue(production.dw_time_variance_minutes > 0)
        self.assertTrue(production.dw_labor_cost > 0)
        self.assertTrue(production.dw_machine_cost > 0)
        self.assertTrue(production.dw_material_cost > 0)
        # The estimate and the actual both exist, so a variance can be reported.
        self.assertNotEqual(production.dw_estimated_cost, 0.0)

    # ==================================================================
    # Scenario 3 - steel door
    # ==================================================================
    def test_scenario_3_steel_door(self):
        family = self.env["dw.product.family"].create({
            "name": "Steel Door",
            "name_ar": "باب حديدي",
            "code": "DOOR",
            "product_kind": "door",
            "quantity_method": "unit",
            "company_id": self.company.id,
            "dimension_ids": self._dims(
                "width", "height", "thickness", "leaf_count", "weld_length", "paint_area",
            ),
        })
        self.env["dw.component.rule"].create([
            {
                "name": "Frame",
                "family_id": family.id,
                "company_id": self.company.id,
                "component_product_id": self.mat_tube40.id,
                "calc_method": "variable",
                "basis": "perimeter",
                "factor": 1.0,
                "waste_percent": 10.0,
            },
            {
                "name": "Leaf sheet",
                "family_id": family.id,
                "company_id": self.company.id,
                "component_product_id": self.mat_sheet.id,
                "calc_method": "formula",
                "term_ids": [
                    Command.create({"sequence": 1, "operand_type": "variable", "variable": "area"}),
                    Command.create({"sequence": 2, "operator": "*", "operand_type": "constant", "constant_value": 2.0}),
                ],
                "waste_percent": 12.0,
            },
            {
                "name": "Hinges",
                "family_id": family.id,
                "company_id": self.company.id,
                "component_product_id": self.mat_hinge.id,
                "calc_method": "formula",
                "term_ids": [
                    Command.create({"sequence": 1, "operand_type": "variable", "variable": "leaf_count"}),
                    Command.create({"sequence": 2, "operator": "*", "operand_type": "constant", "constant_value": 3.0}),
                ],
                "round_mode": "up",
            },
            {
                "name": "Lock",
                "family_id": family.id,
                "company_id": self.company.id,
                "component_product_id": self.mat_lock.id,
                "calc_method": "fixed",
                "fixed_qty": 1.0,
            },
        ])

        order = self._make_sale_order()
        item = self.env["dw.opening"].create({
            "sale_order_id": order.id,
            "family_id": family.id,
            "finished_product_id": self.product_door.id,
            "width_mm": 1200.0,
            "height_mm": 2200.0,
            "thickness_mm": 45.0,
            "leaf_count": 2,
            "quantity": 4.0,
        })
        item.action_generate_components()

        frame = item.component_line_ids.filtered(lambda l: l.product_id == self.mat_tube40)
        self.assertAlmostEqual(frame.qty_per_unit, 6.8 * 1.1, places=6)
        self.assertAlmostEqual(frame.total_qty, 6.8 * 1.1 * 4, places=6)
        hinges = item.component_line_ids.filtered(lambda l: l.product_id == self.mat_hinge)
        self.assertAlmostEqual(hinges.qty_per_unit, 6.0)
        sheet = item.component_line_ids.filtered(lambda l: l.product_id == self.mat_sheet)
        self.assertAlmostEqual(sheet.qty_per_unit, 2.64 * 2 * 1.12, places=6)

        item.action_sync_quotation_line()
        order.action_confirm()
        for line in item.component_line_ids:
            self._stock(line.product_id, line.total_qty * 2)
        item.action_create_manufacturing_order()
        production = item.production_id

        self._produce(production)
        production._dw_recompute_actual_cost()
        self.assertTrue(production.dw_material_cost > 0)

        invoice = order._create_invoices()
        invoice.action_post()
        item.invalidate_recordset()
        self.assertTrue(item.actual_revenue > 0)
        self.assertAlmostEqual(
            item.actual_profit, item.actual_revenue - item.actual_cost, places=2
        )

    # ==================================================================
    # Scenario 4 - brand new metal product, configuration only
    # ==================================================================
    def test_scenario_4_new_product_family_without_code(self):
        """A brand new family, its dimensions, rules, operations and quality
        template are created purely through configuration records."""
        family = self.env["dw.product.family"].create({
            "name": "Steel Canopy",
            "name_ar": "مظلة معدنية",
            "code": "CANOPY",
            "product_kind": "canopy",
            "quantity_method": "area",
            "weight_method": "components",
            "pricing_method": "per_m2",
            "default_price_unit": 450.0,
            "company_id": self.company.id,
            "default_product_id": self.product_canopy.id,
            "dimension_ids": self._dims(
                "length", "width", "height", "post_count", "paint_area", "galv_area",
            ),
            "operation_ids": [
                Command.create({"sequence": 10, "operation_type_id": self.op_cutting.id}),
                Command.create({"sequence": 20, "operation_type_id": self.op_welding.id}),
            ],
        })
        quality_template = self.env["dw.quality.template"].create({
            "name": "Canopy final inspection",
            "family_id": family.id,
            "stage": "final",
            "company_id": self.company.id,
            "is_mandatory": True,
            "line_ids": [
                Command.create({
                    "name": "Overall length",
                    "measure_type": "numeric",
                    "uom_label": "mm",
                    "target_value": 6000.0,
                    "tolerance": 10.0,
                }),
                Command.create({
                    "name": "Weld quality acceptable",
                    "measure_type": "boolean",
                    "expected_boolean": True,
                }),
            ],
        })
        family.quality_template_id = quality_template

        self.env["dw.component.rule"].create([
            {
                "name": "Canopy columns",
                "family_id": family.id,
                "company_id": self.company.id,
                "component_product_id": self.mat_pipe.id,
                "calc_method": "formula",
                "term_ids": [
                    Command.create({"sequence": 1, "operand_type": "variable", "variable": "post_count"}),
                    Command.create({"sequence": 2, "operator": "*", "operand_type": "variable", "variable": "height"}),
                ],
                "waste_percent": 5.0,
            },
            {
                "name": "Roof sheet",
                "family_id": family.id,
                "company_id": self.company.id,
                "component_product_id": self.mat_sheet.id,
                "calc_method": "variable",
                "basis": "area",
                "factor": 1.05,
            },
            {
                "name": "Galvanizing service",
                "family_id": family.id,
                "company_id": self.company.id,
                "component_product_id": self.service_galv.id,
                "component_kind": "service",
                "calc_method": "variable",
                "basis": "weight",
                "factor": 1.0,
            },
        ])

        order = self._make_sale_order()
        item = self.env["dw.opening"].create({
            "sale_order_id": order.id,
            "family_id": family.id,
            "finished_product_id": self.product_canopy.id,
            "length_mm": 6000.0,
            "width_mm": 4000.0,
            "height_mm": 3000.0,
            "post_count": 4,
            "quantity": 1.0,
        })
        # No code was written for canopies: the family drives everything.
        self.assertIn(",length,", item.visible_dimension_codes)
        self.assertIn(",post_count,", item.visible_dimension_codes)
        self.assertNotIn(",step_count,", item.visible_dimension_codes)
        self.assertEqual(item.pricing_method, "per_m2")

        item.action_generate_components()
        self.assertEqual(len(item.component_line_ids), 3)
        columns = item.component_line_ids.filtered(lambda l: l.product_id == self.mat_pipe)
        self.assertAlmostEqual(columns.qty_per_unit, 4 * 3.0 * 1.05, places=6)
        service = item.component_line_ids.filtered(lambda l: l.product_id == self.service_galv)
        self.assertEqual(service.component_kind, "service")
        self.assertTrue(item.subcontract_cost > 0)

        # per m2 pricing: area is length x height because a height is entered
        self.assertAlmostEqual(item.area_m2, 18.0, places=4)
        self.assertAlmostEqual(item.recommended_price_unit, 450.0 * 18.0, places=2)

        item.action_sync_quotation_line()
        order.action_confirm()
        for line in item.component_line_ids.filtered(
            lambda l: l.product_id.type != "service"
        ):
            self._stock(line.product_id, line.total_qty * 2)
        item.action_create_manufacturing_order()
        production = item.production_id
        self.assertTrue(production)
        # Services are not put into the bill of materials.
        self.assertNotIn(self.service_galv, production.bom_id.bom_line_ids.product_id)
        # The quality template of the family produced a check automatically.
        self.assertTrue(production.dw_quality_check_ids)
        self.assertEqual(production.dw_quality_check_ids.template_id, quality_template)
        self.assertEqual(len(production.dw_quality_check_ids.line_ids), 2)
