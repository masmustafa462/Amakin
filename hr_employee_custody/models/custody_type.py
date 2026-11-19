# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class EmployeeCustodyType(models.Model):
    """Defines a specific custody type (financial or material).

    Each type can override default accounts/journal at a granular level,
    so the accounting engine can derive the correct GL postings per type.
    """

    _name = "employee.custody.type"
    _description = "Employee Custody Type | نوع العهدة"
    _order = "sequence, name"

    name = fields.Char(
        string="النوع",
        required=True,
        translate=True,
        index=True,
    )
    code = fields.Char(string="الرمز", index=True)
    sequence = fields.Integer(string="الترتيب", default=10)
    description = fields.Text(string="الوصف", translate=True)
    active = fields.Boolean(string="نشط", default=True)
    color = fields.Integer(string="اللون")

    custody_kind = fields.Selection(
        [
            ("financial", "مالية / Financial"),
            ("material", "عينية / Material"),
        ],
        string="نوع العهدة",
        required=True,
        default="financial",
        index=True,
    )

    category_id = fields.Many2one(
        "employee.custody.category",
        string="التصنيف",
        ondelete="restrict",
        index=True,
    )

    default_duration_days = fields.Integer(
        string="المدة الافتراضية (يوم)",
        default=30,
        help="عدد الأيام بين تاريخ الإصدار والتاريخ المتوقع للتسوية.",
    )

    require_approval = fields.Boolean(
        string="يتطلب موافقة",
        default=True,
    )
    require_hr_approval = fields.Boolean(
        string="يتطلب موافقة الموارد البشرية",
        default=False,
    )
    require_accounting_approval = fields.Boolean(
        string="يتطلب موافقة المحاسبة",
        default=False,
    )

    # --- Accounting overrides (optional) -----------------------------------
    journal_id = fields.Many2one(
        "account.journal",
        string="اليومية",
        domain="[('company_id', '=', company_id)]",
    )
    custody_account_id = fields.Many2one(
        "account.account",
        string="حساب العهدة",
        domain="[('company_ids', 'in', company_id)]",
        help="حساب المدين عند إصدار العهدة المالية (عادة أصل قصير الأجل).",
    )
    cash_account_id = fields.Many2one(
        "account.account",
        string="حساب الصندوق/البنك الافتراضي",
        domain="[('company_ids', 'in', company_id)]",
    )
    expense_account_id = fields.Many2one(
        "account.account",
        string="حساب المصروف الافتراضي",
        domain="[('company_ids', 'in', company_id)]",
    )
    salary_deduction_account_id = fields.Many2one(
        "account.account",
        string="حساب خصم الراتب",
        domain="[('company_ids', 'in', company_id)]",
    )
    loss_account_id = fields.Many2one(
        "account.account",
        string="حساب الفقد/التلف",
        domain="[('company_ids', 'in', company_id)]",
    )
    employee_due_account_id = fields.Many2one(
        "account.account",
        string="حساب مستحقات الموظف",
        domain="[('company_ids', 'in', company_id)]",
        help="يُستخدم لتسجيل الفرق المستحق للموظف عند تجاوز مبلغ التسوية لرصيد العهدة.",
    )
    analytic_account_id = fields.Many2one(
        "account.analytic.account",
        string="الحساب التحليلي الافتراضي",
    )

    # --- Material defaults --------------------------------------------------
    allow_partial_return = fields.Boolean(
        string="السماح بالإرجاع الجزئي",
        default=True,
    )

    company_id = fields.Many2one(
        "res.company",
        string="الشركة",
        default=lambda self: self.env.company,
        index=True,
    )

    # Odoo 19 declares SQL objects as model attributes; the legacy
    # ``_sql_constraints`` list is no longer read by the ORM.
    _code_company_uniq = models.Constraint(
        "unique(code, company_id)",
        "رمز النوع يجب أن يكون فريداً داخل الشركة.",
    )

    @api.constrains("default_duration_days")
    def _check_duration(self):
        for rec in self:
            if rec.default_duration_days < 0:
                raise ValidationError(_("المدة الافتراضية لا يمكن أن تكون سالبة."))

    # ``name_get`` was removed in Odoo 19: display names are produced by the
    # ``display_name`` computed field. Same output as the previous name_get.
    @api.depends("name", "code")
    def _compute_display_name(self):
        for rec in self:
            name = rec.name
            if rec.code:
                name = f"[{rec.code}] {name}"
            rec.display_name = name
