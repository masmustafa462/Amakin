# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    custody_ids = fields.One2many(
        "employee.custody",
        "employee_id",
        string="العهد",
    )
    custody_count = fields.Integer(
        string="عدد العهد",
        compute="_compute_custody_totals",
    )
    open_custody_count = fields.Integer(
        string="العهد المفتوحة",
        compute="_compute_custody_totals",
    )
    custody_total_balance = fields.Monetary(
        string="إجمالي الرصيد المفتوح",
        compute="_compute_custody_totals",
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        readonly=True,
    )
    has_overdue_custody = fields.Boolean(
        string="لديه عهد متأخرة",
        compute="_compute_custody_totals",
        search="_search_has_overdue_custody",
    )

    @api.depends("custody_ids", "custody_ids.state", "custody_ids.balance_amount", "custody_ids.is_overdue")
    def _compute_custody_totals(self):
        for emp in self:
            open_custodies = emp.custody_ids.filtered(
                lambda c: c.state in ("issued", "partial")
            )
            emp.custody_count = len(emp.custody_ids)
            emp.open_custody_count = len(open_custodies)
            emp.custody_total_balance = sum(open_custodies.mapped("balance_amount"))
            emp.has_overdue_custody = any(c.is_overdue for c in open_custodies)

    def _search_has_overdue_custody(self, operator, value):
        today = fields.Date.context_today(self)
        if operator not in ("=", "!="):
            return []
        positive = (operator == "=" and value) or (operator == "!=" and not value)
        overdue_emps = self.env["employee.custody"].search([
            ("state", "in", ("issued", "partial")),
            ("expected_return_date", "<", today),
            ("expected_return_date", "!=", False),
        ]).mapped("employee_id")
        op = "in" if positive else "not in"
        return [("id", op, overdue_emps.ids)]

    def action_view_custodies(self):
        self.ensure_one()
        return {
            "name": _("عهد %s") % self.name,
            "type": "ir.actions.act_window",
            "res_model": "employee.custody",
            "view_mode": "list,form,pivot,graph",
            "domain": [("employee_id", "=", self.id)],
            "context": {
                "default_employee_id": self.id,
                "search_default_group_state": 1,
            },
        }
