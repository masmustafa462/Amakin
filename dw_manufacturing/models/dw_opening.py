# -*- coding: utf-8 -*-
"""Manufacturing Item (``dw.opening``).

The technical model name is deliberately unchanged since phase 1 so that no
existing record, foreign key or attachment is lost. Only the user facing label
became generic: a record now describes *any* fabricated metal product - door,
window, fence, handrail, staircase, gate, canopy, sheet metal work, and any
family an administrator creates later.
"""

import math

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

MM = 1000.0


class DwOpening(models.Model):
    _name = "dw.opening"
    _description = "Manufacturing Item"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "sale_order_id desc, sequence, id"

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------
    name = fields.Char(
        required=True,
        copy=False,
        default=lambda self: self.env._("New"),
        tracking=True,
    )
    sequence = fields.Integer(string="Sequence", default=10)
    active = fields.Boolean(string="Active", default=True)
    description = fields.Char(string="Product Description", translate=True)
    company_id = fields.Many2one(
        "res.company",
        compute="_compute_company_id",
        store=True,
        readonly=False,
        required=True,
        precompute=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_currency_id",
        store=True,
        readonly=True,
    )
    sale_order_id = fields.Many2one(
        "sale.order",
        ondelete="cascade",
        index=True,
        tracking=True,
    )
    sale_line_id = fields.Many2one(
        "sale.order.line",
        string="Quotation Line",
        copy=False,
        readonly=True,
        ondelete="set null",
    )
    project_id = fields.Many2one(
        "project.project",
        string="Project",
        compute="_compute_project_id",
        store=True,
        readonly=False,
        index=True,
        tracking=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        compute="_compute_partner_id",
        store=True,
        readonly=False,
        index=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("quoted", "Quoted"),
            ("confirmed", "Confirmed"),
            ("production", "In Production"),
            ("ready", "Ready"),
            ("delivered", "Delivered"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )

    # ------------------------------------------------------------------
    # Family and product
    # ------------------------------------------------------------------
    family_id = fields.Many2one(
        "dw.product.family",
        string="Product Family",
        index=True,
        tracking=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )
    product_kind = fields.Selection(related="family_id.product_kind", store=True)
    visible_dimension_codes = fields.Char(
        compute="_compute_visible_dimension_codes",
        help="Comma separated dimension codes shown for the selected family.",
    )
    required_dimension_codes = fields.Char(compute="_compute_visible_dimension_codes")
    family_rule_count = fields.Integer(
        string="Matching Component Rules", compute="_compute_setup_warning"
    )
    setup_warning = fields.Char(
        string="Configuration Warning", compute="_compute_setup_warning",
        help="Explains what is still missing before the estimate can be generated.",
    )
    opening_type = fields.Selection(
        [
            ("door", "Door"),
            ("window", "Window"),
            ("facade", "Facade"),
            ("other", "Other"),
        ],
        string="Legacy Item Type",
        default="other",
        tracking=True,
        help="Kept from phase 1 so historical records and rules keep matching.",
    )
    location = fields.Char(string="Location / Tag", translate=True)
    finished_product_id = fields.Many2one(
        "product.product",
        string="Finished Product",
        required=True,
        domain="[('type', '=', 'consu')]",
        tracking=True,
    )
    uom_id = fields.Many2one(
        "uom.uom",
        string="Unit of Measure",
        compute="_compute_uom_id",
        store=True,
        readonly=False,
    )

    # ------------------------------------------------------------------
    # Dimensions - captured in millimetres, exposed in metres
    # ------------------------------------------------------------------
    quantity = fields.Float(string="Item Count", required=True, default=1.0, tracking=True)
    length_mm = fields.Float(string="Length (mm)", tracking=True)
    width_mm = fields.Float(string="Width (mm)", tracking=True)
    height_mm = fields.Float(string="Height (mm)", tracking=True)
    thickness_mm = fields.Float(string="Thickness (mm)")
    diameter_mm = fields.Float(string="Diameter (mm)")

    length_m = fields.Float(string="Length (m)", compute="_compute_measurements", store=True, digits=(16, 4))
    width_m = fields.Float(string="Width (m)", compute="_compute_measurements", store=True, digits=(16, 4))
    height_m = fields.Float(string="Height (m)", compute="_compute_measurements", store=True, digits=(16, 4))
    thickness_m = fields.Float(string="Thickness (m)", compute="_compute_measurements", store=True, digits=(16, 5))
    diameter_m = fields.Float(string="Diameter (m)", compute="_compute_measurements", store=True, digits=(16, 5))
    perimeter_m = fields.Float(string="Perimeter (m)", compute="_compute_measurements", store=True, digits=(16, 4))
    area_m2 = fields.Float(string="Area (m2)", compute="_compute_measurements", store=True, digits=(16, 4))
    volume_m3 = fields.Float(string="Volume (m3)", compute="_compute_measurements", store=True, digits=(16, 5))
    total_length_m = fields.Float(string="Total Length (m)", compute="_compute_measurements", store=True, digits=(16, 4))
    dw_one = fields.Float(compute="_compute_dw_one", string="Unit Constant")

    # Counts
    leaf_count = fields.Integer(string="Leaf Count", default=1)
    post_count = fields.Integer(
        string="Post Count", compute="_compute_layout", store=True, readonly=False
    )
    section_count = fields.Integer(
        string="Section Count", compute="_compute_layout", store=True, readonly=False
    )
    post_spacing_mm = fields.Float(string="Post Spacing (mm)", default=0.0)
    post_spacing_m = fields.Float(string="Post Spacing (m)", compute="_compute_measurements", store=True, digits=(16, 4))

    # Staircase geometry
    step_count = fields.Integer(string="Step Count")
    step_height_mm = fields.Float(string="Step Height (mm)")
    step_width_mm = fields.Float(string="Step Width / Going (mm)")
    total_rise_mm = fields.Float(string="Total Rise (mm)")
    step_height_m = fields.Float(string="Step Height (m)", compute="_compute_measurements", store=True, digits=(16, 4))
    step_width_m = fields.Float(string="Step Width (m)", compute="_compute_measurements", store=True, digits=(16, 4))
    total_rise_m = fields.Float(string="Total Rise (m)", compute="_compute_measurements", store=True, digits=(16, 4))
    total_run_m = fields.Float(string="Total Run (m)", compute="_compute_stairs", store=True, digits=(16, 4))
    stair_slope_length_m = fields.Float(string="Slope Length (m)", compute="_compute_stairs", store=True, digits=(16, 4))
    stair_angle_deg = fields.Float(
        string="Stair Angle (deg)", compute="_compute_stairs", store=True, readonly=False
    )

    # Process quantities
    weld_length_m = fields.Float(
        string="Welding Length (m)", compute="_compute_process_quantities",
        store=True, readonly=False, digits=(16, 4),
    )
    paint_area_m2 = fields.Float(
        string="Painting Area (m2)", compute="_compute_process_quantities",
        store=True, readonly=False, digits=(16, 4),
    )
    galv_area_m2 = fields.Float(
        string="Galvanizing Area (m2)", compute="_compute_process_quantities",
        store=True, readonly=False, digits=(16, 4),
    )
    surface_factor = fields.Float(
        string="Surface Factor", default=2.0,
        help="Multiplier applied to the projected area to estimate the coated surface.",
    )

    # ------------------------------------------------------------------
    # Materials and finishing
    # ------------------------------------------------------------------
    metal_type_id = fields.Many2one("dw.metal.type", string="Metal Type")
    metal_grade_id = fields.Many2one(
        "dw.metal.grade",
        string="Grade / Specification",
        domain="[('metal_type_id', '=?', metal_type_id)]",
    )
    finish_type_id = fields.Many2one("dw.finish.type", string="Finish Type")
    color = fields.Char(translate=True)
    opening_system = fields.Selection(
        [
            ("fixed", "Fixed"),
            ("hinged", "Hinged"),
            ("sliding", "Sliding"),
            ("folding", "Folding"),
            ("tilt_turn", "Tilt and Turn"),
            ("rolling", "Rolling"),
            ("other", "Other"),
        ],
        default="fixed",
    )
    glass_specification = fields.Char(translate=True)
    accessory_specification = fields.Char(translate=True)
    manufacturing_instructions = fields.Html(translate=True)
    note = fields.Text(translate=True)

    # ------------------------------------------------------------------
    # Drawings
    # ------------------------------------------------------------------
    drawing_id = fields.Many2one("dw.drawing", string="Drawing", index="btree_not_null")
    drawing_revision_id = fields.Many2one(
        "dw.drawing.revision",
        string="Drawing Revision",
        domain="[('drawing_id', '=', drawing_id)]",
    )
    drawing_number = fields.Char(related="drawing_id.name", store=True, string="Drawing No.")
    drawing_revision_number = fields.Char(
        related="drawing_revision_id.revision", store=True, string="Revision No."
    )

    # ------------------------------------------------------------------
    # Weights
    # ------------------------------------------------------------------
    theoretical_weight_kg = fields.Float(
        compute="_compute_weights", store=True, digits=(16, 3), string="Theoretical Weight (kg)"
    )
    planned_weight_kg = fields.Float(
        compute="_compute_weights", store=True, digits=(16, 3), string="Planned Weight (kg)"
    )
    manual_weight_kg = fields.Float(string="Manual Weight (kg)", digits=(16, 3))
    issued_weight_kg = fields.Float(
        compute="_compute_actual_weights", store=True, digits=(16, 3),
        string="Issued Weight (kg)",
    )
    finished_weight_kg = fields.Float(string="Finished Product Weight (kg)", digits=(16, 3))
    scrap_weight_kg = fields.Float(
        compute="_compute_actual_weights", store=True, digits=(16, 3), string="Scrap Weight (kg)"
    )
    weight_variance_kg = fields.Float(
        string="Weight Variance (kg)",
        compute="_compute_actual_weights", store=True, digits=(16, 3)
    )
    weight_variance_percent = fields.Float(
        string="Weight Variance %",
        compute="_compute_actual_weights", store=True, digits=(16, 2)
    )

    # ------------------------------------------------------------------
    # Components, operations and estimate
    # ------------------------------------------------------------------
    component_line_ids = fields.One2many(
        "dw.opening.component", "opening_id", string="Estimated Components", copy=True
    )
    operation_line_ids = fields.One2many(
        "dw.opening.operation", "opening_id", string="Planned Operations", copy=True
    )
    extra_cost_ids = fields.One2many(
        "dw.opening.extra.cost", "opening_id", string="Manual Cost Items", copy=True
    )

    material_cost = fields.Monetary(string="Material Cost", compute="_compute_costs", store=True, tracking=True)
    labor_cost = fields.Monetary(string="Labour Cost", compute="_compute_costs", store=True)
    machine_cost = fields.Monetary(string="Machine Cost", compute="_compute_costs", store=True)
    labor_cost_manual = fields.Monetary(string="Manual Labour Cost")
    machine_cost_manual = fields.Monetary(string="Manual Machine Cost")
    subcontract_cost = fields.Monetary(string="Outsourcing Cost", compute="_compute_costs", store=True)
    subcontract_cost_manual = fields.Monetary(string="Manual Outsourcing Cost")
    contractor_cost = fields.Monetary(string="Contractor Cost")
    transport_cost = fields.Monetary(string="Transport Cost")
    installation_cost = fields.Monetary(string="Installation Cost")
    direct_expense_cost = fields.Monetary(string="Direct Expenses")
    manual_cost = fields.Monetary(compute="_compute_costs", store=True, string="Manual Items")
    overhead_cost = fields.Monetary(string="Overhead Cost", compute="_compute_costs", store=True, readonly=False)
    overhead_rule_id = fields.Many2one("dw.overhead.rule", string="Overhead Rule")
    estimated_cost = fields.Monetary(string="Estimated Cost", compute="_compute_costs", store=True)
    estimated_unit_cost = fields.Monetary(string="Estimated Unit Cost", compute="_compute_costs", store=True)

    markup_percent = fields.Float(string="Markup %", default=25.0)
    pricing_method = fields.Selection(
        [
            ("cost_plus", "Cost plus Markup"),
            ("per_m2", "Price per m2"),
            ("per_m", "Price per Linear Meter"),
            ("per_kg", "Price per Kilogram"),
            ("per_unit", "Price per Unit"),
        ],
        compute="_compute_pricing_defaults",
        store=True,
        readonly=False,
        required=True,
        precompute=True,
    )
    price_rate = fields.Monetary(
        string="Rate", compute="_compute_pricing_defaults",
        store=True, readonly=False, precompute=True,
    )
    recommended_price_unit = fields.Monetary(string="Recommended Unit Price", compute="_compute_costs", store=True)
    selling_price_unit = fields.Monetary(string="Unit Price", tracking=True)
    expected_revenue = fields.Monetary(string="Expected Revenue", compute="_compute_costs", store=True)
    expected_profit = fields.Monetary(string="Expected Profit", compute="_compute_costs", store=True)
    expected_margin_percent = fields.Float(string="Expected Margin %", compute="_compute_costs", store=True)

    # ------------------------------------------------------------------
    # Manufacturing, actual cost and revenue
    # ------------------------------------------------------------------
    bom_id = fields.Many2one("mrp.bom", string="Bill of Materials", copy=False)
    production_ids = fields.One2many(
        "mrp.production", "dw_opening_id", string="Manufacturing Orders"
    )
    production_id = fields.Many2one(
        "mrp.production", compute="_compute_production_data", store=True, string="Main MO"
    )
    production_count = fields.Integer(
        string="Manufacturing Order Count", compute="_compute_production_data", store=True
    )

    cost_line_ids = fields.One2many(
        "dw.production.cost.line", "opening_id", string="Actual Cost Lines"
    )
    actual_material_cost = fields.Monetary(string="Actual Material Cost", compute="_compute_actual_costs", store=True)
    actual_labor_cost = fields.Monetary(string="Actual Labour Cost", compute="_compute_actual_costs", store=True)
    actual_machine_cost = fields.Monetary(string="Actual Machine Cost", compute="_compute_actual_costs", store=True)
    actual_subcontract_cost = fields.Monetary(string="Actual Outsourcing Cost", compute="_compute_actual_costs", store=True)
    actual_scrap_cost = fields.Monetary(string="Actual Scrap Cost", compute="_compute_actual_costs", store=True)
    actual_overhead_cost = fields.Monetary(string="Actual Overhead Cost", compute="_compute_actual_costs", store=True)
    actual_other_cost = fields.Monetary(string="Actual Other Cost", compute="_compute_actual_costs", store=True)
    actual_cost = fields.Monetary(string="Actual Cost", compute="_compute_actual_costs", store=True)
    cost_variance = fields.Monetary(string="Cost Variance", compute="_compute_actual_costs", store=True)
    cost_variance_percent = fields.Float(string="Cost Variance %", compute="_compute_actual_costs", store=True)

    invoiced_revenue = fields.Monetary(string="Invoiced Revenue", compute="_compute_revenue", store=True)
    internal_transfer_value = fields.Monetary(
        compute="_compute_revenue", store=True,
        help="Management transfer value used when no external invoice exists.",
    )
    actual_revenue = fields.Monetary(string="Actual Revenue", compute="_compute_revenue", store=True)
    actual_profit = fields.Monetary(string="Actual Profit", compute="_compute_revenue", store=True)
    actual_margin_percent = fields.Float(string="Actual Margin %", compute="_compute_revenue", store=True)

    # ------------------------------------------------------------------
    # Quality
    # ------------------------------------------------------------------
    quality_check_ids = fields.One2many(
        "dw.quality.check", "opening_id", string="Quality Checks"
    )
    quality_check_count = fields.Integer(
        string="Quality Check Count", compute="_compute_quality_count"
    )
    quality_state = fields.Selection(
        string="Quality Status",
        selection=[
            ("none", "No Check"),
            ("pending", "Pending"),
            ("pass", "Passed"),
            ("rework", "Needs Rework"),
            ("fail", "Rejected"),
        ],
        compute="_compute_quality",
        store=True,
        default="none",
    )
    scrap_ids = fields.One2many("stock.scrap", "dw_opening_id", string="Scraps")
    offcut_ids = fields.One2many("dw.material.offcut", "opening_id", string="Offcuts")

    # ------------------------------------------------------------------
    # Compute methods
    # ------------------------------------------------------------------
    @api.depends("sale_order_id.company_id")
    def _compute_company_id(self):
        for item in self:
            if item.sale_order_id:
                item.company_id = item.sale_order_id.company_id
            elif not item.company_id:
                item.company_id = self.env.company

    @api.depends("company_id", "sale_order_id.currency_id")
    def _compute_currency_id(self):
        for item in self:
            item.currency_id = (
                item.sale_order_id.currency_id or item.company_id.currency_id
            )

    @api.depends("sale_order_id.dw_project_id")
    def _compute_project_id(self):
        for item in self:
            if item.sale_order_id.dw_project_id:
                item.project_id = item.sale_order_id.dw_project_id

    @api.depends("sale_order_id.partner_id")
    def _compute_partner_id(self):
        for item in self:
            if item.sale_order_id.partner_id:
                item.partner_id = item.sale_order_id.partner_id

    @api.depends("family_id", "family_id.uom_id", "finished_product_id")
    def _compute_uom_id(self):
        for item in self:
            item.uom_id = (
                item.family_id.uom_id
                or item.finished_product_id.uom_id
                or item.uom_id
            )

    @api.depends("family_id.dimension_codes", "family_id.required_dimension_codes",
                 "family_id.dimension_ids", "family_id.product_kind")
    def _compute_visible_dimension_codes(self):
        for item in self:
            if item.family_id:
                # Read the family live rather than trusting the stored value: a
                # family upgraded from an older version may still carry an empty
                # cache, and an empty set of codes would hide every input.
                codes = item.family_id._effective_dimension_codes()
                item.visible_dimension_codes = ",%s," % ",".join(codes)
                item.required_dimension_codes = item.family_id.required_dimension_codes or ",,"
            else:
                # No family: keep the phase-1 behaviour (width, height, leaves).
                item.visible_dimension_codes = ",width,height,leaf_count,thickness,paint_area,"
                item.required_dimension_codes = ",width,height,"

    @api.depends("family_id", "finished_product_id", "company_id",
                 "family_id.dimension_ids", "component_line_ids")
    def _compute_setup_warning(self):
        Rule = self.env["dw.component.rule"]
        for item in self:
            rules = Rule._rules_for_item(item) if item.finished_product_id else Rule.browse()
            item.family_rule_count = len(rules)
            messages = []
            if item.family_id and not item.family_id.dimension_ids:
                messages.append(self.env._(
                    "The product family \"%s\" has no dimension selected, so the standard set "
                    "for its product kind is being shown. Open Configuration > Product Families "
                    "to choose the dimensions this product really needs.",
                    item.family_id.display_name,
                ))
            if not rules and not item.component_line_ids:
                if item.family_id:
                    messages.append(self.env._(
                        "No component rule is defined for the family \"%s\", so the estimate "
                        "cannot be generated. Add rules on the family, or add the component "
                        "lines by hand in the Components tab.",
                        item.family_id.display_name,
                    ))
                elif item.finished_product_id:
                    messages.append(self.env._(
                        "No component rule matches the finished product \"%s\". Select a "
                        "product family, or add the component lines by hand.",
                        item.finished_product_id.display_name,
                    ))
            item.setup_warning = " ".join(messages)

    def _compute_dw_one(self):
        for item in self:
            item.dw_one = 1.0

    @api.depends(
        "length_mm", "width_mm", "height_mm", "thickness_mm", "diameter_mm",
        "step_height_mm", "step_width_mm", "total_rise_mm", "post_spacing_mm",
    )
    def _compute_measurements(self):
        for item in self:
            item.length_m = item.length_mm / MM
            item.width_m = item.width_mm / MM
            item.height_m = item.height_mm / MM
            item.thickness_m = item.thickness_mm / MM
            item.diameter_m = item.diameter_mm / MM
            item.step_height_m = item.step_height_mm / MM
            item.step_width_m = item.step_width_mm / MM
            item.total_rise_m = item.total_rise_mm / MM
            item.post_spacing_m = item.post_spacing_mm / MM

            plan = item.length_m or item.width_m
            rise = item.height_m
            if plan and rise:
                item.perimeter_m = 2.0 * (plan + rise)
                item.area_m2 = plan * rise
            elif item.length_m and item.width_m:
                item.perimeter_m = 2.0 * (item.length_m + item.width_m)
                item.area_m2 = item.length_m * item.width_m
            elif item.diameter_m:
                item.perimeter_m = math.pi * item.diameter_m
                item.area_m2 = math.pi * item.diameter_m ** 2 / 4.0
            else:
                item.perimeter_m = 0.0
                item.area_m2 = 0.0

            if item.length_m and item.width_m and item.height_m:
                item.volume_m3 = item.length_m * item.width_m * item.height_m
            else:
                item.volume_m3 = item.area_m2 * item.thickness_m
            item.total_length_m = item.length_m or item.perimeter_m

    @api.depends("step_count", "step_width_m", "total_rise_m", "step_height_m")
    def _compute_stairs(self):
        for item in self:
            steps = item.step_count or 0
            rise = item.total_rise_m or (steps * item.step_height_m)
            run = steps * item.step_width_m
            item.total_run_m = run
            item.stair_slope_length_m = math.sqrt(rise ** 2 + run ** 2) if (rise or run) else 0.0
            item.stair_angle_deg = math.degrees(math.atan2(rise, run)) if run else 0.0

    @api.depends("length_m", "post_spacing_m")
    def _compute_layout(self):
        for item in self:
            if item.post_spacing_m and item.length_m:
                spans = max(int(math.ceil(item.length_m / item.post_spacing_m - 1e-9)), 1)
                item.post_count = spans + 1
                item.section_count = spans
            else:
                item.post_count = item.post_count or 0
                item.section_count = item.section_count or 0

    @api.depends("area_m2", "surface_factor", "perimeter_m", "leaf_count",
                 "finish_type_id.kind", "total_length_m", "post_count", "height_m")
    def _compute_process_quantities(self):
        for item in self:
            surface = item.area_m2 * (item.surface_factor or 2.0)
            item.paint_area_m2 = surface
            item.galv_area_m2 = surface if item.finish_type_id.kind == "galvanizing" else 0.0
            # Rough default: frame perimeter plus one weld per leaf / post joint.
            joints = (item.leaf_count or 0) + (item.post_count or 0)
            item.weld_length_m = item.perimeter_m + (joints * (item.height_m or 0.0))

    @api.depends(
        "component_line_ids.theoretical_weight_kg",
        "family_id.weight_method",
        "family_id.weight_factor",
        "manual_weight_kg",
        "area_m2",
        "total_length_m",
        "quantity",
    )
    def _compute_weights(self):
        for item in self:
            method = item.family_id.weight_method or "components"
            factor = item.family_id.weight_factor or 0.0
            if method == "manual":
                unit_weight = item.manual_weight_kg
            elif method == "per_area":
                unit_weight = factor * item.area_m2
            elif method == "per_length":
                unit_weight = factor * item.total_length_m
            elif method == "per_unit":
                unit_weight = factor
            else:
                unit_weight = sum(item.component_line_ids.mapped("theoretical_weight_kg"))
            item.theoretical_weight_kg = unit_weight
            item.planned_weight_kg = unit_weight * (item.quantity or 0.0)

    @api.depends("cost_line_ids.weight_kg", "cost_line_ids.cost_type",
                 "theoretical_weight_kg", "quantity", "finished_weight_kg")
    def _compute_actual_weights(self):
        for item in self:
            issued = sum(
                line.weight_kg
                for line in item.cost_line_ids
                if line.cost_type == "material"
            )
            scrap = sum(
                line.weight_kg
                for line in item.cost_line_ids
                if line.cost_type in ("scrap", "waste")
            )
            item.issued_weight_kg = issued
            item.scrap_weight_kg = scrap
            planned = item.theoretical_weight_kg * (item.quantity or 0.0)
            item.weight_variance_kg = issued - planned
            item.weight_variance_percent = (
                item.weight_variance_kg / planned * 100.0 if planned else 0.0
            )

    @api.depends(
        "component_line_ids.estimated_total_cost",
        "component_line_ids.component_kind",
        "operation_line_ids.labor_cost",
        "operation_line_ids.machine_cost",
        "extra_cost_ids.amount",
        "extra_cost_ids.approved",
        "quantity",
        "labor_cost_manual",
        "machine_cost_manual",
        "subcontract_cost_manual",
        "contractor_cost",
        "transport_cost",
        "installation_cost",
        "direct_expense_cost",
        "markup_percent",
        "selling_price_unit",
        "pricing_method",
        "price_rate",
        "area_m2",
        "total_length_m",
        "theoretical_weight_kg",
        "overhead_rule_id",
    )
    def _compute_costs(self):
        for item in self:
            materials = item.component_line_ids.filtered(
                lambda line: line.component_kind in ("material", "subassembly")
            )
            services = item.component_line_ids.filtered(
                lambda line: line.component_kind == "service"
            )
            item.material_cost = sum(materials.mapped("estimated_total_cost"))
            item.labor_cost = (
                sum(item.operation_line_ids.mapped("labor_cost")) + item.labor_cost_manual
            )
            item.machine_cost = (
                sum(item.operation_line_ids.mapped("machine_cost")) + item.machine_cost_manual
            )
            item.subcontract_cost = (
                sum(services.mapped("estimated_total_cost")) + item.subcontract_cost_manual
            )
            item.manual_cost = sum(
                line.amount for line in item.extra_cost_ids if line.approved
            )
            direct = (
                item.material_cost
                + item.labor_cost
                + item.machine_cost
                + item.subcontract_cost
                + item.contractor_cost
                + item.transport_cost
                + item.installation_cost
                + item.direct_expense_cost
                + item.manual_cost
            )
            if item.overhead_rule_id:
                item.overhead_cost = item.overhead_rule_id._compute_amount(
                    item, material_cost=item.material_cost,
                    labor_cost=item.labor_cost + item.machine_cost,
                    direct_cost=direct,
                )
            item.estimated_cost = direct + item.overhead_cost
            item.estimated_unit_cost = (
                item.estimated_cost / item.quantity if item.quantity else 0.0
            )

            if item.pricing_method == "per_m2":
                item.recommended_price_unit = item.price_rate * item.area_m2
            elif item.pricing_method == "per_m":
                item.recommended_price_unit = item.price_rate * item.total_length_m
            elif item.pricing_method == "per_kg":
                item.recommended_price_unit = item.price_rate * item.theoretical_weight_kg
            elif item.pricing_method == "per_unit":
                item.recommended_price_unit = item.price_rate
            else:
                item.recommended_price_unit = item.estimated_unit_cost * (
                    1.0 + item.markup_percent / 100.0
                )

            item.expected_revenue = item.selling_price_unit * item.quantity
            item.expected_profit = item.expected_revenue - item.estimated_cost
            item.expected_margin_percent = (
                item.expected_profit / item.expected_revenue * 100.0
                if item.expected_revenue
                else 0.0
            )

    @api.depends("family_id")
    def _compute_pricing_defaults(self):
        for item in self:
            if item.family_id:
                item.pricing_method = item.family_id.pricing_method
                item.price_rate = item.family_id.default_price_unit
            else:
                item.pricing_method = item.pricing_method or "cost_plus"
                item.price_rate = item.price_rate or 0.0

    @api.depends("cost_line_ids.amount", "cost_line_ids.cost_type",
                 "cost_line_ids.state", "estimated_cost")
    def _compute_actual_costs(self):
        buckets = {
            "material": "actual_material_cost",
            "labor": "actual_labor_cost",
            "machine": "actual_machine_cost",
            "outsourcing": "actual_subcontract_cost",
            "scrap": "actual_scrap_cost",
            "overhead": "actual_overhead_cost",
        }
        for item in self:
            totals = dict.fromkeys(buckets.values(), 0.0)
            other = 0.0
            for line in item.cost_line_ids:
                if line.state == "cancel":
                    continue
                field_name = buckets.get(line.cost_type)
                if field_name:
                    totals[field_name] += line.amount
                else:
                    other += line.amount
            for field_name, value in totals.items():
                item[field_name] = value
            item.actual_other_cost = other
            item.actual_cost = sum(totals.values()) + other
            item.cost_variance = item.actual_cost - item.estimated_cost
            item.cost_variance_percent = (
                item.cost_variance / item.estimated_cost * 100.0
                if item.estimated_cost
                else 0.0
            )

    @api.depends(
        "sale_line_id.invoice_lines.move_id.state",
        "sale_line_id.invoice_lines.price_subtotal",
        "sale_line_id.invoice_lines.move_id.move_type",
        "sale_order_id.dw_relationship",
        "expected_revenue",
        "actual_cost",
    )
    def _compute_revenue(self):
        for item in self:
            invoiced = 0.0
            for invoice_line in item.sale_line_id.invoice_lines:
                move = invoice_line.move_id
                if move.state != "posted":
                    continue
                if move.move_type == "out_invoice":
                    invoiced += invoice_line.price_subtotal
                elif move.move_type == "out_refund":
                    invoiced -= invoice_line.price_subtotal
            item.invoiced_revenue = invoiced
            relationship = item.sale_order_id.dw_relationship or "external"
            if relationship == "main_same_entity":
                # No external invoice: report a management transfer value only.
                item.internal_transfer_value = item.expected_revenue
                item.actual_revenue = 0.0
            else:
                item.internal_transfer_value = 0.0
                item.actual_revenue = invoiced
            base = item.actual_revenue or item.internal_transfer_value
            item.actual_profit = base - item.actual_cost
            item.actual_margin_percent = (
                item.actual_profit / base * 100.0 if base else 0.0
            )

    @api.depends("quality_check_ids")
    def _compute_quality_count(self):
        for item in self:
            item.quality_check_count = len(item.quality_check_ids)

    @api.depends("production_ids", "production_ids.state")
    def _compute_production_data(self):
        for item in self:
            productions = item.production_ids
            item.production_count = len(productions)
            active = productions.filtered(lambda mo: mo.state != "cancel")
            item.production_id = active[:1] or productions[:1]

    @api.depends("quality_check_ids.result", "quality_check_ids.state")
    def _compute_quality(self):
        for item in self:
            checks = item.quality_check_ids
            if not checks:
                item.quality_state = "none"
            elif any(check.result == "fail" for check in checks):
                item.quality_state = "fail"
            elif any(check.result == "rework" for check in checks):
                item.quality_state = "rework"
            elif all(check.result == "pass" for check in checks):
                item.quality_state = "pass"
            else:
                item.quality_state = "pending"

    # ------------------------------------------------------------------
    # Constraints and onchange
    # ------------------------------------------------------------------
    @api.constrains("quantity", "leaf_count", "length_mm", "width_mm", "height_mm")
    def _check_positive_dimensions(self):
        for item in self:
            if item.quantity <= 0:
                raise ValidationError(self.env._("The item count must be positive."))
            if item.leaf_count < 0:
                raise ValidationError(self.env._("The leaf count cannot be negative."))
            for value in (item.length_mm, item.width_mm, item.height_mm):
                if value < 0:
                    raise ValidationError(self.env._("Dimensions cannot be negative."))

    @api.constrains("family_id", "length_mm", "width_mm", "height_mm", "thickness_mm",
                    "diameter_mm", "step_count", "total_rise_mm")
    def _check_required_dimensions(self):
        mapping = {
            "length": "length_mm",
            "width": "width_mm",
            "height": "height_mm",
            "thickness": "thickness_mm",
            "diameter": "diameter_mm",
            "step_count": "step_count",
            "total_rise": "total_rise_mm",
            "step_height": "step_height_mm",
            "step_width": "step_width_mm",
            "post_count": "post_count",
            "leaf_count": "leaf_count",
        }
        for item in self:
            if not item.family_id:
                continue
            for dimension in item.family_id.required_dimension_ids:
                field_name = mapping.get(dimension.code)
                if field_name and not item[field_name]:
                    raise ValidationError(
                        self.env._(
                            "%(dimension)s is mandatory for the family %(family)s.",
                            dimension=dimension.name,
                            family=item.family_id.display_name,
                        )
                    )

    @api.onchange("family_id")
    def _onchange_family_id(self):
        for item in self:
            family = item.family_id
            if not family:
                continue
            if family.default_product_id and not item.finished_product_id:
                item.finished_product_id = family.default_product_id
            if family.metal_type_id and not item.metal_type_id:
                item.metal_type_id = family.metal_type_id
            if family.finish_type_id and not item.finish_type_id:
                item.finish_type_id = family.finish_type_id
            item.markup_percent = family.default_markup_percent

    @api.onchange("metal_type_id")
    def _onchange_metal_type_id(self):
        if self.metal_grade_id.metal_type_id != self.metal_type_id:
            self.metal_grade_id = False

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", self.env._("New")) == self.env._("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "dw.opening"
                ) or self.env._("New")
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Business actions
    # ------------------------------------------------------------------
    def _matching_rules(self):
        """Kept from phase 1; now delegates to the family aware matcher."""
        self.ensure_one()
        return self.env["dw.component.rule"]._rules_for_item(self)

    def action_generate_components(self):
        for item in self:
            rules = item._matching_rules()
            if not rules:
                if item.component_line_ids:
                    # Nothing to generate, but the user entered the components by
                    # hand: recompute what depends on them and carry on.
                    item._generate_operations()
                    if not item.selling_price_unit:
                        item.selling_price_unit = item.recommended_price_unit
                    continue
                if item.family_id:
                    raise UserError(self.env._(
                        "No component rule is defined for the product family \"%(family)s\".\n\n"
                        "Either add rules under Configuration > Component Rules for this family, "
                        "or enter the components by hand in the Components tab and press this "
                        "button again.",
                        family=item.family_id.display_name,
                    ))
                raise UserError(self.env._(
                    "No component rule matches the finished product \"%(product)s\".\n\n"
                    "Select a product family that has component rules, or enter the components "
                    "by hand in the Components tab.",
                    product=item.finished_product_id.display_name,
                ))
            item.component_line_ids.unlink()
            item.invalidate_recordset()
            lines = [
                (0, 0, {
                    "rule_id": rule.id,
                    "product_id": rule.component_product_id.id,
                    "component_kind": rule.component_kind,
                    "uom_id": rule._target_uom().id,
                    "operation_type_id": rule.operation_type_id.id,
                    "qty_per_unit": rule.calculate_quantity(item),
                })
                for rule in rules
            ]
            item.write({"component_line_ids": lines})
            # Second pass: rules driven by the item weight (galvanizing, painting,
            # transport...) can only be evaluated once the material lines exist.
            item.invalidate_recordset()
            for line in item.component_line_ids.filtered("rule_id"):
                quantity = line.rule_id.calculate_quantity(item)
                if line.qty_per_unit != quantity:
                    line.qty_per_unit = quantity
            item.component_line_ids.filtered(lambda l: not l.qty_per_unit).unlink()
            item.invalidate_recordset()
            item._generate_operations()
            if not item.selling_price_unit:
                item.selling_price_unit = item.recommended_price_unit
            item.message_post(
                body=self.env._("Component estimate generated: %s lines.", len(lines))
            )
        return True

    def _generate_operations(self):
        for item in self:
            family = item.family_id
            if not family or not family.operation_ids:
                continue
            item.operation_line_ids.unlink()
            lines = []
            for sequence, operation in enumerate(family.operation_ids, start=1):
                workcenter = operation._effective_workcenter()
                lines.append((0, 0, {
                    "sequence": sequence * 10,
                    "operation_type_id": operation.operation_type_id.id,
                    "workcenter_id": workcenter.id if workcenter else False,
                    "planned_minutes": operation._duration_for(item, item.quantity or 1.0),
                    "is_outsourced": operation.is_outsourced,
                }))
            item.write({"operation_line_ids": lines})

    def action_recompute_estimate(self):
        for item in self:
            for line in item.component_line_ids.filtered("rule_id"):
                line.qty_per_unit = line.rule_id.calculate_quantity(item)
            item._generate_operations()
        return True

    def _quotation_line_description(self):
        self.ensure_one()
        parts = [self.description or self.finished_product_id.display_name]
        detail = []
        if self.location:
            detail.append(self.location)
        if self.length_mm:
            detail.append(self.env._("L %s mm", self.length_mm))
        if self.width_mm:
            detail.append(self.env._("W %s mm", self.width_mm))
        if self.height_mm:
            detail.append(self.env._("H %s mm", self.height_mm))
        if self.thickness_mm:
            detail.append(self.env._("T %s mm", self.thickness_mm))
        if self.leaf_count:
            detail.append(self.env._("Leaves %s", self.leaf_count))
        if self.step_count:
            detail.append(self.env._("Steps %s", self.step_count))
        if self.finish_type_id:
            detail.append(self.finish_type_id.display_name)
        if self.color:
            detail.append(self.color)
        if detail:
            parts.append(" | ".join(detail))
        return "\n".join(parts)

    def action_sync_quotation_line(self):
        for item in self:
            if not item.sale_order_id:
                raise UserError(self.env._("Link the item to a quotation first."))
            order = item.sale_order_id
            if order.state == "cancel":
                raise UserError(
                    self.env._(
                        "Sales order %s is cancelled. Reset it to a quotation, or link the "
                        "item to another order.",
                        order.name,
                    )
                )
            if order.locked:
                raise UserError(
                    self.env._(
                        "Sales order %s is locked, so its lines cannot be changed. Unlock it "
                        "from the sales order and press this button again.",
                        order.name,
                    )
                )
            if not item.component_line_ids:
                raise UserError(self.env._("Generate the component estimate first."))
            values = {
                "order_id": item.sale_order_id.id,
                "product_id": item.finished_product_id.id,
                "product_uom_qty": item.quantity,
                "product_uom_id": (item.uom_id or item.finished_product_id.uom_id).id,
                "price_unit": item.selling_price_unit,
                "name": item._quotation_line_description(),
                "dw_opening_id": item.id,
            }
            if item.sale_line_id:
                item.sale_line_id.write(values)
            else:
                item.sale_line_id = self.env["sale.order.line"].create(values)
            # Mark the quotation so confirming it moves the items forward and the
            # fabrication fields (relationship, project) become visible.
            if not order.dw_is_manufacturing_quote:
                order.dw_is_manufacturing_quote = True
            # An order that is already sold carries the item straight to Confirmed:
            # waiting for a confirmation that has already happened would strand it.
            item.state = "confirmed" if order.state == "sale" else "quoted"
        return True

    # ------------------------------------------------------------------
    # Bill of materials and manufacturing order
    # ------------------------------------------------------------------
    def _prepare_bom_operation_values(self, bom):
        self.ensure_one()
        operations = []
        for line in self.operation_line_ids:
            if not line.workcenter_id:
                continue
            operations.append((0, 0, {
                "name": line.display_operation_name,
                "sequence": line.sequence,
                "workcenter_id": line.workcenter_id.id,
                "time_mode": "manual",
                "time_cycle_manual": line.planned_minutes,
            }))
        return operations

    def _prepare_bom_line_values(self):
        self.ensure_one()
        lines = []
        for line in self.component_line_ids:
            if line.component_kind == "customer_supplied" and not line.include_in_bom:
                continue
            if line.product_id.type == "service":
                continue
            lines.append((0, 0, {
                "product_id": line.product_id.id,
                "product_qty": line.qty_per_unit,
                "product_uom_id": line.uom_id.id,
            }))
        return lines

    def action_create_bom(self):
        """Create a dedicated BoM for this item without touching generic BoMs."""
        for item in self:
            if not item.component_line_ids:
                raise UserError(self.env._("Generate the component estimate first."))
            item._check_drawing_released()
            bom_lines = item._prepare_bom_line_values()
            if not bom_lines:
                raise UserError(
                    self.env._("The estimate has no storable component to put in a bill of materials.")
                )
            values = {
                "code": item.name,
                "product_tmpl_id": item.finished_product_id.product_tmpl_id.id,
                "product_id": item.finished_product_id.id,
                "product_qty": 1.0,
                "product_uom_id": (item.uom_id or item.finished_product_id.uom_id).id,
                "type": "normal",
                "company_id": item.company_id.id,
                "bom_line_ids": bom_lines,
                "dw_opening_id": item.id,
                "dw_project_id": item.project_id.id,
                "dw_partner_id": item.partner_id.id,
                "dw_drawing_revision_id": item.drawing_revision_id.id,
                "dw_is_item_specific": True,
            }
            bom = self.env["mrp.bom"].create(values)
            operations = item._prepare_bom_operation_values(bom)
            if operations:
                bom.write({"operation_ids": operations})
            item.bom_id = bom
        return True

    def action_view_bom(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "mrp.bom",
            "res_id": self.bom_id.id,
            "view_mode": "form",
        }

    def _check_drawing_released(self):
        self.ensure_one()
        if self.drawing_revision_id and self.drawing_revision_id.state != "released":
            raise UserError(
                self.env._(
                    "Drawing revision %s is not released. A non approved revision cannot be used in production.",
                    self.drawing_revision_id.display_name,
                )
            )

    def action_create_manufacturing_order(self):
        for item in self:
            if item.sale_order_id and item.sale_order_id.state not in ("sale", "done"):
                raise UserError(self.env._("Confirm the sales order first."))
            if not item.component_line_ids:
                raise UserError(self.env._("Generate the component estimate first."))
            if item.production_ids.filtered(lambda mo: mo.state != "cancel"):
                raise UserError(
                    self.env._(
                        "A non-cancelled manufacturing order already exists for this item."
                    )
                )
            item._check_drawing_released()
            if not item.bom_id:
                item.action_create_bom()
            production = self.env["mrp.production"].create({
                "origin": item.sale_order_id.name or item.name,
                "product_id": item.finished_product_id.id,
                "product_qty": item.quantity,
                "product_uom_id": (item.uom_id or item.finished_product_id.uom_id).id,
                "bom_id": item.bom_id.id,
                "company_id": item.company_id.id,
                "dw_opening_id": item.id,
                "dw_project_id": item.project_id.id,
                "dw_sale_order_id": item.sale_order_id.id,
                "dw_drawing_revision_id": item.drawing_revision_id.id,
            })
            production.action_confirm()
            production._dw_generate_quality_checks()
            item.state = "production"
        return self.action_view_productions()

    def action_view_productions(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("mrp.mrp_production_action")
        action["domain"] = [("dw_opening_id", "=", self.id)]
        action["context"] = {"default_dw_opening_id": self.id}
        if self.production_count == 1:
            action["views"] = [(self.env.ref("mrp.mrp_production_form_view").id, "form")]
            action["res_id"] = self.production_ids.id
        return action

    def action_view_cost_lines(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Actual Cost Lines"),
            "res_model": "dw.production.cost.line",
            "view_mode": "list,pivot,form",
            "domain": [("opening_id", "=", self.id)],
            "context": {"default_opening_id": self.id},
        }

    def action_view_quality_checks(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Quality Checks"),
            "res_model": "dw.quality.check",
            "view_mode": "list,form",
            "domain": [("opening_id", "=", self.id)],
            "context": {"default_opening_id": self.id},
        }

    def action_recompute_actual_cost(self):
        productions = self.mapped("production_ids")
        if productions:
            productions._dw_recompute_actual_cost()
        return True

    def action_set_ready(self):
        for item in self:
            item._check_final_quality()
            item.state = "ready"
        return True

    def action_set_delivered(self):
        for item in self:
            if item.quality_state == "fail":
                raise UserError(
                    self.env._(
                        "Item %s failed quality control and cannot be delivered.", item.name
                    )
                )
            item.state = "delivered"
        return True

    def _check_final_quality(self):
        self.ensure_one()
        blocking = self.quality_check_ids.filtered(
            lambda check: check.is_mandatory and check.result != "pass"
        )
        if blocking:
            raise UserError(
                self.env._(
                    "Mandatory quality checks are not passed yet: %s",
                    ", ".join(blocking.mapped("display_name")),
                )
            )


class DwOpeningComponent(models.Model):
    _name = "dw.opening.component"
    _description = "Estimated Component"
    _order = "sequence, id"

    opening_id = fields.Many2one(
        "dw.opening", required=True, ondelete="cascade", index=True
    )
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(related="opening_id.company_id", store=True)
    currency_id = fields.Many2one(related="opening_id.currency_id", store=True)
    rule_id = fields.Many2one("dw.component.rule", ondelete="set null")
    product_id = fields.Many2one(
        "product.product", required=True, domain="[('type', 'in', ['consu', 'service'])]"
    )
    component_kind = fields.Selection(
        [
            ("material", "Raw Material"),
            ("subassembly", "Sub-Assembly"),
            ("service", "Outsourced Service"),
            ("customer_supplied", "Customer Supplied"),
        ],
        default="material",
        required=True,
    )
    include_in_bom = fields.Boolean(string="Include in Bill of Materials", default=True)
    operation_type_id = fields.Many2one("dw.operation.type", string="Operation")
    uom_id = fields.Many2one(
        "uom.uom", string="UoM", compute="_compute_uom_id", store=True, readonly=False
    )
    qty_per_unit = fields.Float(
        string="Quantity per Unit", required=True, digits=(16, 6)
    )
    total_qty = fields.Float(
        string="Total Quantity", compute="_compute_amounts", store=True, digits=(16, 6)
    )
    theoretical_weight_kg = fields.Float(
        string="Theoretical Weight (kg)", compute="_compute_amounts", store=True, digits=(16, 3)
    )
    estimated_unit_cost = fields.Monetary(string="Unit Cost", compute="_compute_amounts", store=True)
    estimated_total_cost = fields.Monetary(string="Total Cost", compute="_compute_amounts", store=True)
    note = fields.Char(translate=True)

    @api.depends("product_id")
    def _compute_uom_id(self):
        for line in self:
            if not line.uom_id or line.uom_id != line.product_id.uom_id:
                line.uom_id = line.product_id.uom_id

    @api.depends("qty_per_unit", "opening_id.quantity", "product_id.standard_price",
                 "product_id.dw_weight_per_uom", "component_kind", "uom_id")
    def _compute_amounts(self):
        for line in self:
            line.total_qty = line.qty_per_unit * (line.opening_id.quantity or 0.0)
            line.theoretical_weight_kg = (
                line.product_id.dw_weight_per_uom or 0.0
            ) * line.qty_per_unit
            if line.component_kind == "customer_supplied":
                line.estimated_unit_cost = 0.0
            else:
                line.estimated_unit_cost = line.product_id.standard_price
            line.estimated_total_cost = line.total_qty * line.estimated_unit_cost

    @api.constrains("qty_per_unit")
    def _check_quantity(self):
        for line in self:
            if line.qty_per_unit < 0:
                raise ValidationError(self.env._("Component quantity cannot be negative."))


class DwOpeningOperation(models.Model):
    _name = "dw.opening.operation"
    _description = "Planned Operation"
    _order = "sequence, id"

    opening_id = fields.Many2one(
        "dw.opening", required=True, ondelete="cascade", index=True
    )
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(related="opening_id.company_id", store=True)
    currency_id = fields.Many2one(related="opening_id.currency_id", store=True)
    operation_type_id = fields.Many2one("dw.operation.type", required=True)
    display_operation_name = fields.Char(string="Operation Name", compute="_compute_display_operation_name", store=True)
    workcenter_id = fields.Many2one("mrp.workcenter", string="Work Center")
    planned_minutes = fields.Float(string="Planned Minutes")
    labor_rate = fields.Float(
        string="Labour Rate / h", compute="_compute_rates", store=True, readonly=False
    )
    machine_rate = fields.Float(
        string="Machine Rate / h", compute="_compute_rates", store=True, readonly=False
    )
    labor_cost = fields.Monetary(string="Labour Cost", compute="_compute_operation_costs", store=True)
    machine_cost = fields.Monetary(string="Machine Cost", compute="_compute_operation_costs", store=True)
    is_outsourced = fields.Boolean(string="Outsourced")
    note = fields.Char(string="Note", translate=True)

    @api.depends("operation_type_id")
    def _compute_display_operation_name(self):
        for line in self:
            line.display_operation_name = line.operation_type_id.name or ""

    @api.depends("workcenter_id", "operation_type_id", "company_id")
    def _compute_rates(self):
        Rate = self.env["dw.labor.rate"]
        for line in self:
            rate = Rate._find_rate(
                company=line.company_id,
                workcenter=line.workcenter_id,
                operation_type=line.operation_type_id,
            )
            line.labor_rate = rate.hourly_cost if rate else 0.0
            line.machine_rate = line.workcenter_id.costs_hour or 0.0

    @api.depends("planned_minutes", "labor_rate", "machine_rate")
    def _compute_operation_costs(self):
        for line in self:
            hours = line.planned_minutes / 60.0
            line.labor_cost = hours * line.labor_rate
            line.machine_cost = hours * line.machine_rate


class DwOpeningExtraCost(models.Model):
    _name = "dw.opening.extra.cost"
    _description = "Manual Estimated Cost Item"
    _order = "sequence, id"

    opening_id = fields.Many2one(
        "dw.opening", required=True, ondelete="cascade", index=True
    )
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(related="opening_id.company_id", store=True)
    currency_id = fields.Many2one(related="opening_id.currency_id", store=True)
    name = fields.Char(required=True, translate=True)
    cost_type = fields.Selection(
        [
            ("material", "Material"),
            ("labor", "Labour"),
            ("machine", "Machine"),
            ("outsourcing", "Outsourcing"),
            ("contractor", "Contractor"),
            ("transport", "Transport"),
            ("installation", "Installation"),
            ("direct", "Direct Expense"),
            ("indirect", "Indirect Expense"),
            ("other", "Other"),
        ],
        default="other",
        required=True,
    )
    amount = fields.Monetary(required=True)
    approved = fields.Boolean(
        default=False,
        help="Only approved manual items are added to the estimated cost.",
    )
    approved_by = fields.Many2one("res.users", readonly=True)
    note = fields.Char(translate=True)

    def action_approve(self):
        self.write({"approved": True, "approved_by": self.env.user.id})
        return True
