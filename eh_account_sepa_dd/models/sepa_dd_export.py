# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
eh.sepa.dd.export: audit row per generated PAIN.008 file.

Mirrors the design of eh.sepa.export from the credit transfer module
(file hash, state machine, supersedes prior generation for the same
batch). Kept as a separate model so direct debit and credit transfer
exports can be queried, audited, and reported on independently.
"""

import hashlib

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class EhSepaDdExport(models.Model):
    _name = 'eh.sepa.dd.export'
    _description = "SEPA Direct Debit export file"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'generated_at desc, id desc'
    _rec_name = 'message_id'

    batch_id = fields.Many2one(
        'eh.batch.payment', required=True,
        ondelete='cascade', index=True,
    )
    company_id = fields.Many2one(
        related='batch_id.company_id', store=True, readonly=True,
    )
    message_id = fields.Char(
        required=True, copy=False, index=True,
    )
    generated_at = fields.Datetime(
        required=True, default=fields.Datetime.now, index=True,
    )
    generated_by_id = fields.Many2one(
        'res.users', required=True,
        default=lambda self: self.env.user,
    )
    transaction_count = fields.Integer(readonly=True)
    control_sum = fields.Float(digits=(16, 2), readonly=True)
    file_hash = fields.Char(size=64, readonly=True, index=True)
    sequence_type = fields.Selection(
        [
            ('FRST', "First"),
            ('RCUR', "Recurring"),
            ('FNAL', "Final"),
            ('OOFF', "One-off"),
        ],
        readonly=True,
        help=(
            "The sequence type used by every transaction in this file. "
            "Each PAIN.008 export groups one sequence type per file "
            "for clarity; mixed-sequence collections produce multiple "
            "files."
        ),
    )
    state = fields.Selection(
        [
            ('generated', "Generated"),
            ('downloaded', "Downloaded"),
            ('superseded', "Superseded"),
        ],
        default='generated', required=True, tracking=True,
    )
    attachment_id = fields.Many2one(
        'ir.attachment', readonly=True, ondelete='set null',
    )
    notes = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            siblings = self.search([
                ('batch_id', '=', rec.batch_id.id),
                ('id', '!=', rec.id),
                ('sequence_type', '=', rec.sequence_type),
                ('state', 'in', ('generated', 'downloaded')),
            ])
            siblings.write({'state': 'superseded'})
        return records

    def action_download(self):
        self.ensure_one()
        if not self.attachment_id:
            raise UserError(_(
                "Export %s has no attached XML file.", self.message_id,
            ))
        self.state = 'downloaded'
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % self.attachment_id.id,
            'target': 'download',
        }

    @staticmethod
    def compute_hash(content_bytes):
        return hashlib.sha256(content_bytes).hexdigest()
