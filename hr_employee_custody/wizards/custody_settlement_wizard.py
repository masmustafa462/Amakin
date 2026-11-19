# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CustodySettlementWizard(models.TransientModel):
    """Wizard to record a settlement against a custody.

    Handles all four settlement modes in a single, unified flow:

        expense : the amount was spent and must be expensed.
        return  : the employee returned cash to the company.
        salary  : the outstanding balance will be deducted from payroll.
        loss    : the amount is recognized as loss/employee receivable.
    """

    _name = "custody.settlement.wizard"
    _inherit = ["analytic.mixin"]
    _description = "Custody Settlement Wizard"

    custody_id = fields.Many2one(
        "employee.custody",
        string="العهدة",
        required=True,
    )
    custody_kind = fields.Selection(
        related="custody_id.custody_kind",
        readonly=True,
    )
    settlement_kind = fields.Selection(
        [
            ("expense", "مصروف"),
            ("return", "إرجاع نقدي"),
            ("salary", "خصم من الراتب"),
            ("loss", "فقد / تلف"),
        ],
        string="نوع التسوية",
        required=True,
        default="expense",
    )
    settlement_date = fields.Date(
        string="تاريخ التسوية",
        required=True,
        default=fields.Date.context_today,
    )
    amount = fields.Monetary(
        string="المبلغ",
        currency_field="currency_id",
    )
    returned_quantity = fields.Float(
        string="الكمية المرتجعة",
        digits="Product Unit",
    )
    return_condition = fields.Selection(
        [
            ("good", "سليمة"),
            ("fair", "مستعملة"),
            ("damaged", "تالفة"),
            ("lost", "مفقودة"),
        ],
        string="حالة الإرجاع",
        default="good",
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="custody_id.currency_id",
    )
    balance_amount = fields.Monetary(
        string="الرصيد الحالي",
        related="custody_id.balance_amount",
    )
    remaining_quantity = fields.Float(
        string="الكمية المتبقية",
        related="custody_id.remaining_quantity",
    )
    expense_account_id = fields.Many2one(
        "account.account",
        string="حساب المصروف",
        domain="[('company_ids', 'in', company_id)]",
    )
    counterpart_account_id = fields.Many2one(
        "account.account",
        string="الحساب المقابل",
        domain="[('company_ids', 'in', company_id)]",
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="اليومية",
        domain="[('company_id', '=', company_id)]",
    )
    tax_id = fields.Many2one(
        "account.tax",
        string="الضريبة",
        domain="[('company_id', '=', company_id), ('type_tax_use', '=', 'purchase')]",
        help="ضريبة اختيارية تُحتسب من المبلغ المُدخل (شامل الضريبة) "
             "وتُضاف كسطر منفصل في القيد المحاسبي.",
    )
    line_ids = fields.One2many(
        "custody.settlement.wizard.line",
        "wizard_id",
        string="أسطر التسوية",
    )
    line_total = fields.Monetary(
        string="إجمالي الأسطر",
        compute="_compute_line_total",
        currency_field="currency_id",
    )
    # analytic_distribution is provided by the analytic.mixin inherited above.
    description = fields.Char(string="البيان")
    attachment_ids = fields.Many2many(
        "ir.attachment",
        string="المرفقات",
    )
    company_id = fields.Many2one(
        related="custody_id.company_id",
        store=False,
    )

    @api.onchange("settlement_kind", "custody_id")
    def _onchange_defaults(self):
        if not self.custody_id:
            return
        custody = self.custody_id
        company = custody.company_id
        ctype = custody.custody_type_id

        self.journal_id = (
            custody.journal_id or ctype.journal_id or company.custody_default_journal_id
        )
        if self.custody_kind == "financial":
            self.amount = custody.balance_amount
        else:
            self.returned_quantity = custody.remaining_quantity

        counterpart_map = {
            "expense": ctype.expense_account_id or company.custody_expense_account_id,
            "return": custody.cash_account_id or ctype.cash_account_id or company.custody_cash_account_id,
            "salary": ctype.salary_deduction_account_id or company.custody_salary_deduction_account_id,
            "loss": ctype.loss_account_id or company.custody_loss_account_id,
        }
        self.counterpart_account_id = counterpart_map.get(self.settlement_kind) or False
        self.expense_account_id = self.counterpart_account_id

    @api.depends("line_ids.amount")
    def _compute_line_total(self):
        for rec in self:
            rec.line_total = sum(l.amount for l in rec.line_ids)

    def action_confirm(self):
        self.ensure_one()
        custody = self.custody_id
        if custody.state not in ("issued", "partial"):
            raise UserError(_("العهدة ليست في حالة تسمح بالتسوية."))

        use_lines = (
            self.custody_kind == "financial"
            and self.settlement_kind == "expense"
            and self.line_ids
        )

        # Compute the actual settlement amount (lines win over single amount).
        if use_lines:
            settlement_amount = sum(self.line_ids.mapped("amount"))
        else:
            settlement_amount = self.amount or 0.0

        # Overage detection: only for financial expense settlements.
        # The new custody is defaulted to the FULL settlement amount
        # (per spec); ``default_get`` on the overage wizard takes care
        # of that. We deliberately do NOT pass a
        # ``default_new_custody_amount`` override here.
        if (self.custody_kind == "financial"
                and self.settlement_kind == "expense"
                and settlement_amount > (custody.balance_amount or 0.0)
                and not self.env.context.get("overage_confirmed")):
            return {
                "name": _("تنبيه: مبلغ التسوية أكبر من رصيد العهدة"),
                "type": "ir.actions.act_window",
                "res_model": "custody.settlement.overage.wizard",
                "view_mode": "form",
                "target": "new",
                "context": {
                    "default_settlement_wizard_id": self.id,
                    "default_custody_id": custody.id,
                    "default_original_balance": custody.balance_amount,
                    "default_settlement_amount": settlement_amount,
                    "default_difference_amount":
                        settlement_amount - custody.balance_amount,
                },
            }

        vals = {
            "custody_id": custody.id,
            "settlement_kind": self.settlement_kind,
            "settlement_date": self.settlement_date,
            "description": self.description,
            "journal_id": self.journal_id.id if self.journal_id else False,
            "counterpart_account_id":
                self.counterpart_account_id.id if self.counterpart_account_id else False,
            "expense_account_id":
                self.expense_account_id.id if self.expense_account_id else False,
            "tax_id": self.tax_id.id if self.tax_id else False,
            "analytic_distribution": self.analytic_distribution,
        }

        if self.custody_kind == "financial":
            if use_lines:
                line_cmds = []
                total = 0.0
                for ln in self.line_ids:
                    if not ln.account_id:
                        raise UserError(_("حدد حساباً لكل سطر مصروف."))
                    if not ln.amount or ln.amount <= 0:
                        raise UserError(_("أدخل مبلغاً موجباً لكل سطر."))
                    line_cmds.append((0, 0, {
                        "name": ln.name,
                        "sequence": ln.sequence,
                        "account_id": ln.account_id.id,
                        "amount": ln.amount,
                        "tax_id": ln.tax_id.id if ln.tax_id else False,
                        "analytic_distribution": ln.analytic_distribution,
                    }))
                    total += ln.amount
                vals["line_ids"] = line_cmds
                vals["amount"] = total
            else:
                # Capped amount path: when overage_confirmed, use balance.
                if self.env.context.get("overage_confirmed"):
                    capped = self.env.context.get("overage_capped_amount")
                    if capped is None:
                        capped = custody.balance_amount
                    if capped <= 0:
                        raise UserError(_("لا يوجد رصيد لتسويته."))
                    vals["amount"] = capped
                else:
                    if not self.amount or self.amount <= 0:
                        raise UserError(_("أدخل مبلغ التسوية."))
                    vals["amount"] = self.amount
        else:
            if not self.returned_quantity or self.returned_quantity <= 0:
                raise UserError(_("أدخل الكمية المرتجعة."))
            vals["returned_quantity"] = self.returned_quantity
            vals["return_condition"] = self.return_condition

        settlement = self.env["employee.custody.settlement"].create(vals)
        for att in self.attachment_ids:
            att.copy({
                "res_model": "employee.custody.settlement",
                "res_id": settlement.id,
            })
        settlement.action_post()

        return {
            "name": _("التسوية"),
            "type": "ir.actions.act_window",
            "res_model": "employee.custody.settlement",
            "res_id": settlement.id,
            "view_mode": "form",
            "target": "current",
        }

class CustodySettlementWizardLine(models.TransientModel):
    """Transient line within the settlement wizard for expense itemization."""

    _name = "custody.settlement.wizard.line"
    _description = "Custody Settlement Wizard Line"
    _inherit = ["analytic.mixin"]
    _order = "sequence, id"

    wizard_id = fields.Many2one(
        "custody.settlement.wizard",
        ondelete="cascade",
        required=True,
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(string="البيان")
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company.id,
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
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ctx = self.env.context
        # Use context defaults from parent wizard if provided, else env company.
        if "company_id" in fields_list and not res.get("company_id"):
            res["company_id"] = ctx.get("default_company_id") or self.env.company.id
        if "currency_id" in fields_list and not res.get("currency_id"):
            res["currency_id"] = (
                ctx.get("default_currency_id")
                or self.env.company.currency_id.id
            )
        return res

    @api.onchange("wizard_id")
    def _onchange_wizard_id(self):
        for ln in self:
            if ln.wizard_id:
                ln.company_id = ln.wizard_id.company_id
                ln.currency_id = ln.wizard_id.currency_id

    @api.depends("amount", "tax_id", "currency_id")
    def _compute_tax_amount(self):
        for ln in self:
            if ln.tax_id and ln.amount and ln.currency_id:
                taxes_res = ln.tax_id.compute_all(
                    ln.amount,
                    currency=ln.currency_id,
                    quantity=1.0,
                    product=False,
                    partner=False,
                    is_refund=False,
                )
                ln.tax_amount = sum(
                    t.get("amount", 0.0) for t in taxes_res.get("taxes", [])
                )
            else:
                ln.tax_amount = 0.0
