# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare


SETTLEMENT_KINDS = [
    ("expense", "مصروف (Expense)"),
    ("return", "إرجاع نقدي (Cash Return)"),
    ("salary", "خصم من الراتب (Salary Deduction)"),
    ("loss", "فقد / تلف (Loss / Damage)"),
    ("over_settlement", "تجاوز تسوية (Over-settlement)"),
    ("due_reconciliation", "تسوية مستحق الموظف (Employee Due Reconciliation)"),
]


class EmployeeCustodySettlement(models.Model):
    """A single settlement transaction against a custody.

    States:
        draft  — editable, no move posted
        posted — move posted, custody balance updated
        cancelled — move reversed and settlement closed
    """

    _name = "employee.custody.settlement"
    _description = "Custody Settlement | تسوية العهدة"
    _inherit = ["mail.thread", "mail.activity.mixin", "analytic.mixin"]
    _order = "settlement_date desc, id desc"
    _check_company_auto = True

    name = fields.Char(
        string="الرقم",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("جديد"),
        tracking=True,
    )
    custody_id = fields.Many2one(
        "employee.custody",
        string="العهدة",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
        check_company=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        related="custody_id.employee_id",
        store=True,
        index=True,
    )
    custody_kind = fields.Selection(
        related="custody_id.custody_kind",
        store=True,
    )

    settlement_kind = fields.Selection(
        SETTLEMENT_KINDS,
        string="نوع التسوية",
        required=True,
        default="expense",
        tracking=True,
    )

    settlement_date = fields.Date(
        string="تاريخ التسوية",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )

    state = fields.Selection(
        [
            ("draft", "مسودة"),
            ("posted", "مرحلة"),
            ("cancelled", "ملغاة"),
        ],
        default="draft",
        required=True,
        tracking=True,
        copy=False,
        index=True,
    )

    # Financial ------------------------------------------------------------
    amount = fields.Monetary(
        string="المبلغ",
        currency_field="currency_id",
        tracking=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="custody_id.currency_id",
        store=True,
    )

    # Material -------------------------------------------------------------
    returned_quantity = fields.Float(
        string="الكمية المرتجعة",
        digits="Product Unit",
        tracking=True,
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

    # Accounting -----------------------------------------------------------
    expense_account_id = fields.Many2one(
        "account.account",
        string="حساب المصروف",
        domain="[('company_ids', 'in', company_id)]",
    )
    cash_account_id = fields.Many2one(
        "account.account",
        string="حساب النقدية",
        domain="[('company_ids', 'in', company_id)]",
    )
    counterpart_account_id = fields.Many2one(
        "account.account",
        string="الحساب المقابل",
        domain="[('company_ids', 'in', company_id)]",
        help="يُحدد تلقائياً بناءً على نوع التسوية (مصروف/خصم راتب/فقد/إرجاع).",
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
    # analytic_distribution is provided by the analytic.mixin inherited above.

    move_id = fields.Many2one(
        "account.move",
        string="القيد اليومي",
        readonly=True,
        copy=False,
    )

    # Set by the over-settlement / auto-reconciliation paths so the
    # standard 2-leg ``_prepare_move_vals`` is skipped and the
    # pre-built combined move is used instead.
    is_externally_posted = fields.Boolean(
        string="قيد محاسبي خارجي",
        readonly=True,
        copy=False,
        help="إذا كان صحيحاً، تم بناء القيد المحاسبي خارج التسوية "
             "(قيد مدمج للتسوية بتجاوز / تسوية مستحق تلقائية).",
    )
    full_expense_amount = fields.Monetary(
        string="إجمالي المصروف",
        currency_field="currency_id",
        readonly=True,
        copy=False,
        help="في حالة التسوية بتجاوز: إجمالي المصروف المسجَّل على حساب "
             "المصروف بالكامل، حتى لو كان أكبر من رصيد العهدة.",
    )
    employee_due_amount = fields.Monetary(
        string="مستحق الموظف",
        currency_field="currency_id",
        readonly=True,
        copy=False,
        help="في حالة التسوية بتجاوز: الفرق المسجَّل كمستحق للموظف.",
    )

    description = fields.Char(string="البيان", tracking=True)
    notes = fields.Text(string="الملاحظات")

    line_ids = fields.One2many(
        "employee.custody.settlement.line",
        "settlement_id",
        string="أسطر التسوية",
        copy=True,
    )
    line_total = fields.Monetary(
        string="إجمالي الأسطر",
        compute="_compute_line_total",
        store=True,
        currency_field="currency_id",
    )

    company_id = fields.Many2one(
        "res.company",
        related="custody_id.company_id",
        store=True,
        index=True,
    )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("جديد")) == _("جديد"):
                seq = self.env["ir.sequence"].next_by_code("employee.custody.settlement")
                vals["name"] = seq or _("جديد")
        return super().create(vals_list)

    def unlink(self):
        for rec in self:
            if rec.state == "posted":
                raise UserError(_("لا يمكن حذف تسوية مرحلة. قم بإلغائها أولاً."))
        return super().unlink()

    @api.depends("line_ids.amount")
    def _compute_line_total(self):
        for rec in self:
            rec.line_total = sum(l.amount for l in rec.line_ids)

    # ------------------------------------------------------------------
    # CONSTRAINTS
    # ------------------------------------------------------------------
    @api.constrains("amount", "returned_quantity", "custody_id", "settlement_kind", "state")
    def _check_values(self):
        for rec in self:
            if rec.state == "cancelled":
                continue
            if rec.custody_kind == "financial":
                effective_amount = rec.amount
                if rec.settlement_kind == "expense" and rec.line_ids:
                    effective_amount = sum(l.amount for l in rec.line_ids)
                if (effective_amount or 0.0) <= 0:
                    raise ValidationError(_("مبلغ التسوية يجب أن يكون أكبر من صفر."))
                # No over-settlement guard.
                # ``over_settlement`` settlement records reduce the custody
                # by exactly the original balance (3-leg move handles the
                # excess on the Employee Due side), so they are bounded.
                # ``due_reconciliation`` records are auto-generated and
                # always honor the parent custody amount by construction.
                other_settled = sum(
                    s.amount for s in rec.custody_id.settlement_ids
                    if s.state == "posted" and s.id != rec.id
                )
                projected = other_settled + effective_amount
                if float_compare(
                    projected, rec.custody_id.amount,
                    precision_rounding=rec.currency_id.rounding or 0.01,
                ) > 0:
                    raise ValidationError(_(
                        "مبلغ التسوية يتجاوز رصيد العهدة. "
                        "الرصيد المتبقي = %(bal)s"
                    ) % {"bal": rec.custody_id.balance_amount})
            else:  # material
                if (rec.returned_quantity or 0.0) <= 0:
                    raise ValidationError(_("كمية الإرجاع يجب أن تكون أكبر من صفر."))
                other_returned = sum(
                    s.returned_quantity for s in rec.custody_id.settlement_ids
                    if s.state == "posted" and s.id != rec.id
                )
                projected = other_returned + rec.returned_quantity
                if projected > rec.custody_id.quantity:
                    raise ValidationError(_(
                        "الكمية المرتجعة تتجاوز الكمية الأصلية للعهدة."
                    ))

    # ------------------------------------------------------------------
    # ONCHANGE
    # ------------------------------------------------------------------
    @api.onchange("settlement_kind", "custody_id")
    def _onchange_settlement_kind(self):
        if not self.custody_id:
            return
        custody = self.custody_id
        company = custody.company_id
        ctype = custody.custody_type_id
        # Journal
        self.journal_id = (
            custody.journal_id or ctype.journal_id or company.custody_default_journal_id
        )
        # Cash account
        self.cash_account_id = (
            custody.cash_account_id or ctype.cash_account_id or company.custody_cash_account_id
        )
        # Counterpart by kind
        counterpart_map = {
            "expense": ctype.expense_account_id or company.custody_expense_account_id,
            "return": custody.cash_account_id or ctype.cash_account_id or company.custody_cash_account_id,
            "salary": ctype.salary_deduction_account_id or company.custody_salary_deduction_account_id,
            "loss": ctype.loss_account_id or company.custody_loss_account_id,
        }
        self.counterpart_account_id = counterpart_map.get(self.settlement_kind) or False

    # ------------------------------------------------------------------
    # ACCOUNTING
    # ------------------------------------------------------------------
    def _build_debit_commands(self, account, amount, tax, description, narration,
                              analytic_distribution):
        """Return [(0, 0, vals), ...] for one debit slot, splitting tax if any.

        ``amount`` is treated as tax-inclusive when ``tax`` is provided.
        Returns a tuple ``(commands, total_debit_amount)``.
        """
        self.ensure_one()
        commands = []
        if not tax:
            commands.append((0, 0, {
                "name": description or narration,
                "account_id": account.id,
                "debit": amount,
                "credit": 0.0,
                "analytic_distribution": analytic_distribution,
            }))
            return commands, amount
        custody = self.custody_id
        taxes_res = tax.compute_all(
            amount,
            currency=self.currency_id,
            quantity=1.0,
            product=False,
            partner=custody.employee_id.work_contact_id or False,
            is_refund=False,
        )
        base_amount = taxes_res.get("total_excluded", amount)
        commands.append((0, 0, {
            "name": description or narration,
            "account_id": account.id,
            "debit": base_amount,
            "credit": 0.0,
            "analytic_distribution": analytic_distribution,
            "tax_ids": [(6, 0, [tax.id])],
        }))
        for tax_vals in taxes_res.get("taxes", []):
            tax_account_id = (
                tax_vals.get("account_id")
                or tax.invoice_repartition_line_ids.filtered(
                    lambda r: r.account_id
                )[:1].account_id.id
            )
            if not tax_account_id:
                raise UserError(_(
                    "حساب الضريبة غير محدد للضريبة %s. "
                    "يرجى ضبط حساب الضريبة في إعدادات الضريبة."
                ) % tax.display_name)
            commands.append((0, 0, {
                "name": tax_vals.get("name") or tax.name,
                "account_id": tax_account_id,
                "debit": tax_vals.get("amount", 0.0),
                "credit": 0.0,
                "tax_repartition_line_id": tax_vals.get("tax_repartition_line_id"),
                "tax_base_amount": tax_vals.get("base", 0.0),
                "analytic_distribution": analytic_distribution,
            }))
        return commands, amount

    def _prepare_move_vals(self):
        """Build the accounting entry for the settlement.

        Patterns:
          - expense (single)  : Dr Expense | Cr Custody
          - expense (lines)   : Dr Acc1, Dr Acc2, ... | Cr Custody (sum)
          - return            : Dr Cash    | Cr Custody
          - salary            : Dr Payroll | Cr Custody
          - loss              : Dr Loss    | Cr Custody

        When a tax is set on the settlement (header) or on a line, the
        entered amount is treated as tax-inclusive and split via
        ``account.tax.compute_all`` into a base line + tax line(s).
        """
        self.ensure_one()
        custody = self.custody_id
        custody_acc = custody._resolve_account("custody")
        journal = self.journal_id or custody._resolve_account("journal")

        if not (journal and custody_acc):
            raise UserError(_(
                "الإعدادات المحاسبية غير مكتملة لتسجيل التسوية. "
                "تأكد من اليومية وحساب العهدة."
            ))

        analytic_distribution = self.analytic_distribution or custody.analytic_distribution
        narration = _("تسوية عهدة %(name)s / %(kind)s") % {
            "name": custody.name,
            "kind": dict(SETTLEMENT_KINDS).get(self.settlement_kind, ""),
        }
        partner_id = False
        if custody.employee_id.work_contact_id:
            partner_id = custody.employee_id.work_contact_id.id

        line_commands = []
        total_debit = 0.0

        use_lines = self.settlement_kind == "expense" and self.line_ids
        if use_lines:
            for ln in self.line_ids:
                if not ln.account_id:
                    raise UserError(_("حدد حساباً لكل سطر مصروف."))
                cmds, ln_total = self._build_debit_commands(
                    account=ln.account_id,
                    amount=ln.amount,
                    tax=ln.tax_id,
                    description=ln.name,
                    narration=narration,
                    analytic_distribution=ln.analytic_distribution or analytic_distribution,
                )
                line_commands.extend(cmds)
                total_debit += ln_total
        else:
            if not self.counterpart_account_id:
                raise UserError(_(
                    "الإعدادات المحاسبية غير مكتملة لتسجيل التسوية. "
                    "تأكد من الحساب المقابل."
                ))
            cmds, ln_total = self._build_debit_commands(
                account=self.counterpart_account_id,
                amount=self.amount,
                tax=self.tax_id,
                description=self.description,
                narration=narration,
                analytic_distribution=analytic_distribution,
            )
            line_commands.extend(cmds)
            total_debit += ln_total

        credit_line = {
            "name": self.description or narration,
            "account_id": custody_acc.id,
            "partner_id": partner_id,
            "debit": 0.0,
            "credit": total_debit,
        }
        line_commands.append((0, 0, credit_line))

        return {
            "journal_id": journal.id,
            "date": self.settlement_date,
            "ref": self.name,
            "move_type": "entry",
            "company_id": custody.company_id.id,
            "custody_id": custody.id,
            "narration": narration,
            "line_ids": line_commands,
        }
    def action_post(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("التسوية ليست في حالة مسودة."))
            if rec.custody_id.state not in ("issued", "partial"):
                raise UserError(_("لا يمكن ترحيل تسوية إلا إذا كانت العهدة مصروفة."))
            # An externally-posted record (over-settlement / due-reconciliation)
            # already has its account.move attached -- skip _prepare_move_vals.
            if rec.is_externally_posted:
                if rec.move_id and rec.move_id.state != "posted":
                    rec.move_id.action_post()
            elif rec.custody_kind == "financial" and rec.custody_id._accounting_enabled():
                move = self.env["account.move"].create(rec._prepare_move_vals())
                move.action_post()
                rec.move_id = move.id
            rec.state = "posted"
            rec.message_post(body=_("تم ترحيل التسوية."))
            rec.custody_id._update_state_from_settlements()
        return True

    def _post_with_external_move(self, move_vals):
        """Post the settlement using a pre-built combined move.

        Used by the over-settlement workflow (3-leg combined move
        Dr Expense / Cr Custody / Cr Employee Due) and by the
        auto due-reconciliation (Dr Employee Due / Cr Custody).

        The standard ``_prepare_move_vals`` is intentionally bypassed so
        non-standard move shapes can be expressed without polluting the
        regular settlement template.
        """
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("التسوية ليست في حالة مسودة."))
        move = self.env["account.move"].create(move_vals)
        move.action_post()
        self.write({
            "move_id": move.id,
            "is_externally_posted": True,
        })
        # Reuse the standard post path for state + chatter + balance update.
        self.action_post()
        return move

    def action_cancel(self):
        for rec in self:
            if rec.state == "cancelled":
                continue
            if rec.move_id and rec.move_id.state == "posted":
                reverse = rec.move_id._reverse_moves(
                    default_values_list=[{
                        "date": fields.Date.context_today(self),
                        "ref": _("عكس %s") % rec.name,
                    }],
                    cancel=True,
                )
                reverse.write({"custody_id": rec.custody_id.id})
            rec.state = "cancelled"
            rec.message_post(body=_("تم إلغاء التسوية."))
            rec.custody_id._update_state_from_settlements()
        return True

    def action_draft(self):
        for rec in self:
            if rec.state != "cancelled":
                raise UserError(_("يمكن إعادة التسويات الملغاة فقط إلى المسودة."))
            rec.state = "draft"
        return True
