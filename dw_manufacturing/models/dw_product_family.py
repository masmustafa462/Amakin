# -*- coding: utf-8 -*-
"""Configurable product families.

A family describes *a kind of metal product* (fence, staircase, door, canopy...).
It decides which dimensions the manufacturing item asks for, how quantity and
weight are derived, which operations are planned, which quality template applies
and which component rules are used. Adding a new metal product to the system is
therefore a configuration exercise, not a development one.
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError

# Sensible dimension set per kind of metal product. Used both to preselect the
# dimensions when the kind is chosen and as a fallback so a family that was
# saved without any dimension never produces an unusable, empty item form.
DIMENSION_PRESETS = {
    "door": ["width", "height", "thickness", "leaf_count", "weld_length", "paint_area"],
    "fire_door": ["width", "height", "thickness", "leaf_count", "weld_length", "paint_area"],
    "window": ["width", "height", "leaf_count", "paint_area"],
    "facade": ["width", "height", "section_count", "paint_area"],
    "gate": ["width", "height", "leaf_count", "weld_length", "paint_area"],
    "fence": ["length", "height", "post_spacing", "post_count", "section_count",
              "weld_length", "paint_area", "galv_area"],
    "handrail": ["length", "height", "post_spacing", "post_count", "section_count",
                 "weld_length", "paint_area"],
    "staircase": ["total_rise", "step_count", "step_height", "step_width", "width",
                  "stair_angle", "weld_length", "paint_area"],
    "spiral_staircase": ["total_rise", "step_count", "step_height", "diameter",
                         "stair_angle", "weld_length", "paint_area"],
    "canopy": ["length", "width", "height", "post_count", "paint_area", "galv_area"],
    "structure": ["length", "width", "height", "weld_length", "paint_area", "galv_area"],
    "shelving": ["length", "width", "height", "section_count", "paint_area"],
    "sheet_metal": ["length", "width", "thickness", "paint_area"],
}

# Applied when the kind has no preset of its own (custom, other).
GENERIC_DIMENSION_CODES = [
    "length", "width", "height", "thickness", "leaf_count", "weld_length", "paint_area",
]


class DwProductFamily(models.Model):
    _name = "dw.product.family"
    _description = "Metal Product Family"
    _order = "sequence, id"

    name = fields.Char(string="Name (English)", required=True, translate=True)
    name_ar = fields.Char(string="Name (Arabic)")
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company,
        help="Leave empty to share the family across all companies.",
    )
    product_kind = fields.Selection(
        [
            ("door", "Door"),
            ("fire_door", "Fire Rated Door"),
            ("window", "Window"),
            ("facade", "Facade"),
            ("gate", "Gate"),
            ("fence", "Fence"),
            ("handrail", "Handrail / Balustrade"),
            ("staircase", "Staircase"),
            ("spiral_staircase", "Spiral Staircase"),
            ("canopy", "Canopy / Shade"),
            ("structure", "Light Steel Structure"),
            ("shelving", "Shelving / Platform"),
            ("sheet_metal", "Sheet Metal Work"),
            ("custom", "Custom Product"),
            ("other", "Other"),
        ],
        required=True,
        default="custom",
    )

    # --- How the quantity of the finished item is measured -------------------
    quantity_method = fields.Selection(
        [
            ("unit", "By Unit"),
            ("length", "By Linear Meter"),
            ("area", "By Square Meter"),
            ("volume", "By Cubic Meter"),
            ("weight", "By Kilogram"),
        ],
        required=True,
        default="unit",
        string="Quantity Method",
    )
    weight_method = fields.Selection(
        [
            ("components", "Sum of Component Theoretical Weights"),
            ("manual", "Manually Entered"),
            ("per_area", "Weight per m² x Area"),
            ("per_length", "Weight per m x Length"),
            ("per_unit", "Weight per Unit x Count"),
        ],
        required=True,
        default="components",
        string="Weight Method",
    )
    weight_factor = fields.Float(
        string="Weight Factor (kg)",
        default=0.0,
        help="Kilograms per m², per meter or per unit depending on the weight method.",
    )
    pricing_method = fields.Selection(
        [
            ("cost_plus", "Cost plus Markup"),
            ("per_m2", "Price per m²"),
            ("per_m", "Price per Linear Meter"),
            ("per_kg", "Price per Kilogram"),
            ("per_unit", "Price per Unit"),
        ],
        required=True,
        default="cost_plus",
        string="Default Pricing Method",
    )
    default_markup_percent = fields.Float(default=25.0)
    default_price_unit = fields.Float(
        string="Default Rate",
        help="Rate used by the per m², per meter, per kg or per unit pricing methods.",
    )
    default_waste_percent = fields.Float(default=5.0)

    # --- Units of measure ----------------------------------------------------
    uom_id = fields.Many2one(
        "uom.uom",
        string="Sales UoM",
        default=lambda self: self.env.ref("uom.product_uom_unit", raise_if_not_found=False),
    )
    dimension_uom_id = fields.Many2one(
        "uom.uom",
        string="Dimension UoM",
        default=lambda self: self.env.ref("uom.product_uom_millimeter", raise_if_not_found=False),
        help="Informative: dimensions are always captured in millimetres.",
    )
    weight_uom_id = fields.Many2one(
        "uom.uom",
        string="Weight UoM",
        default=lambda self: self.env.ref("uom.product_uom_kgm", raise_if_not_found=False),
    )

    # --- Which inputs the manufacturing item shows ---------------------------
    dimension_ids = fields.Many2many(
        "dw.dimension.field",
        "dw_family_dimension_rel",
        "family_id",
        "dimension_id",
        string="Dimensions Shown",
    )
    required_dimension_ids = fields.Many2many(
        "dw.dimension.field",
        "dw_family_required_dimension_rel",
        "family_id",
        "dimension_id",
        string="Mandatory Dimensions",
    )
    dimension_codes = fields.Char(compute="_compute_dimension_codes", store=True)
    required_dimension_codes = fields.Char(compute="_compute_dimension_codes", store=True)
    uses_default_dimensions = fields.Boolean(
        string="Using Default Dimensions",
        compute="_compute_dimension_codes",
        store=True,
        help="No dimension was selected, so the standard set for this product kind is shown.",
    )

    # --- Defaults propagated to new manufacturing items ----------------------
    default_product_id = fields.Many2one(
        "product.product",
        string="Default Finished Product",
        domain="[('type', '=', 'consu')]",
    )
    metal_type_id = fields.Many2one("dw.metal.type", string="Default Metal Type")
    finish_type_id = fields.Many2one("dw.finish.type", string="Default Finish")
    operation_ids = fields.One2many(
        "dw.product.family.operation", "family_id", string="Default Operations", copy=True
    )
    quality_template_id = fields.Many2one(
        "dw.quality.template",
        string="Default Quality Template",
        domain="['|', ('family_id', '=', False), ('family_id', '=', id)]",
    )
    component_rule_ids = fields.One2many(
        "dw.component.rule", "family_id", string="Component Rules"
    )
    component_rule_count = fields.Integer(compute="_compute_counts")
    item_count = fields.Integer(compute="_compute_counts")

    # --- Documentation -------------------------------------------------------
    manufacturing_notes = fields.Html(string="Manufacturing Instructions", translate=True)
    note = fields.Text(translate=True)

    _code_uniq = models.Constraint(
        "unique(code, company_id)", "The product family code must be unique per company."
    )

    @api.model
    def _preset_dimension_codes(self, product_kind):
        """Standard dimension codes for a kind of metal product."""
        return DIMENSION_PRESETS.get(product_kind) or GENERIC_DIMENSION_CODES

    def _effective_dimension_codes(self):
        """Codes actually shown on the manufacturing item.

        A family saved with no dimension would otherwise hide every input and
        leave the user unable to enter anything, so the standard set for the
        product kind is used instead.
        """
        self.ensure_one()
        return self.dimension_ids.mapped("code") or self._preset_dimension_codes(
            self.product_kind
        )

    @api.depends("dimension_ids.code", "required_dimension_ids.code", "product_kind")
    def _compute_dimension_codes(self):
        for family in self:
            family.uses_default_dimensions = not family.dimension_ids
            family.dimension_codes = ",%s," % ",".join(family._effective_dimension_codes())
            family.required_dimension_codes = ",%s," % ",".join(
                family.required_dimension_ids.mapped("code")
            )

    def _compute_counts(self):
        rule_data = self.env["dw.component.rule"]._read_group(
            [("family_id", "in", self.ids)], ["family_id"], ["__count"]
        )
        rule_map = {family.id: count for family, count in rule_data}
        item_data = self.env["dw.opening"]._read_group(
            [("family_id", "in", self.ids)], ["family_id"], ["__count"]
        )
        item_map = {family.id: count for family, count in item_data}
        for family in self:
            family.component_rule_count = rule_map.get(family.id, 0)
            family.item_count = item_map.get(family.id, 0)

    @api.constrains("required_dimension_ids", "dimension_ids")
    def _check_required_subset(self):
        for family in self:
            extra = family.required_dimension_ids - family.dimension_ids
            if extra:
                raise ValidationError(
                    self.env._(
                        "These dimensions are mandatory but not shown: %s",
                        ", ".join(extra.mapped("name")),
                    )
                )

    @api.onchange("product_kind")
    def _onchange_product_kind(self):
        """Preselect a sensible dimension set so a new family is usable at once."""
        codes = self._preset_dimension_codes(self.product_kind)
        dimensions = self.env["dw.dimension.field"].search([("code", "in", codes)])
        self.dimension_ids = [(6, 0, dimensions.ids)]

    def action_apply_default_dimensions(self):
        """Write the standard dimension set of the product kind onto the family."""
        for family in self:
            codes = family._preset_dimension_codes(family.product_kind)
            dimensions = self.env["dw.dimension.field"].search([("code", "in", codes)])
            family.dimension_ids = [(6, 0, dimensions.ids)]
        return True

    def action_view_component_rules(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Component Rules"),
            "res_model": "dw.component.rule",
            "view_mode": "list,form",
            "domain": [("family_id", "=", self.id)],
            "context": {"default_family_id": self.id},
        }

    def action_view_items(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Manufacturing Items"),
            "res_model": "dw.opening",
            "view_mode": "list,form",
            "domain": [("family_id", "=", self.id)],
            "context": {"default_family_id": self.id},
        }


class DwProductFamilyOperation(models.Model):
    _name = "dw.product.family.operation"
    _description = "Default Operation of a Product Family"
    _order = "sequence, id"

    family_id = fields.Many2one(
        "dw.product.family", required=True, ondelete="cascade", index=True
    )
    sequence = fields.Integer(default=10)
    operation_type_id = fields.Many2one(
        "dw.operation.type", string="Operation", required=True
    )
    workcenter_id = fields.Many2one(
        "mrp.workcenter",
        string="Work Center",
        help="Overrides the work center defined on the operation type.",
    )
    time_mode = fields.Selection(
        related="operation_type_id.time_mode", readonly=False, store=True
    )
    time_value = fields.Float(
        string="Minutes", related="operation_type_id.time_value", readonly=False, store=True
    )
    setup_minutes = fields.Float(
        related="operation_type_id.setup_minutes", readonly=False, store=True
    )
    is_outsourced = fields.Boolean(related="operation_type_id.is_outsourced", store=True)
    note = fields.Text(translate=True)

    def _effective_workcenter(self):
        self.ensure_one()
        return self.workcenter_id or self.operation_type_id.workcenter_id

    def _duration_for(self, item, produced_qty=1.0):
        self.ensure_one()
        basis = {
            "fixed": 1.0,
            "per_unit": produced_qty,
            "per_meter": item.total_length_m,
            "per_m2": item.paint_area_m2 or item.area_m2,
            "per_kg": item.theoretical_weight_kg,
            "per_weld_meter": item.weld_length_m,
        }.get(self.time_mode, 1.0)
        return self.setup_minutes + (self.time_value * basis)
