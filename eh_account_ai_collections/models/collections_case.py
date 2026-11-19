# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
Live wiring of the deterministic collections next-action engine onto
eh.collections.case.

The suggestion is a non-stored computed field: it is recomputed on
every read so it always reflects the current case state (days overdue,
promises, contact history) without a stale stored value or a refresh
cron. The heavy lifting lives in the Odoo-independent
next_action_suggester helper; this model only builds the snapshot and
surfaces the result.
"""

from odoo import api, fields, models

from odoo.addons.eh_account_ai_agent.tools import next_action_suggester


class EhCollectionsCase(models.Model):
    _inherit = 'eh.collections.case'

    eh_ai_suggested_action = fields.Char(
        string="AI suggested action",
        compute='_compute_eh_ai_suggestion', store=False,
    )
    eh_ai_suggested_priority = fields.Selection(
        [('low', "Low"), ('medium', "Medium"), ('high', "High")],
        string="AI priority",
        compute='_compute_eh_ai_suggestion', store=False,
    )
    eh_ai_suggestion_rationale = fields.Text(
        string="AI rationale",
        compute='_compute_eh_ai_suggestion', store=False,
    )

    @api.depends(
        'days_overdue_max', 'total_overdue_amount',
        'has_active_promise', 'broken_promise',
        'action_ids', 'action_ids.contact_made',
        'action_ids.action_type', 'action_ids.action_date',
        'is_resolved',
    )
    def _compute_eh_ai_suggestion(self):
        for case in self:
            snap = case._eh_build_case_snapshot()
            company = case.company_id
            suggestion = next_action_suggester.suggest(
                snap,
                provider_key=company.eh_ai_provider_key or 'manual',
                provider_config=company.eh_ai_provider_config or None,
            )
            case.eh_ai_suggested_action = suggestion.action
            case.eh_ai_suggested_priority = suggestion.priority
            case.eh_ai_suggestion_rationale = suggestion.rationale

    def _eh_build_case_snapshot(self):
        """Map the case onto the helper's CaseSnapshot transport record."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        contacts = self.action_ids.filtered(lambda a: a.contact_made)
        last_action = self.action_ids.sorted(
            key=lambda a: a.action_date or fields.Datetime.now(),
            reverse=True,
        )[:1]
        last_days = 0
        if last_action and last_action.action_date:
            last_days = (today - last_action.action_date.date()).days
        return next_action_suggester.CaseSnapshot(
            days_overdue=self.days_overdue_max or 0,
            total_overdue=self.total_overdue_amount or 0.0,
            contact_count=len(contacts),
            has_active_promise=bool(self.has_active_promise),
            has_broken_promise=bool(self.broken_promise),
            last_action_type=(last_action.action_type or '') if last_action else '',
            last_action_days_ago=last_days,
            has_demand_letter=any(
                a.action_type == 'letter' for a in self.action_ids
            ),
            has_payment_plan=False,
            customer_segment='',
        )

    def action_eh_ai_refresh_suggestion(self):
        """Manual recompute. The field is non-stored so a read already
        refreshes it; this button exists for an explicit user gesture
        and to pick up a provider-config change made on the company.
        """
        self.invalidate_recordset([
            'eh_ai_suggested_action',
            'eh_ai_suggested_priority',
            'eh_ai_suggestion_rationale',
        ])
        return True
