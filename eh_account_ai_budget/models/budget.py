# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
Live wiring of the deterministic budget-variance commentary onto
eh.budget.budget.

The commentary is a non-stored computed field recomputed on read so it
always reflects the current line figures. The Odoo-independent
variance_commenter helper does the prose; this model only builds the
per-line snapshot and resolves the income flag from the account type.
"""

from odoo import api, fields, models

from odoo.addons.eh_account_ai_agent.tools import variance_commenter

# Mirrors the income classification used by the P&L report handler.
_INCOME_TYPES = ('income', 'income_other')


class EhBudget(models.Model):
    _inherit = 'eh.budget.budget'

    eh_ai_variance_commentary = fields.Text(
        string="AI variance commentary",
        compute='_compute_eh_ai_variance_commentary', store=False,
    )

    @api.depends(
        'name', 'line_ids',
        'line_ids.budgeted_amount', 'line_ids.actual_amount',
        'line_ids.account_id',
    )
    def _compute_eh_ai_variance_commentary(self):
        for budget in self:
            snapshot = budget._eh_build_budget_snapshot()
            company = budget.company_id
            budget.eh_ai_variance_commentary = variance_commenter.comment(
                snapshot,
                period_label=budget.name or '',
                provider_key=company.eh_ai_provider_key or 'manual',
                provider_config=company.eh_ai_provider_config or None,
            )

    def _eh_build_budget_snapshot(self):
        """Map budget lines onto the helper's BudgetLineSnapshot records.

        is_income is resolved from the line account's account_type so
        the commentary describes an income shortfall and an expense
        overrun correctly rather than treating every variance the same.
        """
        self.ensure_one()
        snapshot = []
        for line in self.line_ids:
            account = line.account_id
            if not account:
                continue
            snapshot.append(variance_commenter.BudgetLineSnapshot(
                label=account.display_name,
                budget=line.budgeted_amount or 0.0,
                actual=line.actual_amount or 0.0,
                is_income=account.account_type in _INCOME_TYPES,
            ))
        return snapshot

    def action_eh_ai_refresh_commentary(self):
        """Manual recompute gesture; also picks up a provider-config
        change made on the company since the last read.
        """
        self.invalidate_recordset(['eh_ai_variance_commentary'])
        return True
