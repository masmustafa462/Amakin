# -*- coding: utf-8 -*-
"""Light configuration models shared by the whole Metal Fabrication application.

Everything here is data driven on purpose: an administrator can add a new metal
type, finish, dimension or operation from the user interface without touching
any Python code.
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class DwDimensionField(models.Model):
    """Catalogue of the measurable attributes a manufacturing item can carry.

    A product family ticks the subset it needs; the manufacturing item form then
    shows exactly those inputs. This is what makes "add a new metal product
    without code" possible.
    """

    _name = "dw.dimension.field"
    _description = "Manufacturing Dimension"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        required=True,
        help="Technical code of the matching field on the manufacturing item.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    uom_label = fields.Char(translate=True)
    is_computed = fields.Boolean(
        string="Computed",
        help="Computed dimensions are derived from the entered ones and cannot be required.",
    )
    note = fields.Text(translate=True)

    _code_uniq = models.Constraint("unique(code)", "The dimension code must be unique.")


class DwMetalType(models.Model):
    _name = "dw.metal.type"
    _description = "Metal Type"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    density = fields.Float(
        string="Density (kg/m³)",
        default=7850.0,
        digits=(16, 2),
        help="Used by the theoretical weight engine when the profile does not override it.",
    )
    grade_ids = fields.One2many("dw.metal.grade", "metal_type_id", string="Grades")
    note = fields.Text(translate=True)

    @api.constrains("density")
    def _check_density(self):
        for record in self:
            if record.density < 0:
                raise ValidationError(self.env._("Density cannot be negative."))


class DwMetalGrade(models.Model):
    _name = "dw.metal.grade"
    _description = "Metal Grade or Specification"
    _order = "metal_type_id, sequence, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    metal_type_id = fields.Many2one("dw.metal.type", required=True, ondelete="cascade", index=True)
    density = fields.Float(
        string="Density (kg/m³)",
        digits=(16, 2),
        help="Leave zero to inherit the density of the metal type.",
    )
    standard = fields.Char(string="Standard", help="ASTM, EN, SASO, ...")
    yield_strength = fields.Float(string="Yield Strength (MPa)")
    note = fields.Text(translate=True)

    @property
    def effective_density(self):
        self.ensure_one()
        return self.density or self.metal_type_id.density


class DwFinishType(models.Model):
    _name = "dw.finish.type"
    _description = "Finish Type"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    kind = fields.Selection(
        [
            ("paint", "Paint"),
            ("powder", "Powder Coating"),
            ("galvanizing", "Galvanizing"),
            ("polish", "Polishing"),
            ("raw", "Raw / Untreated"),
            ("other", "Other"),
        ],
        default="paint",
        required=True,
    )
    coverage_m2_per_unit = fields.Float(
        string="Coverage (m² per unit)",
        help="Square meters covered by one unit of the consumable (litre, kg...).",
    )
    consumable_product_id = fields.Many2one(
        "product.product",
        string="Consumable",
        domain="[('type', '=', 'consu')]",
    )
    note = fields.Text(translate=True)


class DwOperationType(models.Model):
    """Catalogue of fabrication operations (cutting, welding, painting...)."""

    _name = "dw.operation.type"
    _description = "Fabrication Operation Type"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    workcenter_id = fields.Many2one(
        "mrp.workcenter",
        string="Default Work Center",
        check_company=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    time_mode = fields.Selection(
        [
            ("fixed", "Fixed minutes"),
            ("per_unit", "Minutes per produced unit"),
            ("per_meter", "Minutes per linear meter"),
            ("per_m2", "Minutes per square meter"),
            ("per_kg", "Minutes per kilogram"),
            ("per_weld_meter", "Minutes per welding meter"),
        ],
        default="fixed",
        required=True,
    )
    time_value = fields.Float(string="Minutes", default=0.0)
    setup_minutes = fields.Float(string="Setup Minutes", default=0.0)
    is_outsourced = fields.Boolean(string="Outsourced")
    note = fields.Text(translate=True)

    _code_uniq = models.Constraint(
        "unique(code, company_id)", "The operation code must be unique per company."
    )

    def _duration_for(self, item, produced_qty=1.0):
        """Return the expected duration in minutes for one manufacturing item."""
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
