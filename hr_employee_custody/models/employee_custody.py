# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero


CUSTODY_STATES = [
    ("draft", "مسودة"),
    ("submitted", "مقدمة"),
    ("approved", "معتمدة"),
    ("issued", "مصروفة"),
    ("partial", "مسواة جزئياً"),
    ("settled", "مسواة"),
    ("returned", "مرجعة"),
    ("damaged", "تالفة"),
    ("lost", "مفقودة"),
    ("rejected", "مرفوضة"),
    ("cancelled", "ملغاة"),
]

# States in which critical data is locked (no edits by non-admin).
LOCKED_STATES = ("issued", "partial", "settled", "returned", "damaged", "lost", "rejected", "cancelled")

# Fields that become readonly once the custody is issued.
LOCKED_FIELDS = (
    "employee_id",
    "custody_type_id",
    "custody_kind",
    "amount",
    "currency_id",
    "product_id",
    "asset_description",
    "quantity",
    "company_id",
)


class EmployeeCustody(models.Model):
    """Master record for an employee custody.

    Implements the full lifecycle as described in the functional spec:
    request → submit → approve → issue → (partial settlement)* → settle.

    Accounting entries are fully configurable — no account is hardcoded.
    All journal postings flow through :meth:`_post_issue_move` and
    :meth:`_post_settlement_move` which read account configuration in
    the following order of precedence:

        line override  >  custody type  >  company settings

    The model also supports material custody (equipment, tools, vehicles)
    with partial returns, condition tracking and loss/damage handling.
    """

    _name = "employee.custody"
    _description = "Employee Custody | عهدة الموظف"
    _inherit = ["mail.thread", "mail.activity.mixin", "analytic.mixin"]
    _order = "issue_date desc, id desc"
    _rec_name = "name"
    _check_company_auto = True

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------
    name = fields.Char(
        string="الرقم",
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: _("جديد"),
        tracking=True,
        index=True,
    )
    reference = fields.Char(string="المرجع الخارجي", tracking=True)

    state = fields.Selection(
        CUSTODY_STATES,
        string="الحالة",
        default="draft",
        required=True,
        tracking=True,
        copy=False,
        index=True,
    )
    color = fields.Integer(
        string="اللون",
        compute="_compute_color",
    )

    # ------------------------------------------------------------------
    # Parties
    # ------------------------------------------------------------------
    employee_id = fields.Many2one(
        "hr.employee",
        string="الموظف",
        required=True,
        index=True,
        tracking=True,
        check_company=True,
    )
    department_id = fields.Many2one(
        "hr.department",
        string="القسم",
        related="employee_id.department_id",
        store=True,
        index=True,
    )
    job_id = fields.Many2one(
        "hr.job",
        string="الوظيفة",
        related="employee_id.job_id",
        store=True,
    )
    manager_id = fields.Many2one(
        "hr.employee",
        string="المدير المباشر",
        related="employee_id.parent_id",
        store=True,
    )
    user_id = fields.Many2one(
        "res.users",
        string="المسؤول",
        default=lambda self: self.env.user,
        tracking=True,
        check_company=True,
    )

    # ------------------------------------------------------------------
    # Type / Category
    # ------------------------------------------------------------------
    custody_type_id = fields.Many2one(
        "employee.custody.type",
        string="نوع العهدة",
        required=True,
        tracking=True,
        check_company=True,
    )
    custody_kind = fields.Selection(
        [
            ("financial", "مالية"),
            ("material", "عينية"),
        ],
        string="التصنيف",
        related="custody_type_id.custody_kind",
        store=True,
        index=True,
    )
    category_id = fields.Many2one(
        "employee.custody.category",
        string="التصنيف",
        related="custody_type_id.category_id",
        store=True,
    )

    # ------------------------------------------------------------------
    # Dates
    # ------------------------------------------------------------------
    request_date = fields.Date(
        string="تاريخ الطلب",
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )
    issue_date = fields.Date(string="تاريخ الإصدار", tracking=True, copy=False)
    expected_return_date = fields.Date(
        string="التاريخ المتوقع للتسوية",
        tracking=True,
    )
    settlement_date = fields.Date(string="تاريخ التسوية النهائية", readonly=True, copy=False)

    # ------------------------------------------------------------------
    # Financial
    # ------------------------------------------------------------------
    currency_id = fields.Many2one(
        "res.currency",
        string="العملة",
        required=True,
        default=lambda self: self.env.company.currency_id,
        tracking=True,
    )
    amount = fields.Monetary(
        string="المبلغ",
        currency_field="currency_id",
        tracking=True,
    )
    amount_settled = fields.Monetary(
        string="المسوى",
        currency_field="currency_id",
        compute="_compute_amounts",
        store=True,
    )
    balance_amount = fields.Monetary(
        string="الرصيد",
        currency_field="currency_id",
        compute="_compute_amounts",
        store=True,
    )
    settlement_ratio = fields.Float(
        string="نسبة التسوية",
        compute="_compute_amounts",
        store=True,
        # Odoo 18 renamed ``group_operator`` to ``aggregator``.
        aggregator="avg",
    )

    # ------------------------------------------------------------------
    # Material
    # ------------------------------------------------------------------
    product_id = fields.Many2one(
        "product.product",
        string="المنتج / الأصل",
        check_company=True,
    )
    asset_description = fields.Char(string="وصف الأصل")
    serial_number = fields.Char(string="الرقم التسلسلي")
    quantity = fields.Float(string="الكمية", default=1.0, digits="Product Unit")
    returned_quantity = fields.Float(
        string="الكمية المرتجعة",
        compute="_compute_quantities",
        store=True,
        digits="Product Unit",
    )
    remaining_quantity = fields.Float(
        string="الكمية المتبقية",
        compute="_compute_quantities",
        store=True,
        digits="Product Unit",
    )
    condition = fields.Selection(
        [
            ("good", "سليمة"),
            ("fair", "مستعملة"),
            ("damaged", "تالفة"),
            ("lost", "مفقودة"),
        ],
        string="الحالة",
        default="good",
        tracking=True,
    )
    uom_id = fields.Many2one(
        "uom.uom",
        string="وحدة القياس",
        related="product_id.uom_id",
        readonly=False,
    )

    # ------------------------------------------------------------------
    # Accounting overrides (optional at the custody level)
    # ------------------------------------------------------------------
    journal_id = fields.Many2one(
        "account.journal",
        string="اليومية",
        check_company=True,
        domain="[('company_id', '=', company_id)]",
    )
    custody_account_id = fields.Many2one(
        "account.account",
        string="حساب العهدة",
        check_company=True,
        domain="[('company_ids', 'in', company_id)]",
    )
    cash_account_id = fields.Many2one(
        "account.account",
        string="حساب الصندوق/البنك",
        check_company=True,
        domain="[('company_ids', 'in', company_id)]",
    )
    # analytic_distribution is provided by the analytic.mixin inherited above.

    # ------------------------------------------------------------------
    # Relations
    # ------------------------------------------------------------------
    line_ids = fields.One2many(
        "employee.custody.line",
        "custody_id",
        string="تفاصيل العهدة",
        copy=True,
    )
    settlement_ids = fields.One2many(
        "employee.custody.settlement",
        "custody_id",
        string="التسويات",
        copy=False,
    )
    move_ids = fields.One2many(
        "account.move",
        "custody_id",
        string="القيود اليومية",
        copy=False,
    )
    issue_move_id = fields.Many2one(
        "account.move",
        string="قيد الإصدار",
        copy=False,
        readonly=True,
    )

    # ------------------------------------------------------------------
    # Counts / flags
    # ------------------------------------------------------------------
    settlement_count = fields.Integer(
        string="عدد التسويات",
        compute="_compute_counts",
    )
    move_count = fields.Integer(
        string="عدد القيود",
        compute="_compute_counts",
    )
    employee_custody_count = fields.Integer(
        string="عهد الموظف",
        compute="_compute_counts",
    )

    is_overdue = fields.Boolean(
        string="متأخرة",
        compute="_compute_overdue",
        search="_search_is_overdue",
        store=False,
    )
    overdue_days = fields.Integer(
        string="أيام التأخير",
        compute="_compute_overdue",
    )

    notes = fields.Html(string="الملاحظات")
    rejection_reason = fields.Text(string="سبب الرفض", readonly=True, copy=False)

    parent_custody_id = fields.Many2one(
        "employee.custody",
        string="العهدة الأصلية",
        readonly=True,
        copy=False,
        ondelete="set null",
        index=True,
        help="إذا تم إنشاء هذه العهدة "
             "كعهدة تكميلية لتسوية "
             "تجاوزت الرصيد، تشير "
             "إلى العهدة الأصلية.",
    )
    child_custody_ids = fields.One2many(
        "employee.custody",
        "parent_custody_id",
        string="العهد التكميلية",
    )
    child_custody_count = fields.Integer(
        compute="_compute_child_custody_count",
        string="عدد العهد التكميلية",
    )

    # ------------------------------------------------------------------
    # Overage / Employee Due (when this custody was created from a
    # settlement that exceeded the parent's balance).
    # ------------------------------------------------------------------
    origin_custody_id = fields.Many2one(
        "employee.custody",
        related="parent_custody_id",
        store=True,
        string="العهدة الأصلية (المصدر)",
        help="العهدة التي نتج عنها هذا الطلب نتيجة "
             "تجاوز مبلغ التسوية للرصيد.",
    )
    over_settlement_difference = fields.Monetary(
        string="فرق التجاوز (مجمد)",
        currency_field="currency_id",
        readonly=True,
        copy=False,
        tracking=True,
        help="مبلغ الفرق الذي ترتب على تسوية العهدة الأصلية "
             "وأنتج هذا الطلب. يبقى ثابتاً للمراجعة.",
    )
    employee_due_amount = fields.Monetary(
        string="مستحق الموظف",
        currency_field="currency_id",
        readonly=True,
        copy=False,
        tracking=True,
        help="المبلغ المسجل كمستحق للموظف بقيد محاسبي مستقل.",
    )
    original_remaining_amount = fields.Monetary(
        string="مبلغ الفرق الأصلي",
        currency_field="currency_id",
        readonly=True,
        copy=False,
        help="مبلغ الفرق الذي تم به إنشاء طلب العهدة الجديد.",
    )
    # Spec-named alias: spec field "original_difference_amount" mirrors
    # ``original_remaining_amount`` and is exposed for API stability.
    original_difference_amount = fields.Monetary(
        string="مبلغ الفرق الأصلي (Spec)",
        currency_field="currency_id",
        related="original_remaining_amount",
        store=True,
        readonly=True,
        help="اسم متوافق مع المواصفة. يطابق original_remaining_amount.",
    )
    requested_new_custody_amount = fields.Monetary(
        string="المبلغ المطلوب الأصلي",
        currency_field="currency_id",
        readonly=True,
        copy=False,
        help="المبلغ الذي طُلب عند إنشاء العهدة (قبل أي تعديل من المستخدم).",
    )
    # Spec-named alias: spec field "requested_disbursement_amount" mirrors
    # ``requested_new_custody_amount`` and is exposed for API stability.
    requested_disbursement_amount = fields.Monetary(
        string="المبلغ المطلوب للصرف (Spec)",
        currency_field="currency_id",
        related="requested_new_custody_amount",
        store=True,
        readonly=True,
        help="اسم متوافق مع المواصفة. يطابق requested_new_custody_amount.",
    )
    editable_disbursement_amount = fields.Monetary(
        string="مبلغ الصرف القابل للتعديل",
        currency_field="currency_id",
        compute="_compute_editable_disbursement_amount",
        help="يعكس المبلغ الفعلي الذي سيُصرف عند الضغط على زر الصرف.",
    )

    # ------------------------------------------------------------------
    # Auto due-reconciliation tracking (Step 5)
    # ------------------------------------------------------------------
    employee_due_move_id = fields.Many2one(
        "account.move",
        string="قيد نشأة المستحق",
        readonly=True,
        copy=False,
        help="القيد المحاسبي الذي أنشأ مستحق الموظف عند تجاوز التسوية.",
    )
    due_reconciliation_move_id = fields.Many2one(
        "account.move",
        string="قيد تسوية المستحق التلقائي",
        readonly=True,
        copy=False,
        help="القيد المحاسبي الذي سَوّى مستحق الموظف تلقائياً عند صرف العهدة "
             "التكميلية (Dr مستحقات الموظف / Cr حساب العهدة).",
    )
    is_due_auto_reconciled = fields.Boolean(
        string="تمت تسوية المستحق",
        compute="_compute_is_due_auto_reconciled",
        store=True,
        help="يصبح صحيحاً عندما يُسجَّل القيد التلقائي لتسوية مستحق الموظف.",
    )
    generated_from_over_settlement = fields.Boolean(
        string="ناتجة عن تجاوز تسوية",
        compute="_compute_generated_from_over_settlement",
        store=True,
        help="يدل على أن هذه العهدة أُنشئت تلقائياً نتيجة تجاوز تسوية "
             "عهدة سابقة، ويستحق الموظف الفرق المُجمَّد.",
    )
    employee_due_move_count = fields.Integer(
        string="إدخالات مستحقات الموظف",
        compute="_compute_employee_due_move_count",
    )

    # ------------------------------------------------------------------
    # Multi-company
    # ------------------------------------------------------------------
    company_id = fields.Many2one(
        "res.company",
        string="الشركة",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    # Approvers audit
    submitted_by = fields.Many2one("res.users", string="قدمها", readonly=True, copy=False)
    submitted_date = fields.Datetime(string="تاريخ التقديم", readonly=True, copy=False)
    approved_by = fields.Many2one("res.users", string="اعتمدها", readonly=True, copy=False)
    approved_date = fields.Datetime(string="تاريخ الاعتماد", readonly=True, copy=False)
    issued_by = fields.Many2one("res.users", string="صرفها", readonly=True, copy=False)

    # ==================================================================
    # COMPUTES
    # ==================================================================
    @api.depends("state")
    def _compute_color(self):
        mapping = {
            "draft": 0,
            "submitted": 4,
            "approved": 3,
            "issued": 1,
            "partial": 2,
            "settled": 10,
            "returned": 10,
            "damaged": 9,
            "lost": 1,
            "rejected": 1,
            "cancelled": 0,
        }
        for rec in self:
            rec.color = mapping.get(rec.state, 0)

    @api.depends(
        "amount",
        "settlement_ids.state",
        "settlement_ids.amount",
        "custody_kind",
    )
    def _compute_amounts(self):
        for rec in self:
            if rec.custody_kind == "financial":
                settled = sum(
                    s.amount for s in rec.settlement_ids
                    if s.state == "posted"
                )
            else:
                settled = 0.0
            rec.amount_settled = settled
            rec.balance_amount = (rec.amount or 0.0) - settled
            rec.settlement_ratio = (
                (settled / rec.amount) if rec.amount else 0.0
            )

    @api.depends(
        "quantity",
        "settlement_ids.state",
        "settlement_ids.returned_quantity",
        "custody_kind",
    )
    def _compute_quantities(self):
        for rec in self:
            if rec.custody_kind == "material":
                returned = sum(
                    s.returned_quantity for s in rec.settlement_ids
                    if s.state == "posted"
                )
            else:
                returned = 0.0
            rec.returned_quantity = returned
            rec.remaining_quantity = (rec.quantity or 0.0) - returned

    @api.depends("child_custody_ids")
    def _compute_child_custody_count(self):
        for rec in self:
            rec.child_custody_count = len(rec.child_custody_ids)

    @api.depends("amount", "state")
    def _compute_editable_disbursement_amount(self):
        for rec in self:
            # The editable disbursement is the live custody amount until
            # the custody is issued. After issue, it is the same value
            # (but the amount field becomes frozen by workflow rules).
            rec.editable_disbursement_amount = rec.amount or 0.0

    @api.depends("due_reconciliation_move_id", "due_reconciliation_move_id.state")
    def _compute_is_due_auto_reconciled(self):
        for rec in self:
            rec.is_due_auto_reconciled = bool(
                rec.due_reconciliation_move_id
                and rec.due_reconciliation_move_id.state == "posted"
            )

    @api.depends("parent_custody_id", "original_remaining_amount")
    def _compute_generated_from_over_settlement(self):
        for rec in self:
            rec.generated_from_over_settlement = bool(
                rec.parent_custody_id
                and (rec.original_remaining_amount or 0.0) > 0
            )

    @api.depends(
        "employee_due_move_id",
        "due_reconciliation_move_id",
        "child_custody_ids.employee_due_move_id",
        "child_custody_ids.due_reconciliation_move_id",
    )
    def _compute_employee_due_move_count(self):
        for rec in self:
            moves = rec.employee_due_move_id | rec.due_reconciliation_move_id
            for child in rec.child_custody_ids:
                moves |= child.employee_due_move_id | child.due_reconciliation_move_id
            rec.employee_due_move_count = len(moves)

    @api.depends("settlement_ids", "move_ids", "employee_id")
    def _compute_counts(self):
        for rec in self:
            rec.settlement_count = len(rec.settlement_ids)
            rec.move_count = len(rec.move_ids)
            rec.employee_custody_count = self.env["employee.custody"].search_count([
                ("employee_id", "=", rec.employee_id.id),
            ])

    @api.depends("expected_return_date", "state")
    def _compute_overdue(self):
        today = fields.Date.context_today(self)
        open_states = ("issued", "partial")
        for rec in self:
            if (
                rec.state in open_states
                and rec.expected_return_date
                and rec.expected_return_date < today
            ):
                rec.is_overdue = True
                rec.overdue_days = (today - rec.expected_return_date).days
            else:
                rec.is_overdue = False
                rec.overdue_days = 0

    def _search_is_overdue(self, operator, value):
        today = fields.Date.context_today(self)
        if operator not in ("=", "!="):
            raise UserError(_("عامل بحث غير مدعوم على حقل متأخرة."))
        positive = (operator == "=" and value) or (operator == "!=" and not value)
        domain_overdue = [
            ("state", "in", ("issued", "partial")),
            ("expected_return_date", "<", today),
            ("expected_return_date", "!=", False),
        ]
        if positive:
            return domain_overdue
        return ["!"] + domain_overdue

    # ==================================================================
    # ONCHANGE
    # ==================================================================
    @api.onchange("custody_type_id")
    def _onchange_custody_type_id(self):
        if self.custody_type_id:
            if self.custody_type_id.journal_id:
                self.journal_id = self.custody_type_id.journal_id
            if self.custody_type_id.custody_account_id:
                self.custody_account_id = self.custody_type_id.custody_account_id
            if self.custody_type_id.cash_account_id:
                self.cash_account_id = self.custody_type_id.cash_account_id
            if self.request_date and self.custody_type_id.default_duration_days:
                self.expected_return_date = fields.Date.add(
                    self.request_date,
                    days=self.custody_type_id.default_duration_days,
                )

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        if self.employee_id and self.employee_id.company_id:
            self.company_id = self.employee_id.company_id

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id and not self.asset_description:
            self.asset_description = self.product_id.display_name

    # ==================================================================
    # CONSTRAINTS
    # ==================================================================
    @api.constrains("amount", "custody_kind")
    def _check_amount_positive(self):
        for rec in self:
            if rec.custody_kind == "financial":
                if float_compare(rec.amount or 0.0, 0.0,
                                 precision_rounding=rec.currency_id.rounding or 0.01) <= 0:
                    raise ValidationError(_("مبلغ العهدة المالية يجب أن يكون أكبر من صفر."))

    @api.constrains("quantity", "custody_kind")
    def _check_quantity_positive(self):
        for rec in self:
            if rec.custody_kind == "material":
                if (rec.quantity or 0.0) <= 0:
                    raise ValidationError(_("كمية العهدة العينية يجب أن تكون أكبر من صفر."))
                if not rec.product_id and not rec.asset_description:
                    raise ValidationError(_("يجب تحديد المنتج أو وصف الأصل للعهدة العينية."))

    @api.constrains("request_date", "expected_return_date", "issue_date")
    def _check_dates(self):
        for rec in self:
            if rec.expected_return_date and rec.issue_date:
                if rec.expected_return_date < rec.issue_date:
                    raise ValidationError(
                        _("التاريخ المتوقع للتسوية يجب أن يكون بعد أو يساوي تاريخ الإصدار.")
                    )

    @api.constrains("employee_id", "company_id")
    def _check_company_consistency(self):
        for rec in self:
            if rec.employee_id.company_id and rec.employee_id.company_id != rec.company_id:
                raise ValidationError(
                    _("الموظف لا ينتمي إلى نفس شركة العهدة.")
                )

    # ==================================================================
    # CRUD
    # ==================================================================
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("جديد")) == _("جديد"):
                company_id = vals.get("company_id") or self.env.company.id
                seq = self.env["ir.sequence"].with_company(company_id).next_by_code(
                    "employee.custody"
                )
                vals["name"] = seq or _("جديد")
        return super().create(vals_list)

    def write(self, vals):
        # Lock critical fields after the custody is issued.
        if self.env.user.has_group("hr_employee_custody.group_custody_admin"):
            return super().write(vals)
        locked = {f for f in LOCKED_FIELDS if f in vals}
        if locked:
            for rec in self:
                if rec.state in LOCKED_STATES:
                    raise UserError(
                        _("لا يمكن تعديل الحقول %(fields)s بعد صرف العهدة.")
                        % {"fields": ", ".join(locked)}
                    )
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.state not in ("draft", "cancelled", "rejected"):
                raise UserError(
                    _("لا يمكن حذف عهدة في الحالة %s. قم بإلغائها أولاً.") % rec.state
                )
            if rec.move_ids.filtered(lambda m: m.state == "posted"):
                raise UserError(_("لا يمكن حذف عهدة لها قيود محاسبية مرحلة."))
        return super().unlink()

    # ==================================================================
    # WORKFLOW — state transitions
    # ==================================================================
    def _require_state(self, allowed):
        for rec in self:
            if rec.state not in allowed:
                raise UserError(
                    _("لا يمكن تنفيذ هذا الإجراء في الحالة '%s'.") % rec.state
                )

    def action_submit(self):
        self._require_state({"draft"})
        self.write({
            "state": "submitted",
            "submitted_by": self.env.user.id,
            "submitted_date": fields.Datetime.now(),
        })
        for rec in self:
            rec._notify_approvers()
            rec.message_post(body=_("تم تقديم طلب العهدة للاعتماد."))
        return True

    def action_approve(self):
        self._require_state({"submitted", "draft"})
        if not self.env.user.has_group("hr_employee_custody.group_custody_officer"):
            raise UserError(_("صلاحيات الاعتماد غير متاحة لهذا المستخدم."))
        self.write({
            "state": "approved",
            "approved_by": self.env.user.id,
            "approved_date": fields.Datetime.now(),
        })
        for rec in self:
            rec.message_post(body=_("تم اعتماد العهدة."))
        return True

    def action_reject(self):
        self._require_state({"submitted", "draft", "approved"})
        return {
            "name": _("رفض العهدة"),
            "type": "ir.actions.act_window",
            "res_model": "custody.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_custody_id": self.id},
        } if False else self._do_reject()

    def _do_reject(self, reason=None):
        self.write({
            "state": "rejected",
            "rejection_reason": reason or "",
        })
        for rec in self:
            rec.message_post(body=_("تم رفض العهدة. السبب: %s") % (reason or "-"))
        return True

    def action_issue(self):
        """Mark the custody as issued and post the accounting entry.

        When the custody was generated from an over-settlement of a parent
        custody, this method also posts the automatic due-reconciliation
        entry for the **frozen original difference** -- never the edited
        disbursement amount. See :meth:`_auto_settle_employee_due`.
        """
        self._require_state({"approved"})
        for rec in self:
            rec._validate_before_issue()
            rec.write({
                "state": "issued",
                "issue_date": rec.issue_date or fields.Date.context_today(self),
                "issued_by": self.env.user.id,
            })
            if not rec.expected_return_date:
                days = rec.custody_type_id.default_duration_days or 30
                rec.expected_return_date = fields.Date.add(rec.issue_date, days=days)
            if rec._accounting_enabled() and rec.custody_kind == "financial":
                rec._post_issue_move()
                # Step 5: auto-settle the employee due that was created when
                # the parent custody was over-settled. Idempotent.
                rec._auto_settle_employee_due()
            rec.message_post(body=_("تم صرف العهدة."))
        return True

    def action_settle(self):
        """Open the settlement wizard."""
        self.ensure_one()
        self._require_state({"issued", "partial"})
        return {
            "name": _("تسوية العهدة"),
            "type": "ir.actions.act_window",
            "res_model": "custody.settlement.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_custody_id": self.id,
                "default_settlement_kind":
                    "return" if self.custody_kind == "material" else "expense",
            },
        }

    def action_mark_returned(self):
        """Material custody fully returned."""
        self._require_state({"issued", "partial"})
        for rec in self:
            if rec.custody_kind != "material":
                raise UserError(_("هذا الإجراء مخصص للعهد العينية فقط."))
            if float_compare(rec.remaining_quantity, 0.0,
                             precision_digits=2) > 0:
                raise UserError(_("لا يزال هناك كميات غير مرتجعة."))
            rec.state = "returned"
            rec.settlement_date = fields.Date.context_today(self)
            rec.message_post(body=_("تم إرجاع كامل العهدة العينية."))
        return True

    def action_mark_lost(self):
        self._require_state({"issued", "partial"})
        for rec in self:
            rec.state = "lost"
            rec.message_post(body=_("تم تسجيل العهدة كمفقودة."))
        return True

    def action_mark_damaged(self):
        self._require_state({"issued", "partial", "returned"})
        for rec in self:
            rec.state = "damaged"
            rec.message_post(body=_("تم تسجيل العهدة كتالفة."))
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state in ("settled", "returned"):
                raise UserError(_("لا يمكن إلغاء عهدة مسواة أو مرجعة."))
            if rec.issue_move_id and rec.issue_move_id.state == "posted":
                raise UserError(
                    _("العهدة لها قيد مرحل. قم بعكس القيد أولاً.")
                )
            rec.state = "cancelled"
            rec.message_post(body=_("تم إلغاء العهدة."))
        return True

    def action_reset_to_draft(self):
        if not self.env.user.has_group("hr_employee_custody.group_custody_admin"):
            raise UserError(_("فقط المدير يمكنه إعادة العهدة للمسودة."))
        for rec in self:
            if rec.move_ids.filtered(lambda m: m.state == "posted"):
                raise UserError(_("لا يمكن إعادة عهدة لها قيود مرحلة للمسودة."))
            rec.write({
                "state": "draft",
                "submitted_by": False,
                "submitted_date": False,
                "approved_by": False,
                "approved_date": False,
                "issued_by": False,
                "issue_date": False,
                "rejection_reason": False,
            })
        return True

    def _validate_before_issue(self):
        self.ensure_one()
        if self.custody_kind == "financial" and not self.amount:
            raise UserError(_("أدخل مبلغ العهدة قبل الصرف."))
        if self.custody_kind == "material" and not self.quantity:
            raise UserError(_("أدخل الكمية قبل الصرف."))
        if self._accounting_enabled() and self.custody_kind == "financial":
            journal = self._resolve_account("journal")
            custody_acc = self._resolve_account("custody")
            cash_acc = self._resolve_account("cash")
            if not journal or not custody_acc or not cash_acc:
                raise UserError(_(
                    "الإعدادات المحاسبية غير مكتملة:\n"
                    "- اليومية\n"
                    "- حساب العهدة\n"
                    "- حساب الصندوق/البنك\n"
                    "راجع إعدادات العهد أو نوع العهدة."
                ))

    # ==================================================================
    # ACCOUNTING ENGINE
    # ==================================================================
    def _accounting_enabled(self):
        self.ensure_one()
        return bool(self.company_id.custody_enable_accounting)

    def _resolve_account(self, kind):
        """Resolve an account/journal using this precedence:

        custody override  >  custody type  >  company settings.
        """
        self.ensure_one()
        ctype = self.custody_type_id
        company = self.company_id
        mapping = {
            "journal":
                (self.journal_id, ctype.journal_id, company.custody_default_journal_id),
            "custody":
                (self.custody_account_id, ctype.custody_account_id, company.custody_account_id),
            "cash":
                (self.cash_account_id, ctype.cash_account_id, company.custody_cash_account_id),
            "expense":
                (False, ctype.expense_account_id, company.custody_expense_account_id),
            "salary":
                (False, ctype.salary_deduction_account_id, company.custody_salary_deduction_account_id),
            "loss":
                (False, ctype.loss_account_id, company.custody_loss_account_id),
            "analytic":
                (False, ctype.analytic_account_id, False),
        }
        for value in mapping[kind]:
            if value:
                return value
        return False

    def _prepare_issue_move_vals(self):
        """Prepare vals for the issue journal entry:
            Dr Custody Account
            Cr Cash/Bank Account
        """
        self.ensure_one()
        journal = self._resolve_account("journal")
        custody_acc = self._resolve_account("custody")
        cash_acc = self._resolve_account("cash")
        amount = self.amount
        analytic = self._resolve_account("analytic")
        analytic_distribution = self.analytic_distribution or (
            {str(analytic.id): 100.0} if analytic else False
        )

        narration = _("صرف عهدة %(name)s للموظف %(emp)s") % {
            "name": self.name,
            "emp": self.employee_id.name,
        }

        line_vals = [
            (0, 0, {
                "name": narration,
                "account_id": custody_acc.id,
                "partner_id": self.employee_id.work_contact_id.id
                    if self.employee_id.work_contact_id else False,
                "debit": amount,
                "credit": 0.0,
                "analytic_distribution": analytic_distribution,
            }),
            (0, 0, {
                "name": narration,
                "account_id": cash_acc.id,
                "debit": 0.0,
                "credit": amount,
            }),
        ]
        return {
            "journal_id": journal.id,
            "date": self.issue_date or fields.Date.context_today(self),
            "ref": self.name,
            "move_type": "entry",
            "company_id": self.company_id.id,
            "custody_id": self.id,
            "narration": narration,
            "line_ids": line_vals,
        }

    def _post_issue_move(self):
        self.ensure_one()
        if self.issue_move_id:
            raise UserError(_("قيد الإصدار موجود بالفعل لهذه العهدة."))
        move = self.env["account.move"].create(self._prepare_issue_move_vals())
        move.action_post()
        self.issue_move_id = move.id
        return move

    # ------------------------------------------------------------------
    # Step 5 — Auto Employee-Due Settlement
    # ------------------------------------------------------------------
    def _resolve_employee_due_account(self):
        """Resolve the employee-due GL account using the standard precedence.

        custody_type > company settings.
        """
        self.ensure_one()
        ctype = self.custody_type_id
        return (
            (ctype and ctype.employee_due_account_id)
            or self.company_id.custody_employee_due_account_id
            or False
        )

    def _prepare_due_reconciliation_move_vals(self, amount):
        """Build vals for the auto due-settlement entry:
            Dr  Employee Due Account
            Cr  Employee Custody Account
        Posted on the **child** custody for the **frozen** original
        difference -- never the edited disbursement amount.
        """
        self.ensure_one()
        journal = self._resolve_account("journal")
        custody_acc = self._resolve_account("custody")
        due_acc = self._resolve_employee_due_account()
        if not (journal and custody_acc and due_acc):
            raise UserError(_(
                "إعدادات حسابات تسوية مستحق الموظف غير مكتملة:\n"
                "- اليومية\n"
                "- حساب العهدة\n"
                "- حساب مستحقات الموظف\n"
                "راجع إعدادات الشركة أو نوع العهدة."
            ))
        partner_id = (
            self.employee_id.work_contact_id.id
            if self.employee_id.work_contact_id else False
        )
        analytic = self._resolve_account("analytic")
        analytic_distribution = self.analytic_distribution or (
            {str(analytic.id): 100.0} if analytic else False
        )
        parent_name = self.parent_custody_id.name if self.parent_custody_id else ""
        narration = _(
            "تسوية تلقائية لمستحق الموظف %(emp)s — "
            "فرق تسوية العهدة الأصلية %(p)s بمبلغ %(amt)s"
        ) % {
            "emp": self.employee_id.name,
            "p": parent_name,
            "amt": amount,
        }
        line_vals = [
            (0, 0, {
                "name": narration,
                "account_id": due_acc.id,
                "partner_id": partner_id,
                "debit": amount,
                "credit": 0.0,
                "analytic_distribution": analytic_distribution,
            }),
            (0, 0, {
                "name": narration,
                "account_id": custody_acc.id,
                "partner_id": partner_id,
                "debit": 0.0,
                "credit": amount,
            }),
        ]
        return {
            "journal_id": journal.id,
            "date": self.issue_date or fields.Date.context_today(self),
            "ref": _("تسوية مستحق الموظف - %s") % self.name,
            "move_type": "entry",
            "company_id": self.company_id.id,
            "custody_id": self.id,
            "narration": narration,
            "line_ids": line_vals,
        }

    def _auto_settle_employee_due(self):
        """Post the auto Dr Employee Due / Cr Custody settlement on this child custody.

        Implemented as an ``employee.custody.settlement`` record of kind
        ``due_reconciliation`` bound to a pre-built combined move. This
        ensures:

          * ``balance_amount`` natively reflects the offset (the
            ``_compute_amounts`` engine sums posted-settlement amounts).
          * The ``_check_values`` guard cannot mistakenly approve a
            future user-settlement that would over-spend the new custody.
          * One audit chain per move via ``settlement.move_id``.

        Idempotent: returns the existing move if already posted.

        Guards:
          * only fires for child custodies generated from over-settlement
          * only for ``original_remaining_amount`` > 0 (the FROZEN difference)
          * skipped if the reconciliation move already exists

        Reconciles the Employee Due GL lines (parent credit ↔ child
        debit) when the GL account is configured as reconcilable.
        """
        self.ensure_one()
        if not self.generated_from_over_settlement:
            return False
        if self.due_reconciliation_move_id:
            return self.due_reconciliation_move_id
        amount = self.original_remaining_amount or 0.0
        rounding = self.currency_id.rounding or 0.01
        if float_compare(amount, 0.0, precision_rounding=rounding) <= 0:
            return False

        move_vals = self._prepare_due_reconciliation_move_vals(amount)
        settlement = self.env["employee.custody.settlement"].create({
            "custody_id": self.id,
            "settlement_kind": "due_reconciliation",
            "settlement_date": self.issue_date or fields.Date.context_today(self),
            "description": _("تسوية تلقائية لمستحق الموظف"),
            "journal_id": move_vals["journal_id"],
            "analytic_distribution": self.analytic_distribution,
            "amount": amount,
            "employee_due_amount": amount,
            "full_expense_amount": 0.0,
        })
        move = settlement._post_with_external_move(move_vals)
        self.due_reconciliation_move_id = move.id

        # Try to reconcile the Employee Due credit (from parent's combined
        # settlement move) against the debit posted here. Safe no-op when
        # the GL account is not configured as reconcilable.
        try:
            self._reconcile_employee_due_lines(move)
        except Exception:  # noqa: BLE001 - reconciliation is best-effort
            self.message_post(body=_(
                "تعذّر تنفيذ المطابقة التلقائية على حساب مستحقات الموظف "
                "(تأكد من تفعيل خاصية التسوية على الحساب)."
            ))

        # Chatter logs on both sides.
        self.message_post(body=_(
            "تمت تسوية مستحق الموظف تلقائياً بمبلغ %(amt)s "
            "(الفرق الأصلي المُجمَّد) عبر القيد %(mv)s. "
            "الرصيد الفعّال المتاح الآن = %(rem)s."
        ) % {
            "amt": amount,
            "mv": move.name,
            "rem": (self.amount or 0.0) - amount,
        })
        if self.parent_custody_id:
            self.parent_custody_id.message_post(body=_(
                "تمت تسوية مستحق الموظف الناتج عن تجاوز هذه العهدة "
                "تلقائياً بمبلغ %(amt)s عبر القيد %(mv)s (العهدة %(c)s)."
            ) % {
                "amt": amount,
                "mv": move.name,
                "c": self.name,
            })
        return move

    def _reconcile_employee_due_lines(self, reconciliation_move):
        """Reconcile the Employee Due credit (parent combined-move) with
        the debit just posted on the child auto-reconciliation move.

        Only acts when the resolved Employee Due account is reconcilable.
        Safe no-op otherwise.
        """
        self.ensure_one()
        due_acc = self._resolve_employee_due_account()
        if not due_acc or not due_acc.reconcile:
            return False
        parent = self.parent_custody_id
        if not parent:
            return False
        # The combined settlement move on the parent carries the credit.
        # Prefer the stored employee_due_move_id, fall back to scanning
        # all parent moves for an Employee Due credit leg.
        candidate_credit_moves = (
            parent.employee_due_move_id
            | parent.move_ids.filtered(lambda m: m.state == "posted")
        )
        credit_lines = candidate_credit_moves.line_ids.filtered(
            lambda l: l.account_id == due_acc
            and l.credit > 0
            and not l.full_reconcile_id
        )
        debit_lines = reconciliation_move.line_ids.filtered(
            lambda l: l.account_id == due_acc and l.debit > 0
        )
        if not credit_lines or not debit_lines:
            return False
        (credit_lines + debit_lines).reconcile()
        return True

    # ==================================================================
    # ACTIVITIES / NOTIFICATIONS
    # ==================================================================
    def _get_approver_user(self):
        self.ensure_one()
        if self.employee_id.parent_id and self.employee_id.parent_id.user_id:
            return self.employee_id.parent_id.user_id
        # fall back to first manager in the custody manager group
        group = self.env.ref(
            "hr_employee_custody.group_custody_manager",
            raise_if_not_found=False,
        )
        if group and group.users:
            return group.users[0]
        return False

    def _notify_approvers(self):
        for rec in self:
            approver = rec._get_approver_user()
            if not approver:
                continue
            rec.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=approver.id,
                summary=_("طلب اعتماد عهدة %s") % rec.name,
                note=_("يوجد طلب عهدة جديد في انتظار اعتمادك."),
            )

    # ==================================================================
    # SMART BUTTONS
    # ==================================================================
    def action_view_settlements(self):
        self.ensure_one()
        return {
            "name": _("التسويات"),
            "type": "ir.actions.act_window",
            "res_model": "employee.custody.settlement",
            "view_mode": "list,form",
            "domain": [("custody_id", "=", self.id)],
            "context": {"default_custody_id": self.id},
        }

    def action_view_moves(self):
        self.ensure_one()
        return {
            "name": _("القيود اليومية"),
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", self.move_ids.ids)],
        }

    def action_view_child_custodies(self):
        self.ensure_one()
        return {
            "name": _("العهد التكميلية"),
            "type": "ir.actions.act_window",
            "res_model": "employee.custody",
            "view_mode": "list,form",
            "domain": [("parent_custody_id", "=", self.id)],
            "context": {"default_parent_custody_id": self.id},
        }

    def action_view_employee_custodies(self):
        self.ensure_one()
        return {
            "name": _("عهد الموظف"),
            "type": "ir.actions.act_window",
            "res_model": "employee.custody",
            "view_mode": "list,form,pivot,graph",
            "domain": [("employee_id", "=", self.employee_id.id)],
            "context": {"default_employee_id": self.employee_id.id},
        }

    def action_view_employee_due_moves(self):
        """Open the Employee Due journal entries linked to this custody.

        Includes:
          * the due-creation move (posted by the overage wizard on the parent)
          * the auto-reconciliation move (posted on the child at issue time)
        """
        self.ensure_one()
        moves = self.employee_due_move_id | self.due_reconciliation_move_id
        # Also include any due moves recorded against child custodies.
        for child in self.child_custody_ids:
            moves |= child.employee_due_move_id | child.due_reconciliation_move_id
        return {
            "name": _("إدخالات مستحقات الموظف"),
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", moves.ids)],
            "context": {"create": False},
        }

    # ==================================================================
    # AUTO STATE — called from settlements after posting
    # ==================================================================
    def _update_state_from_settlements(self):
        for rec in self:
            if rec.state not in ("issued", "partial"):
                continue
            if rec.custody_kind == "financial":
                if float_is_zero(rec.balance_amount,
                                 precision_rounding=rec.currency_id.rounding):
                    rec.write({
                        "state": "settled",
                        "settlement_date": fields.Date.context_today(self),
                    })
                elif rec.amount_settled > 0:
                    rec.state = "partial"
            else:  # material
                if float_is_zero(rec.remaining_quantity, precision_digits=2):
                    rec.write({
                        "state": "returned",
                        "settlement_date": fields.Date.context_today(self),
                    })
                elif rec.returned_quantity > 0:
                    rec.state = "partial"

    # ==================================================================
    # CRON
    # ==================================================================
    @api.model
    def _cron_mark_overdue(self):
        """Scheduled job: notify managers about overdue custodies."""
        today = fields.Date.context_today(self)
        overdue = self.search([
            ("state", "in", ("issued", "partial")),
            ("expected_return_date", "<", today),
            ("expected_return_date", "!=", False),
        ])
        for rec in overdue:
            approver = rec._get_approver_user()
            # Avoid duplicate activities
            existing = rec.activity_ids.filtered(
                lambda a, u=approver: a.summary and "متأخرة" in a.summary
            )
            if existing:
                continue
            if approver:
                rec.activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=approver.id,
                    summary=_("عهدة متأخرة %s") % rec.name,
                    note=_("العهدة متأخرة عن تاريخ التسوية المتوقع."),
                )
            rec.message_post(body=_("تم اكتشاف تأخر في تسوية العهدة."))
        return True
