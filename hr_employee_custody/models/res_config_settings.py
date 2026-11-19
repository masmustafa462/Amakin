# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # Toggles
    custody_enable_accounting = fields.Boolean(
        related="company_id.custody_enable_accounting",
        readonly=False,
    )
    custody_enable_approvals = fields.Boolean(
        related="company_id.custody_enable_approvals",
        readonly=False,
    )
    custody_enable_hr_approval = fields.Boolean(
        related="company_id.custody_enable_hr_approval",
        readonly=False,
    )
    custody_enable_accounting_approval = fields.Boolean(
        related="company_id.custody_enable_accounting_approval",
        readonly=False,
    )
    custody_enable_notifications = fields.Boolean(
        related="company_id.custody_enable_notifications",
        readonly=False,
    )
    custody_allow_partial_settlement = fields.Boolean(
        related="company_id.custody_allow_partial_settlement",
        readonly=False,
    )

    # Defaults
    custody_default_journal_id = fields.Many2one(
        related="company_id.custody_default_journal_id",
        readonly=False,
    )
    custody_account_id = fields.Many2one(
        related="company_id.custody_account_id",
        readonly=False,
    )
    custody_cash_account_id = fields.Many2one(
        related="company_id.custody_cash_account_id",
        readonly=False,
    )
    custody_expense_account_id = fields.Many2one(
        related="company_id.custody_expense_account_id",
        readonly=False,
    )
    custody_salary_deduction_account_id = fields.Many2one(
        related="company_id.custody_salary_deduction_account_id",
        readonly=False,
    )
    custody_loss_account_id = fields.Many2one(
        related="company_id.custody_loss_account_id",
        readonly=False,
    )
    custody_employee_due_account_id = fields.Many2one(
        related="company_id.custody_employee_due_account_id",
        readonly=False,
    )
    custody_overdue_threshold_days = fields.Integer(
        related="company_id.custody_overdue_threshold_days",
        readonly=False,
    )
