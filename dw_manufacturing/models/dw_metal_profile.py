# -*- coding: utf-8 -*-
"""Theoretical weight engine for metal sections and sheets.

All formulas are closed-form and deterministic: the user picks a section shape
and enters its geometry, nothing is evaluated as code.
"""

import math

from odoo import api, fields, models
from odoo.exceptions import ValidationError

# Shapes whose weight is naturally expressed per linear meter.
LINEAR_SHAPES = (
    "round_tube",
    "square_tube",
    "rect_tube",
    "angle",
    "channel",
    "ibeam",
    "round_bar",
    "square_bar",
    "flat_bar",
    "custom_linear",
)
# Shapes whose weight is naturally expressed per square meter.
AREA_SHAPES = ("sheet", "chequered_plate", "mesh", "custom_area")


class DwMetalProfile(models.Model):
    _name = "dw.metal.profile"
    _description = "Metal Profile / Section"
    _order = "shape, name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char()
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    shape = fields.Selection(
        [
            ("sheet", "Sheet / Plate"),
            ("chequered_plate", "Chequered Plate"),
            ("mesh", "Wire Mesh"),
            ("round_tube", "Round Tube / Pipe"),
            ("square_tube", "Square Hollow Section"),
            ("rect_tube", "Rectangular Hollow Section"),
            ("angle", "Angle"),
            ("channel", "Channel"),
            ("ibeam", "I / H Beam"),
            ("round_bar", "Round Bar"),
            ("square_bar", "Square Bar"),
            ("flat_bar", "Flat Bar"),
            ("custom_linear", "Custom (weight per meter)"),
            ("custom_area", "Custom (weight per m²)"),
            ("custom_piece", "Custom (weight per piece)"),
        ],
        required=True,
        default="square_tube",
    )
    metal_type_id = fields.Many2one("dw.metal.type", string="Metal Type")
    metal_grade_id = fields.Many2one(
        "dw.metal.grade",
        string="Grade",
        domain="[('metal_type_id', '=', metal_type_id)]",
    )
    density = fields.Float(
        string="Density (kg/m³)",
        digits=(16, 2),
        compute="_compute_density",
        store=True,
        readonly=False,
        help="Defaults to the grade or metal type density; can be overridden.",
    )

    # Geometry, always in millimetres. Which ones matter depends on the shape.
    dim_a = fields.Float(string="A (mm)", help="Outer width / diameter / leg A.")
    dim_b = fields.Float(string="B (mm)", help="Outer height / leg B.")
    thickness_mm = fields.Float(string="Thickness (mm)")
    flange_thickness_mm = fields.Float(string="Flange Thickness (mm)")
    mesh_open_ratio = fields.Float(
        string="Open Area Ratio",
        default=0.0,
        help="Fraction of the sheet that is void, between 0 and 1. Used for mesh and perforated plate.",
    )

    manual_weight_per_m = fields.Float(string="Manual kg/m", digits=(16, 4))
    manual_weight_per_m2 = fields.Float(string="Manual kg/m²", digits=(16, 4))
    manual_weight_per_piece = fields.Float(string="Manual kg/piece", digits=(16, 4))
    use_manual_weight = fields.Boolean(
        string="Use Manual Weight",
        help="Ignore the geometric formula and use the manually entered weight.",
    )

    weight_per_m = fields.Float(
        string="kg / m", compute="_compute_weights", store=True, digits=(16, 4)
    )
    weight_per_m2 = fields.Float(
        string="kg / m²", compute="_compute_weights", store=True, digits=(16, 4)
    )
    weight_per_piece = fields.Float(
        string="kg / piece", compute="_compute_weights", store=True, digits=(16, 4)
    )
    weight_basis = fields.Selection(
        [("length", "Per Meter"), ("area", "Per m²"), ("piece", "Per Piece")],
        compute="_compute_weights",
        store=True,
    )
    commercial_length_m = fields.Float(
        string="Commercial Length (m)",
        default=6.0,
        help="Stock length used when a rule rounds quantities up to full bars.",
    )
    note = fields.Text(translate=True)

    @api.depends("metal_type_id", "metal_grade_id", "metal_grade_id.density", "metal_type_id.density")
    def _compute_density(self):
        for profile in self:
            if profile.metal_grade_id:
                profile.density = profile.metal_grade_id.effective_density or 7850.0
            elif profile.metal_type_id:
                profile.density = profile.metal_type_id.density or 7850.0
            else:
                profile.density = profile.density or 7850.0

    @api.depends(
        "shape",
        "density",
        "dim_a",
        "dim_b",
        "thickness_mm",
        "flange_thickness_mm",
        "mesh_open_ratio",
        "use_manual_weight",
        "manual_weight_per_m",
        "manual_weight_per_m2",
        "manual_weight_per_piece",
    )
    def _compute_weights(self):
        for profile in self:
            profile.weight_basis = profile._weight_basis()
            if profile.use_manual_weight or profile.shape.startswith("custom"):
                profile.weight_per_m = profile.manual_weight_per_m
                profile.weight_per_m2 = profile.manual_weight_per_m2
                profile.weight_per_piece = profile.manual_weight_per_piece
                continue
            per_m, per_m2 = profile._geometric_weights()
            profile.weight_per_m = per_m
            profile.weight_per_m2 = per_m2
            profile.weight_per_piece = profile.manual_weight_per_piece

    def _weight_basis(self):
        self.ensure_one()
        if self.shape in AREA_SHAPES:
            return "area"
        if self.shape == "custom_piece":
            return "piece"
        return "length"

    def _geometric_weights(self):
        """Return (kg per linear meter, kg per square meter) for this profile."""
        self.ensure_one()
        rho = self.density or 7850.0
        a = self.dim_a
        b = self.dim_b
        t = self.thickness_mm
        tf = self.flange_thickness_mm or t
        shape = self.shape
        per_m = 0.0
        per_m2 = 0.0

        if shape in ("sheet", "chequered_plate", "mesh"):
            # kg/m2 = thickness (m) * density
            per_m2 = (t / 1000.0) * rho
            if shape == "chequered_plate":
                # Raised pattern adds roughly 5% of mass on standard plates.
                per_m2 *= 1.05
            if shape == "mesh" and 0.0 < self.mesh_open_ratio < 1.0:
                per_m2 *= 1.0 - self.mesh_open_ratio
        elif shape == "round_tube":
            # Cross-section (mm²) = pi * (D - t) * t
            per_m = math.pi * max(a - t, 0.0) * t * rho / 1.0e6
        elif shape == "square_tube":
            per_m = 4.0 * max(a - t, 0.0) * t * rho / 1.0e6
        elif shape == "rect_tube":
            per_m = 2.0 * (max(a - t, 0.0) + max(b - t, 0.0)) * t * rho / 1.0e6
        elif shape == "angle":
            per_m = (a + b - t) * t * rho / 1.0e6
        elif shape == "channel":
            # web + two flanges
            per_m = ((b * t) + (2.0 * max(a - t, 0.0) * tf)) * rho / 1.0e6
        elif shape == "ibeam":
            per_m = ((max(b - 2.0 * tf, 0.0) * t) + (2.0 * a * tf)) * rho / 1.0e6
        elif shape == "round_bar":
            per_m = (math.pi / 4.0) * a * a * rho / 1.0e6
        elif shape == "square_bar":
            per_m = a * a * rho / 1.0e6
        elif shape == "flat_bar":
            per_m = a * t * rho / 1.0e6
        return per_m, per_m2

    @api.constrains("mesh_open_ratio")
    def _check_open_ratio(self):
        for profile in self:
            if not 0.0 <= profile.mesh_open_ratio < 1.0:
                raise ValidationError(
                    self.env._("The open area ratio must be between 0 and 1 (excluded).")
                )

    def weight_for(self, length_m=0.0, area_m2=0.0, pieces=0.0):
        """Theoretical weight in kg for the supplied measurements."""
        self.ensure_one()
        basis = self.weight_basis
        if basis == "area":
            return self.weight_per_m2 * area_m2
        if basis == "piece":
            return self.weight_per_piece * pieces
        return self.weight_per_m * length_m


class ProductTemplate(models.Model):
    _inherit = "product.template"

    dw_metal_profile_id = fields.Many2one(
        "dw.metal.profile",
        string="Metal Profile",
        help="Links the raw material to the theoretical weight engine.",
    )
    dw_material_kind = fields.Selection(
        [
            ("sheet", "Sheet"),
            ("tube", "Tube"),
            ("section", "Section"),
            ("angle", "Angle"),
            ("beam", "Beam"),
            ("bar", "Bar"),
            ("mesh", "Mesh"),
            ("panel", "Panel"),
            ("glass", "Glass"),
            ("accessory", "Accessory"),
            ("hinge", "Hinge"),
            ("lock", "Lock"),
            ("paint", "Paint"),
            ("galvanizing", "Galvanizing Material"),
            ("welding", "Welding Material"),
            ("fastener", "Fastener"),
            ("packing", "Packing Material"),
            ("customer_supplied", "Customer Supplied"),
            ("finished", "Finished Metal Product"),
            ("semi_finished", "Semi-Finished Product"),
            ("service", "Service / Outsourcing"),
        ],
        string="Metal Material Kind",
    )
    dw_is_customer_supplied = fields.Boolean(
        string="Supplied by Customer",
        help="Consumed in production but not charged to the project cost.",
    )
    dw_weight_per_uom = fields.Float(
        string="Weight per UoM (kg)",
        compute="_compute_dw_weight_per_uom",
        store=True,
        readonly=False,
        digits=(16, 4),
        help="Theoretical kilograms carried by one unit of the product UoM.",
    )
    dw_commercial_length_m = fields.Float(
        string="Commercial Length (m)",
        related="dw_metal_profile_id.commercial_length_m",
        readonly=False,
        store=True,
    )

    @api.depends("dw_metal_profile_id", "dw_metal_profile_id.weight_per_m",
                 "dw_metal_profile_id.weight_per_m2", "dw_metal_profile_id.weight_per_piece")
    def _compute_dw_weight_per_uom(self):
        for template in self:
            profile = template.dw_metal_profile_id
            if not profile:
                template.dw_weight_per_uom = template.dw_weight_per_uom or 0.0
                continue
            template.dw_weight_per_uom = {
                "length": profile.weight_per_m,
                "area": profile.weight_per_m2,
                "piece": profile.weight_per_piece,
            }.get(profile.weight_basis, 0.0)


class ProductProduct(models.Model):
    _inherit = "product.product"

    def dw_theoretical_weight(self, quantity):
        """Theoretical kilograms for `quantity` expressed in the product UoM."""
        self.ensure_one()
        return (self.dw_weight_per_uom or 0.0) * quantity
