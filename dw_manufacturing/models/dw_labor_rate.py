# -*- coding: utf-8 -*-
"""Hourly labour cost rates.

Rates can be defined per user, per work center, per operation type or as a
company wide fallback, with a validity period. The most specific valid rate
wins.
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class DwLaborRate(models.Model):
    _name = "dw.labor.rate"
    _description = "Labour Hourly Rate"
    _order = "sequence, date_start desc, id desc"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    user_id = fields.Many2one("res.users", string="Employee / User", index="btree_not_null")
    employee_category = fields.Selection(
        [
            ("helper", "Helper"),
            ("fabricator", "Fabricator"),
            ("welder", "Welder"),
            ("painter", "Painter"),
            ("fitter", "Fitter / Installer"),
            ("machinist", "Machinist"),
            ("supervisor", "Supervisor"),
            ("engineer", "Engineer"),
            ("other", "Other"),
        ],
        string="Category",
    )
    workcenter_id = fields.Many2one("mrp.workcenter", string="Work Center", index="btree_not_null")
    operation_type_id = fields.Many2one("dw.operation.type", string="Operation Type")
    date_start = fields.Date(string="Valid From", default=fields.Date.context_today)
    date_end = fields.Date(string="Valid To")
    hourly_cost = fields.Monetary(string="Cost per Hour", required=True)
    overtime_multiplier = fields.Float(default=1.5)
    note = fields.Text(translate=True)

    @api.constrains("date_start", "date_end")
    def _check_dates(self):
        for rate in self:
            if rate.date_end and rate.date_start and rate.date_end < rate.date_start:
                raise ValidationError(
                    self.env._("The end date cannot be earlier than the start date.")
                )

    @api.constrains("hourly_cost")
    def _check_cost(self):
        for rate in self:
            if rate.hourly_cost < 0:
                raise ValidationError(self.env._("The hourly cost cannot be negative."))

    @api.model
    def _find_rate(self, company, workcenter=None, operation_type=None, user=None, date=None):
        """Return the most specific valid rate, or an empty recordset."""
        date = date or fields.Date.context_today(self)
        company_id = company.id if company else self.env.company.id
        domain = [
            ("active", "=", True),
            ("company_id", "=", company_id),
            "|", ("date_start", "=", False), ("date_start", "<=", date),
            "|", ("date_end", "=", False), ("date_end", ">=", date),
        ]
        candidates = self.search(domain)
        if not candidates:
            return self.browse()

        def score(rate):
            value = 0
            if user and rate.user_id == user:
                value += 8
            elif rate.user_id:
                return -1
            if workcenter and rate.workcenter_id == workcenter:
                value += 4
            elif rate.workcenter_id:
                return -1
            if operation_type and rate.operation_type_id == operation_type:
                value += 2
            elif rate.operation_type_id:
                return -1
            return value

        scored = [(score(rate), rate) for rate in candidates]
        scored = [entry for entry in scored if entry[0] >= 0]
        if not scored:
            return self.browse()
        scored.sort(key=lambda entry: (entry[0], -entry[1].sequence), reverse=True)
        return scored[0][1]


class DwOverheadRule(models.Model):
    _name = "dw.overhead.rule"
    _description = "Overhead Absorption Rule"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    family_id = fields.Many2one("dw.product.family", string="Product Family")
    method = fields.Selection(
        [
            ("percent_material", "% of Material Cost"),
            ("percent_labor", "% of Labour Cost"),
            ("percent_direct", "% of Direct Cost"),
            ("per_hour", "Amount per Hour"),
            ("fixed", "Fixed Amount"),
            ("per_kg", "Amount per Kilogram"),
            ("per_unit", "Amount per Unit"),
            ("per_m2", "Amount per m2"),
            ("percent_order_value", "% of Manufacturing Order Value"),
        ],
        required=True,
        default="percent_direct",
    )
    rate = fields.Float(string="Rate / Percentage", default=0.0)
    date_start = fields.Date(string="Valid From")
    date_end = fields.Date(string="Valid To")
    note = fields.Text(translate=True)

    def _compute_amount(self, item, material_cost=0.0, labor_cost=0.0, direct_cost=0.0,
                        hours=0.0, order_value=0.0):
        """Absorbed overhead for one manufacturing item / order."""
        self.ensure_one()
        rate = self.rate or 0.0
        if self.method == "percent_material":
            return material_cost * rate / 100.0
        if self.method == "percent_labor":
            return labor_cost * rate / 100.0
        if self.method == "percent_direct":
            return direct_cost * rate / 100.0
        if self.method == "per_hour":
            return hours * rate
        if self.method == "fixed":
            return rate
        if self.method == "per_kg":
            weight = getattr(item, "planned_weight_kg", 0.0) or getattr(item, "theoretical_weight_kg", 0.0)
            return weight * rate
        if self.method == "per_unit":
            return (getattr(item, "quantity", 0.0) or 0.0) * rate
        if self.method == "per_m2":
            area = (getattr(item, "area_m2", 0.0) or 0.0) * (getattr(item, "quantity", 1.0) or 1.0)
            return area * rate
        if self.method == "percent_order_value":
            return order_value * rate / 100.0
        return 0.0

    @api.model
    def _find_rule(self, company, family=None, date=None):
        date = date or fields.Date.context_today(self)
        company_id = company.id if company else self.env.company.id
        domain = [
            ("active", "=", True),
            ("company_id", "=", company_id),
            "|", ("date_start", "=", False), ("date_start", "<=", date),
            "|", ("date_end", "=", False), ("date_end", ">=", date),
        ]
        if family:
            rule = self.search(domain + [("family_id", "=", family.id)], limit=1)
            if rule:
                return rule
        return self.search(domain + [("family_id", "=", False)], limit=1)
