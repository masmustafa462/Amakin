# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class EmployeeCustodySettlementLine(models.Model):
    """Detail line for an expense settlement."""

    _name = "employee.custody.settlement.line"
    _description = "Custody Settlement Line"
    _inherit = ["analytic.mixin"]
    _order = "settlement_id, sequence, id"

    settlement_id = fields.Many2one(
        "employee.custody.settlement",
        string="التسوية",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(string="البيان")
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company.id,
        index=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id.id,
    )
    account_id = fields.Many2one(
        "account.account",
        string="حساب المصروف",
        required=True,
        check_company=True,
    )
    amount = fields.Monetary(
        string="المبلغ",
        currency_field="currency_id",
        required=True,
    )
    tax_id = fields.Many2one(
        "account.tax",
        string="الضريبة",
        domain="[('type_tax_use', '=', 'purchase')]",
        check_company=True,
    )
    tax_amount = fields.Monetary(
        string="مبلغ الضريبة",
        currency_field="currency_id",
        compute="_compute_tax_amount",
        store=True,
    )
    amount_untaxed = fields.Monetary(
        string="المبلغ بدون ضريبة",
        currency_field="currency_id",
        compute="_compute_tax_amount",
        store=True,
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ctx = self.env.context
        if "company_id" in fields_list and not res.get("company_id"):
            res["company_id"] = ctx.get("default_company_id") or self.env.company.id
        if "currency_id" in fields_list and not res.get("currency_id"):
            res["currency_id"] = (
                ctx.get("default_currency_id")
                or self.env.company.currency_id.id
            )
        return res

    @api.onchange("settlement_id")
    def _onchange_settlement_id(self):
        for line in self:
            if line.settlement_id:
                line.company_id = line.settlement_id.company_id
                line.currency_id = line.settlement_id.currency_id

    @api.depends("amount", "tax_id", "currency_id")
    def _compute_tax_amount(self):
        for line in self:
            if line.tax_id and line.amount and line.currency_id:
                taxes_res = line.tax_id.compute_all(
                    line.amount,
                    currency=line.currency_id,
                    quantity=1.0,
                    product=False,
                    partner=False,
                    is_refund=False,
                )
                line.amount_untaxed = taxes_res.get("total_excluded", line.amount)
                line.tax_amount = sum(
                    t.get("amount", 0.0) for t in taxes_res.get("taxes", [])
                )
            else:
                line.amount_untaxed = line.amount or 0.0
                line.tax_amount = 0.0

    @api.constrains("amount")
    def _check_amount_positive(self):
        for line in self:
            if (line.amount or 0.0) <= 0:
                raise ValidationError(_(
                    "مبلغ سطر التسوية "
                    "يجب أن يكون أكبر من صفر."
                ))
