# -*- coding: utf-8 -*-
"""Over-settlement wizard.

When a settlement amount exceeds the parent custody's current balance,
this wizard runs and produces ONE combined, balanced journal entry:

    Dr  Expense Account(s)              -- FULL settlement amount
    Cr  Employee Custody Account        -- original custody balance
    Cr  Employee Due / Payable Account  -- the difference

After posting that move, a NEW custody request is created -- with the
**FULL settlement amount** as its default disbursement amount (NOT just
the difference). The user may edit it before clicking Issue/Disburse.

When the new custody is finally disbursed, ``_auto_settle_employee_due``
on ``employee.custody`` posts a second, automatic move:

    Dr  Employee Due Account            -- original_difference_amount only
    Cr  Employee Custody Account        -- original_difference_amount only

That move reduces the new custody's balance by the frozen difference
amount and reconciles against the Employee Due credit leg of the
combined settlement move (when the GL account is reconcilable).

Net effect (using the canonical 5,000 / 6,000 example):

* Parent custody     : closed, residual = 0
* Expense account    : Dr 6,000 (the FULL expense, never split)
* Employee Due       : zeroed after auto-reconcile
* New custody amount : 6,000 (user can edit upward)
* Active balance     : 6,000 - 1,000 = 5,000 available for future settle
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class CustodySettlementOverageWizard(models.TransientModel):
    _name = "custody.settlement.overage.wizard"
    _description = "Custody Settlement Overage Wizard"

    # ------------------------------------------------------------------
    # Linkage
    # ------------------------------------------------------------------
    settlement_wizard_id = fields.Many2one(
        "custody.settlement.wizard",
        string="معالج التسوية",
        required=True,
        ondelete="cascade",
    )
    custody_id = fields.Many2one(
        "employee.custody",
        string="العهدة الأصلية",
        required=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="custody_id.currency_id",
        readonly=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        related="custody_id.employee_id",
        readonly=True,
    )
    custody_type_id = fields.Many2one(
        "employee.custody.type",
        related="custody_id.custody_type_id",
        readonly=True,
    )

    # ------------------------------------------------------------------
    # Amount summary (read-only)
    # ------------------------------------------------------------------
    original_balance = fields.Monetary(
        string="رصيد العهدة الحالي",
        currency_field="currency_id",
        readonly=True,
    )
    settlement_amount = fields.Monetary(
        string="إجمالي المصروف المعتمد",
        currency_field="currency_id",
        readonly=True,
        help="القيمة الكاملة التي ستُسجَّل على حساب المصروف -- لا يتم تقسيمها.",
    )
    difference_amount = fields.Monetary(
        string="فرق التسوية (مستحق للموظف)",
        currency_field="currency_id",
        readonly=True,
    )

    # ------------------------------------------------------------------
    # New custody — default = FULL settlement amount, editable upward.
    # ------------------------------------------------------------------
    new_custody_amount = fields.Monetary(
        string="مبلغ العهدة الجديدة",
        currency_field="currency_id",
        help="الافتراضي = إجمالي المصروف. يمكن تعديله قبل الصرف. "
             "بعد الصرف ستتم تسوية فرق التسوية تلقائياً.",
    )
    expected_active_balance = fields.Monetary(
        string="الرصيد الفعّال المتوقع بعد الصرف",
        currency_field="currency_id",
        compute="_compute_expected_active_balance",
        help="مبلغ العهدة الجديدة − الفرق المُجمَّد (يُحتسب تلقائياً عند الصرف).",
    )
    has_expense_lines = fields.Boolean(
        string="يحوي أسطر مصروف",
        compute="_compute_has_expense_lines",
    )

    # ==================================================================
    # COMPUTES
    # ==================================================================
    @api.depends("settlement_wizard_id.line_ids")
    def _compute_has_expense_lines(self):
        for rec in self:
            rec.has_expense_lines = bool(
                rec.settlement_wizard_id and rec.settlement_wizard_id.line_ids
            )

    @api.depends("new_custody_amount", "difference_amount")
    def _compute_expected_active_balance(self):
        for rec in self:
            rec.expected_active_balance = max(
                (rec.new_custody_amount or 0.0) - (rec.difference_amount or 0.0),
                0.0,
            )

    # ==================================================================
    # CONSTRAINTS
    # ==================================================================
    @api.constrains("new_custody_amount", "difference_amount")
    def _check_new_custody_amount(self):
        for rec in self:
            diff = rec.difference_amount or 0.0
            if (rec.new_custody_amount or 0.0) + 1e-6 < diff:
                raise ValidationError(_(
                    "مبلغ العهدة الجديدة لا يمكن أن يكون أقل من فرق التسوية (%s)، "
                    "وإلا فلن يكون هناك رصيد كافٍ لتسوية مستحق الموظف تلقائياً."
                ) % diff)

    # ==================================================================
    # DEFAULTS
    # ==================================================================
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ctx = self.env.context
        # Default the new custody amount to the FULL settlement amount
        # (the full approved expense), NOT just the difference. The user
        # may still edit it upward; downward is constrained by
        # ``_check_new_custody_amount`` to keep the auto-reconciliation
        # arithmetically sound.
        if "new_custody_amount" in fields_list:
            res["new_custody_amount"] = (
                res.get("settlement_amount")
                or ctx.get("default_settlement_amount")
                or 0.0
            )
        return res

    # ==================================================================
    # CONFIRM
    # ==================================================================
    def action_confirm_overage(self):
        self.ensure_one()
        wizard = self.settlement_wizard_id
        custody = self.custody_id
        if not wizard or not custody:
            raise UserError(_("بيانات غير مكتملة."))

        original_balance = custody.balance_amount or 0.0
        settlement_amount = self.settlement_amount or 0.0
        difference = self.difference_amount or 0.0

        if original_balance <= 0:
            raise UserError(_("لا يوجد رصيد لتسويته على العهدة الأصلية."))
        if settlement_amount <= original_balance:
            raise UserError(_(
                "مبلغ التسوية لا يتجاوز رصيد العهدة -- استخدم تسوية عادية."
            ))
        if difference <= 0:
            raise UserError(_(
                "فرق التسوية غير صحيح."
            ))

        # 1. Build & post the single combined 3-leg move and bind it to
        #    a settlement record on the parent custody.
        self._post_combined_settlement(
            custody, wizard,
            settlement_amount=settlement_amount,
            original_balance=original_balance,
            difference=difference,
        )

        # 2. Create the new custody for the FULL settlement amount as the
        #    default, with the FROZEN difference preserved for the auto
        #    reconciliation that will fire at issue time.
        new_amount = max(self.new_custody_amount or 0.0, settlement_amount)
        new_custody = self._create_pending_custody(
            custody,
            requested=new_amount,
            difference=difference,
            settlement_amount=settlement_amount,
        )
        return self._open_new_custody(new_custody)

    # ==================================================================
    # COMBINED MOVE
    # ==================================================================
    def _post_combined_settlement(self, custody, wizard, settlement_amount,
                                  original_balance, difference):
        """Post the combined 3-leg over-settlement move and bind it.

        Move shape::

            Dr  Expense Account(s)            settlement_amount  (FULL)
            Cr  Employee Custody Account      original_balance
            Cr  Employee Due Account          difference

        The expense side is itemized from wizard.line_ids when present,
        otherwise it is a single debit on the wizard/header expense
        account.

        A single ``employee.custody.settlement`` record is created on
        the parent with ``amount = original_balance`` and
        ``settlement_kind = 'over_settlement'``. Its ``move_id`` points
        to the combined move so the audit chain stays intact.
        """
        journal = self._resolve_journal(wizard, custody)
        custody_acc = self._resolve_custody_account(custody)
        due_acc = self._resolve_employee_due_account(custody)
        if not journal or not custody_acc or not due_acc:
            raise UserError(_(
                "الإعدادات المحاسبية غير مكتملة لتسجيل قيد التسوية بتجاوز:\n"
                "- اليومية\n"
                "- حساب العهدة\n"
                "- حساب مستحقات الموظف\n"
                "راجع إعدادات الشركة أو نوع العهدة."
            ))

        analytic_distribution = (
            wizard.analytic_distribution or custody.analytic_distribution
        )
        partner_id = (
            custody.employee_id.work_contact_id.id
            if custody.employee_id.work_contact_id else False
        )
        narration = _(
            "تسوية بتجاوز رصيد العهدة %(c)s -- إجمالي المصروف %(tot)s "
            "(الرصيد %(bal)s + مستحق الموظف %(diff)s)"
        ) % {
            "c": custody.name,
            "tot": settlement_amount,
            "bal": original_balance,
            "diff": difference,
        }

        # --- DEBIT side: the FULL expense amount, itemized when possible.
        debit_lines = self._build_expense_debit_lines(
            wizard, settlement_amount, narration, analytic_distribution,
        )
        debit_total = sum(cmd[2]["debit"] for cmd in debit_lines)
        # Reconcile against rounding noise from tax computation.
        rounding = (custody.currency_id.rounding or 0.01)
        if abs(debit_total - settlement_amount) > rounding:
            raise UserError(_(
                "إجمالي البنود المدينة (%(d)s) لا يساوي مبلغ المصروف (%(s)s). "
                "تحقق من الأسطر والضرائب."
            ) % {"d": debit_total, "s": settlement_amount})

        # --- CREDIT side: split between Custody (balance) and Due (diff).
        credit_lines = [
            (0, 0, {
                "name": _("إغلاق رصيد العهدة %s") % custody.name,
                "account_id": custody_acc.id,
                "partner_id": partner_id,
                "debit": 0.0,
                "credit": original_balance,
            }),
            (0, 0, {
                "name": _("مستحق للموظف من فرق تسوية العهدة %s") % custody.name,
                "account_id": due_acc.id,
                "partner_id": partner_id,
                "debit": 0.0,
                "credit": difference,
            }),
        ]

        move_vals = {
            "journal_id": journal.id,
            "date": wizard.settlement_date,
            "ref": _("تسوية بتجاوز - %s") % custody.name,
            "move_type": "entry",
            "company_id": custody.company_id.id,
            "custody_id": custody.id,
            "narration": narration,
            "line_ids": debit_lines + credit_lines,
        }

        # Create the settlement record bound to the combined move.
        settlement = self.env["employee.custody.settlement"].create({
            "custody_id": custody.id,
            "settlement_kind": "over_settlement",
            "settlement_date": wizard.settlement_date,
            "description": wizard.description or _("تسوية بتجاوز رصيد العهدة"),
            "journal_id": journal.id,
            "expense_account_id":
                wizard.expense_account_id.id if wizard.expense_account_id else False,
            "counterpart_account_id":
                wizard.counterpart_account_id.id
                if wizard.counterpart_account_id else False,
            "analytic_distribution": analytic_distribution,
            "amount": original_balance,            # custody-side amount
            "full_expense_amount": settlement_amount,
            "employee_due_amount": difference,
        })

        # Persist any attachments from the parent wizard.
        for att in wizard.attachment_ids:
            att.copy({
                "res_model": "employee.custody.settlement",
                "res_id": settlement.id,
            })

        move = settlement._post_with_external_move(move_vals)

        # Cache the combined move on the parent for later reconciliation
        # and the smart button.
        custody.write({"employee_due_move_id": move.id})

        custody.message_post(body=_(
            "تمت تسوية العهدة بالكامل عبر قيد مدمج %(mv)s: "
            "Dr مصروف %(tot)s | Cr عهدة %(bal)s | Cr مستحق موظف %(diff)s."
        ) % {
            "mv": move.name,
            "tot": settlement_amount,
            "bal": original_balance,
            "diff": difference,
        })
        return settlement, move

    def _build_expense_debit_lines(self, wizard, settlement_amount,
                                   narration, analytic_distribution):
        """Build the FULL-expense debit side of the combined move.

        Prefers the wizard's itemized lines (preserves expense-line
        breakdown with optional tax). Falls back to a single debit on
        the wizard/header expense account.

        ``settlement_amount`` -- expected total of the debit lines.
        """
        # Itemized path.
        if wizard.line_ids:
            cmds = []
            for ln in wizard.line_ids:
                if not ln.account_id:
                    raise UserError(_("حدد حساباً لكل سطر مصروف."))
                if not ln.amount or ln.amount <= 0:
                    raise UserError(_("أدخل مبلغاً موجباً لكل سطر."))
                tax = ln.tax_id
                # When a tax is set, expand into base + tax line(s).
                if tax:
                    taxes_res = tax.compute_all(
                        ln.amount,
                        currency=wizard.currency_id,
                        quantity=1.0,
                        product=False,
                        partner=False,
                        is_refund=False,
                    )
                    base_amount = taxes_res.get("total_excluded", ln.amount)
                    cmds.append((0, 0, {
                        "name": ln.name or narration,
                        "account_id": ln.account_id.id,
                        "debit": base_amount,
                        "credit": 0.0,
                        "analytic_distribution":
                            ln.analytic_distribution or analytic_distribution,
                        "tax_ids": [(6, 0, [tax.id])],
                    }))
                    for tx in taxes_res.get("taxes", []):
                        tax_account_id = tx.get("account_id") or (
                            tax.invoice_repartition_line_ids
                                .filtered(lambda r: r.account_id)[:1].account_id.id
                        )
                        if not tax_account_id:
                            raise UserError(_(
                                "حساب الضريبة غير محدد للضريبة %s."
                            ) % tax.display_name)
                        cmds.append((0, 0, {
                            "name": tx.get("name") or tax.name,
                            "account_id": tax_account_id,
                            "debit": tx.get("amount", 0.0),
                            "credit": 0.0,
                            "tax_repartition_line_id": tx.get(
                                "tax_repartition_line_id"
                            ),
                            "tax_base_amount": tx.get("base", 0.0),
                            "analytic_distribution":
                                ln.analytic_distribution or analytic_distribution,
                        }))
                else:
                    cmds.append((0, 0, {
                        "name": ln.name or narration,
                        "account_id": ln.account_id.id,
                        "debit": ln.amount,
                        "credit": 0.0,
                        "analytic_distribution":
                            ln.analytic_distribution or analytic_distribution,
                    }))
            return cmds

        # Single-amount path.
        expense_acc = self._resolve_default_expense_account(wizard, self.custody_id)
        if not expense_acc:
            raise UserError(_(
                "حساب المصروف الافتراضي غير محدد."
            ))
        return [(0, 0, {
            "name": narration,
            "account_id": expense_acc.id,
            "debit": settlement_amount,
            "credit": 0.0,
            "analytic_distribution": analytic_distribution,
        })]

    # ==================================================================
    # NEW CUSTODY (Step 3 / 4)
    # ==================================================================
    def _create_pending_custody(self, custody, requested, difference,
                                settlement_amount):
        """Create the new custody in approved state -- NOT issued.

        ``requested``           -- the editable disbursement amount (default
                                   = settlement_amount, the FULL expense).
        ``difference``          -- frozen amount used by the auto due
                                   settlement at issue time.
        ``settlement_amount``   -- the original full expense (kept for audit).
        """
        new_vals = {
            "employee_id": custody.employee_id.id,
            "custody_type_id": custody.custody_type_id.id,
            "currency_id": custody.currency_id.id,
            "company_id": custody.company_id.id,
            "amount": requested,
            "user_id": self.env.user.id,
            "request_date": fields.Date.context_today(self),
            "parent_custody_id": custody.id,
            "journal_id": custody.journal_id.id if custody.journal_id else False,
            "custody_account_id":
                custody.custody_account_id.id if custody.custody_account_id else False,
            "cash_account_id":
                custody.cash_account_id.id if custody.cash_account_id else False,
            "analytic_distribution": custody.analytic_distribution,
            # Frozen audit fields.
            "over_settlement_difference": difference,
            "employee_due_amount": difference,
            "original_remaining_amount": difference,
            "requested_new_custody_amount": requested,
            "employee_due_move_id": custody.employee_due_move_id.id
                if custody.employee_due_move_id else False,
            "notes": _(
                "طلب عهدة جاهز للصرف -- نتج عن تجاوز تسوية العهدة %(p)s. "
                "إجمالي المصروف المعتمد = %(tot)s. "
                "فرق التسوية المُجمَّد = %(d)s. "
                "بعد الصرف سيُسوَّى الفرق تلقائياً وسيظل الرصيد الفعّال = %(rem)s."
            ) % {
                "p": custody.name,
                "tot": settlement_amount,
                "d": difference,
                "rem": max(requested - difference, 0.0),
            },
        }
        new_custody = self.env["employee.custody"].create(new_vals)
        # Move it to the "approved / ready to disburse" state, but DO NOT
        # auto-issue. The user clicks Issue/Disburse manually.
        new_custody.sudo().action_submit()
        new_custody.sudo().action_approve()
        new_custody.message_post(body=_(
            "تم إنشاء هذا الطلب تلقائياً نتيجة تجاوز تسوية العهدة %(p)s. "
            "إجمالي المصروف %(tot)s، الفرق المُجمَّد %(d)s. "
            "الطلب جاهز للصرف -- يمكن تعديل المبلغ ثم الضغط على زر الصرف. "
            "عند الصرف ستتم تسوية مستحق الموظف تلقائياً بمبلغ %(d)s فقط."
        ) % {
            "p": custody.name,
            "tot": settlement_amount,
            "d": difference,
        })
        custody.message_post(body=_(
            "تم إنشاء طلب عهدة جديد %(n)s بمبلغ %(a)s "
            "(إجمالي المصروف الأصلي %(tot)s، الفرق المُجمَّد %(d)s) "
            "جاهز للصرف."
        ) % {
            "n": new_custody.name,
            "a": requested,
            "tot": settlement_amount,
            "d": difference,
        })
        return new_custody

    # ==================================================================
    # ACCOUNT RESOLUTION HELPERS
    # ==================================================================
    def _resolve_employee_due_account(self, custody):
        company = custody.company_id
        ctype = custody.custody_type_id
        return (
            (ctype and ctype.employee_due_account_id)
            or company.custody_employee_due_account_id
            or False
        )

    def _resolve_default_expense_account(self, wizard, custody):
        company = custody.company_id
        ctype = custody.custody_type_id
        return (
            (wizard.expense_account_id or False)
            or (wizard.counterpart_account_id or False)
            or (ctype and ctype.expense_account_id)
            or company.custody_expense_account_id
            or False
        )

    def _resolve_journal(self, wizard, custody):
        company = custody.company_id
        ctype = custody.custody_type_id
        return (
            (wizard.journal_id or False)
            or (custody.journal_id or False)
            or (ctype and ctype.journal_id)
            or company.custody_default_journal_id
            or False
        )

    def _resolve_custody_account(self, custody):
        company = custody.company_id
        ctype = custody.custody_type_id
        return (
            (custody.custody_account_id or False)
            or (ctype and ctype.custody_account_id)
            or company.custody_account_id
            or False
        )

    # ==================================================================
    # NAVIGATION
    # ==================================================================
    def _open_new_custody(self, new_custody):
        return {
            "type": "ir.actions.act_window",
            "res_model": "employee.custody",
            "res_id": new_custody.id,
            "view_mode": "form",
            "target": "current",
            "name": _("طلب عهدة جديد جاهز للصرف"),
        }


# Kept for ACL / installed-data compatibility; no longer populated.
class CustodySettlementOverageWizardLine(models.TransientModel):
    _name = "custody.settlement.overage.wizard.line"
    _description = "Overage Wizard Line (legacy, unused)"
    _order = "sequence, id"

    wizard_id = fields.Many2one(
        "custody.settlement.overage.wizard",
        ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(string="البيان")
    account_id = fields.Many2one("account.account", string="الحساب")
    currency_id = fields.Many2one("res.currency")
    amount = fields.Monetary(string="المبلغ", currency_field="currency_id")
    tax_id = fields.Many2one("account.tax", string="الضريبة")
    will_move = fields.Boolean(string="ينقل")
    source_line_id = fields.Integer(string="Source Line ID")
