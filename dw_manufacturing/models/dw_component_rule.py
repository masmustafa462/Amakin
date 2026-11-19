# -*- coding: utf-8 -*-
"""Safe, configurable component / quantity engine.

Design rule: **no user supplied Python is ever executed.**
There is no ``eval``, no ``safe_eval`` and no expression string parsing.
A formula is a stored, ordered list of typed terms (a variable taken from a
closed catalogue, or a constant) combined with a small set of arithmetic
operators. The engine walks that list. Anything a user can save is therefore
structurally incapable of running code.
"""

import math

from odoo import api, fields, models
from odoo.exceptions import ValidationError

# --------------------------------------------------------------------------
# Closed catalogue of variables usable in a formula.
# code -> (label, attribute on dw.opening)
# --------------------------------------------------------------------------
RULE_VARIABLES = [
    ("one", "Constant 1", "dw_one"),
    ("item_qty", "Item Count", "quantity"),
    ("length", "Length (m)", "length_m"),
    ("width", "Width (m)", "width_m"),
    ("height", "Height (m)", "height_m"),
    ("thickness", "Thickness (m)", "thickness_m"),
    ("thickness_mm", "Thickness (mm)", "thickness_mm"),
    ("diameter", "Diameter (m)", "diameter_m"),
    ("diameter_mm", "Diameter (mm)", "diameter_mm"),
    ("perimeter", "Perimeter (m)", "perimeter_m"),
    ("area", "Area (m2)", "area_m2"),
    ("volume", "Volume (m3)", "volume_m3"),
    ("weight", "Theoretical Weight (kg)", "theoretical_weight_kg"),
    ("total_length", "Total Linear Length (m)", "total_length_m"),
    ("leaf_count", "Leaf Count", "leaf_count"),
    ("post_count", "Post Count", "post_count"),
    ("section_count", "Section Count", "section_count"),
    ("step_count", "Step Count", "step_count"),
    ("step_height", "Step Height (m)", "step_height_m"),
    ("step_width", "Step Width (m)", "step_width_m"),
    ("total_rise", "Total Rise (m)", "total_rise_m"),
    ("stair_angle", "Stair Angle (degrees)", "stair_angle_deg"),
    ("stair_slope_length", "Stair Slope Length (m)", "stair_slope_length_m"),
    ("weld_length", "Welding Length (m)", "weld_length_m"),
    ("paint_area", "Painting Area (m2)", "paint_area_m2"),
    ("galv_area", "Galvanizing Area (m2)", "galv_area_m2"),
    ("post_spacing", "Post Spacing (m)", "post_spacing_m"),
]

VARIABLE_SELECTION = [(code, label) for code, label, _attr in RULE_VARIABLES]
VARIABLE_ATTRIBUTE = {code: attr for code, _label, attr in RULE_VARIABLES}


def _variable_value(item, code):
    """Read one catalogue variable off a manufacturing item. Never evaluates code."""
    attribute = VARIABLE_ATTRIBUTE.get(code)
    if not attribute:
        return 0.0
    return float(getattr(item, attribute, 0.0) or 0.0)


class DwComponentRule(models.Model):
    _name = "dw.component.rule"
    _description = "Component and Quantity Rule"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )

    # ---- Scope -------------------------------------------------------------
    family_id = fields.Many2one(
        "dw.product.family",
        string="Product Family",
        index=True,
        ondelete="cascade",
    )
    finished_product_tmpl_id = fields.Many2one(
        "product.template",
        string="Finished Product Template",
        domain="[('type', '=', 'consu')]",
        help="Optional. When set the rule only applies to this finished product.",
    )
    opening_type = fields.Selection(
        [
            ("all", "All Types"),
            ("door", "Door"),
            ("window", "Window"),
            ("facade", "Facade"),
            ("other", "Other"),
        ],
        required=True,
        default="all",
        string="Legacy Item Type",
        help="Kept from the first phase so existing rules keep matching.",
    )

    # ---- What is produced by the rule --------------------------------------
    component_product_id = fields.Many2one(
        "product.product",
        string="Component",
        required=True,
        domain="[('type', 'in', ['consu', 'service'])]",
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
    uom_id = fields.Many2one(
        "uom.uom",
        string="Unit of Measure",
        help="Leave empty to use the component's own unit of measure.",
    )
    operation_type_id = fields.Many2one(
        "dw.operation.type",
        string="Consumed at Operation",
        help="Informative link between a material and the operation using it.",
    )

    # ---- Quantity calculation ----------------------------------------------
    calc_method = fields.Selection(
        [
            ("fixed", "Fixed Quantity"),
            ("variable", "Single Variable x Factor"),
            ("formula", "Guided Formula"),
        ],
        required=True,
        default="variable",
    )
    basis = fields.Selection(
        VARIABLE_SELECTION + [("fixed", "Fixed Quantity")],
        required=True,
        default="fixed",
        string="Variable",
    )
    factor = fields.Float(
        default=1.0, digits=(16, 6), help="Multiplier applied to the selected variable."
    )
    fixed_qty = fields.Float(default=1.0, digits=(16, 6))
    term_ids = fields.One2many(
        "dw.component.rule.term", "rule_id", string="Formula Terms", copy=True
    )
    formula_preview = fields.Char(compute="_compute_formula_preview")

    # ---- Post processing ----------------------------------------------------
    extra_qty = fields.Float(
        string="Extra Quantity", default=0.0, digits=(16, 6),
        help="Added after the formula, before waste.",
    )
    conversion_factor = fields.Float(
        default=1.0, digits=(16, 6),
        help="Converts the formula result into the component unit of measure.",
    )
    waste_percent = fields.Float(default=0.0, string="Waste %")
    min_qty = fields.Float(default=0.0, digits=(16, 6))
    round_mode = fields.Selection(
        [
            ("none", "No Rounding"),
            ("up", "Round Up"),
            ("down", "Round Down"),
            ("nearest", "Round to Nearest"),
        ],
        default="none",
        required=True,
    )
    rounding_multiple = fields.Float(
        default=0.0, digits=(16, 6),
        help="Round the quantity to a multiple of this value. Zero disables it.",
    )
    round_commercial = fields.Boolean(
        string="Round to Commercial Length",
        help="Round the length up to whole commercial bars / sheets.",
    )
    commercial_length_m = fields.Float(
        string="Commercial Length (m)", default=6.0, digits=(16, 4)
    )
    commercial_output = fields.Selection(
        [("length", "Keep Meters"), ("pieces", "Convert to Pieces")],
        default="length",
        required=True,
    )
    condition_ids = fields.One2many(
        "dw.component.rule.condition", "rule_id", string="Conditions", copy=True
    )
    note = fields.Text(translate=True)

    @api.constrains("factor", "fixed_qty", "waste_percent", "rounding_multiple",
                    "conversion_factor", "min_qty", "commercial_length_m")
    def _check_non_negative_values(self):
        for rule in self:
            if (
                rule.factor < 0
                or rule.fixed_qty < 0
                or rule.waste_percent < 0
                or rule.rounding_multiple < 0
                or rule.min_qty < 0
                or rule.commercial_length_m < 0
            ):
                raise ValidationError(
                    self.env._("Rule quantities, waste and rounding cannot be negative.")
                )
            if rule.conversion_factor == 0:
                raise ValidationError(self.env._("The conversion factor cannot be zero."))

    @api.constrains("calc_method", "term_ids")
    def _check_formula(self):
        for rule in self:
            if rule.calc_method == "formula" and not rule.term_ids:
                raise ValidationError(
                    self.env._("A guided formula needs at least one term: %s", rule.name)
                )

    @api.depends("term_ids.operator", "term_ids.operand_type", "term_ids.variable",
                 "term_ids.constant_value", "calc_method", "basis", "factor", "fixed_qty")
    def _compute_formula_preview(self):
        labels = dict(VARIABLE_SELECTION)
        for rule in self:
            if rule.calc_method == "fixed":
                rule.formula_preview = "%s" % rule.fixed_qty
            elif rule.calc_method == "variable":
                if rule.basis == "fixed":
                    rule.formula_preview = "%s" % rule.fixed_qty
                else:
                    rule.formula_preview = "%s x %s" % (
                        labels.get(rule.basis, rule.basis),
                        rule.factor,
                    )
            else:
                parts = []
                for index, term in enumerate(rule.term_ids.sorted("sequence")):
                    operand = (
                        labels.get(term.variable, term.variable)
                        if term.operand_type == "variable"
                        else "%s" % term.constant_value
                    )
                    parts.append(operand if index == 0 else "%s %s" % (term.operator, operand))
                rule.formula_preview = " ".join(parts)

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------
    @api.model
    def _rules_for_item(self, item):
        company_ids = [item.company_id.id or self.env.company.id]
        base_domain = [("active", "=", True), ("company_id", "in", company_ids)]
        if item.family_id:
            domain = base_domain + [("family_id", "=", item.family_id.id)]
        else:
            domain = base_domain + [
                ("family_id", "=", False),
                ("finished_product_tmpl_id", "=", item.finished_product_id.product_tmpl_id.id),
                ("opening_type", "in", ["all", item.opening_type or "other"]),
            ]
        rules = self.search(domain, order="sequence, id")
        # A family rule may still narrow itself to one finished product.
        return rules.filtered(
            lambda rule: not rule.finished_product_tmpl_id
            or rule.finished_product_tmpl_id == item.finished_product_id.product_tmpl_id
        )

    def _conditions_met(self, item):
        self.ensure_one()
        for condition in self.condition_ids:
            if not condition._evaluate(item):
                return False
        return True

    # ------------------------------------------------------------------
    # Calculation
    # ------------------------------------------------------------------
    def _raw_quantity(self, item):
        """Quantity before waste, rounding and conversion."""
        self.ensure_one()
        if self.calc_method == "fixed":
            return self.fixed_qty
        if self.calc_method == "variable":
            if self.basis == "fixed":
                return self.fixed_qty
            return _variable_value(item, self.basis) * self.factor
        # Guided formula: strictly ordered, left to right, no code execution.
        terms = self.term_ids.sorted("sequence")
        if not terms:
            return 0.0
        result = terms[0]._operand_value(item)
        for term in terms[1:]:
            operand = term._operand_value(item)
            operator = term.operator
            if operator == "+":
                result += operand
            elif operator == "-":
                result -= operand
            elif operator == "*":
                result *= operand
            elif operator == "/":
                result = result / operand if operand else 0.0
            elif operator == "^":
                try:
                    result = math.pow(result, operand)
                except (ValueError, OverflowError):
                    result = 0.0
        return result

    def calculate_quantity(self, opening):
        """Component quantity for **one** finished unit of the item.

        Kept under its phase-1 name and signature so existing calls keep working.
        """
        self.ensure_one()
        item = opening
        if not self._conditions_met(item):
            return 0.0

        quantity = self._raw_quantity(item)
        quantity += self.extra_qty
        quantity *= self.conversion_factor or 1.0
        quantity *= 1.0 + (self.waste_percent / 100.0)

        if self.round_commercial and self.commercial_length_m > 0:
            bars = math.ceil(quantity / self.commercial_length_m - 1e-9)
            quantity = bars if self.commercial_output == "pieces" \
                else bars * self.commercial_length_m

        if self.rounding_multiple:
            ratio = quantity / self.rounding_multiple
            if self.round_mode == "down":
                ratio = math.floor(ratio + 1e-9)
            elif self.round_mode == "nearest":
                ratio = round(ratio)
            else:
                ratio = math.ceil(ratio - 1e-9)
            quantity = ratio * self.rounding_multiple
        elif self.round_mode == "up":
            quantity = math.ceil(quantity - 1e-9)
        elif self.round_mode == "down":
            quantity = math.floor(quantity + 1e-9)
        elif self.round_mode == "nearest":
            quantity = float(round(quantity))

        if self.min_qty and quantity < self.min_qty:
            quantity = self.min_qty
        return max(quantity, 0.0)

    def _target_uom(self):
        self.ensure_one()
        return self.uom_id or self.component_product_id.uom_id


class DwComponentRuleTerm(models.Model):
    _name = "dw.component.rule.term"
    _description = "Component Rule Formula Term"
    _order = "sequence, id"

    rule_id = fields.Many2one(
        "dw.component.rule", required=True, ondelete="cascade", index=True
    )
    sequence = fields.Integer(default=10)
    operator = fields.Selection(
        [
            ("+", "Add"),
            ("-", "Subtract"),
            ("*", "Multiply"),
            ("/", "Divide"),
            ("^", "Power"),
        ],
        default="*",
        required=True,
        help="Ignored on the first term. Terms are applied in order, top to bottom.",
    )
    operand_type = fields.Selection(
        [("variable", "Variable"), ("constant", "Constant")],
        default="variable",
        required=True,
    )
    variable = fields.Selection(VARIABLE_SELECTION, default="area")
    constant_value = fields.Float(default=1.0, digits=(16, 6))
    note = fields.Char(translate=True)

    def _operand_value(self, item):
        self.ensure_one()
        if self.operand_type == "constant":
            return self.constant_value
        return _variable_value(item, self.variable)

    @api.constrains("operand_type", "variable")
    def _check_variable(self):
        for term in self:
            if term.operand_type == "variable" and not term.variable:
                raise ValidationError(self.env._("Select a variable for the formula term."))


class DwComponentRuleCondition(models.Model):
    _name = "dw.component.rule.condition"
    _description = "Component Rule Condition"
    _order = "sequence, id"

    rule_id = fields.Many2one(
        "dw.component.rule", required=True, ondelete="cascade", index=True
    )
    sequence = fields.Integer(default=10)
    variable = fields.Selection(VARIABLE_SELECTION, required=True, default="area")
    operator = fields.Selection(
        [
            (">", ">"),
            (">=", ">="),
            ("<", "<"),
            ("<=", "<="),
            ("=", "="),
            ("!=", "!="),
        ],
        required=True,
        default=">",
    )
    value = fields.Float(default=0.0, digits=(16, 6))

    def _evaluate(self, item):
        self.ensure_one()
        left = _variable_value(item, self.variable)
        right = self.value
        operator = self.operator
        if operator == ">":
            return left > right
        if operator == ">=":
            return left >= right
        if operator == "<":
            return left < right
        if operator == "<=":
            return left <= right
        if operator == "=":
            return abs(left - right) < 1e-9
        return abs(left - right) >= 1e-9
