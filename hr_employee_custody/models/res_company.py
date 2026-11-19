# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    # Feature toggles
    custody_enable_accounting = fields.Boolean(
        string="تفعيل التكامل المحاسبي",
        default=True,
    )
    custody_enable_approvals = fields.Boolean(
        string="تفعيل الاعتماد",
        default=True,
    )
    custody_enable_hr_approval = fields.Boolean(
        string="تفعيل اعتماد الموارد البشرية",
        default=False,
    )
    custody_enable_accounting_approval = fields.Boolean(
        string="تفعيل اعتماد المحاسبة",
        default=False,
    )
    custody_enable_notifications = fields.Boolean(
        string="تفعيل الإشعارات",
        default=True,
    )
    custody_allow_partial_settlement = fields.Boolean(
        string="السماح بالتسوية الجزئية",
        default=True,
    )

    # Defaults
    custody_default_journal_id = fields.Many2one(
        "account.journal",
        string="يومية العهد الافتراضية",
        domain="[('company_id', '=', id)]",
    )
    custody_account_id = fields.Many2one(
        "account.account",
        string="حساب العهدة (مدين عند الصرف)",
        domain="[('company_ids', 'in', id)]",
    )
    custody_cash_account_id = fields.Many2one(
        "account.account",
        string="حساب الصندوق/البنك",
        domain="[('company_ids', 'in', id)]",
    )
    custody_expense_account_id = fields.Many2one(
        "account.account",
        string="حساب المصروف الافتراضي",
        domain="[('company_ids', 'in', id)]",
    )
    custody_salary_deduction_account_id = fields.Many2one(
        "account.account",
        string="حساب خصم الراتب",
        domain="[('company_ids', 'in', id)]",
    )
    custody_loss_account_id = fields.Many2one(
        "account.account",
        string="حساب الفقد/التلف",
        domain="[('company_ids', 'in', id)]",
    )
    custody_employee_due_account_id = fields.Many2one(
        "account.account",
        string="حساب مستحقات الموظف",
        domain="[('company_ids', 'in', id)]",
        help="الحساب الذي يُسجَّل عليه الفرق المستحق للموظف عند تجاوز مبلغ التسوية لرصيد العهدة.",
    )
    custody_overdue_threshold_days = fields.Integer(
        string="Overdue threshold (days)",
        default=0,
        help="Number of days after which a custody is considered overdue.",
    )
