# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
res.partner extension: active collections cases counter.

Surfaces a smart-button on the partner form: "Active collections: N".
A click drills into the kanban filtered to this partner so the
operator goes from a customer record to the live collections case in
one hop instead of navigating through the menu.
"""

from odoo import api, fields, models
from odoo.addons.eh_account_base.tools.orm_compat import read_group_compat


class ResPartner(models.Model):
    _inherit = 'res.partner'

    eh_active_collections_count = fields.Integer(
        compute='_compute_eh_active_collections_count',
        help=(
            "Number of non-resolved collections cases on this partner. "
            "Refreshed on form load; the auto-creator cron and the "
            "manual refresh action update the underlying case totals."
        ),
    )

    @api.depends_context('uid')
    def _compute_eh_active_collections_count(self):
        Case = self.env['eh.collections.case'].sudo()
        groups = read_group_compat(Case, 
            [
                ('partner_id', 'in', self.ids),
                ('is_resolved', '=', False),
            ],
            groupby=['partner_id'],
            aggregates=['__count'],
        )
        counts = {p.id: c for p, c in groups}
        for partner in self:
            partner.eh_active_collections_count = counts.get(partner.id, 0)

    def action_view_eh_active_collections(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Collections cases',
            'res_model': 'eh.collections.case',
            'view_mode': 'kanban,list,form',
            'views': [(False, 'kanban'), (False, 'list'), (False, 'form')],
            'domain': [
                ('partner_id', '=', self.id),
                ('is_resolved', '=', False),
            ],
        }
