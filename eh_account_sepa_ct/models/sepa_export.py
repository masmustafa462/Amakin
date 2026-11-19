# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
eh.sepa.export: audit row per generated PAIN.001 file.

The XML payload is stored as an attachment so re-downloading it does
not require regeneration, and so the auditor can inspect the exact
file that was uploaded to the bank. The SHA-256 fingerprint detects
accidental double exports of the same batch.

State machine: draft -> generated -> downloaded -> superseded. The
superseded state is set when a new export is generated for the same
batch (the prior file is kept, just flagged so the audit log shows
which file the bank actually received).
"""

import hashlib
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EhSepaExport(models.Model):
    _name = 'eh.sepa.export'
    _description = "SEPA Credit Transfer export file"
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
        help="GrpHdr/MsgId stamped on the XML. Globally unique.",
    )
    generated_at = fields.Datetime(
        required=True, default=fields.Datetime.now, index=True,
    )
    generated_by_id = fields.Many2one(
        'res.users', required=True,
        default=lambda self: self.env.user,
    )
    transaction_count = fields.Integer(readonly=True)
    control_sum = fields.Float(
        digits=(16, 2), readonly=True,
        help="Sum of every transaction amount in the file.",
    )
    file_hash = fields.Char(
        size=64, readonly=True, index=True,
        help="SHA-256 of the rendered XML bytes.",
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
        # When a new export is generated for a batch that already has
        # a generated/downloaded export, mark the prior ones superseded
        # so the audit trail shows which file is the active one.
        for rec in records:
            siblings = self.search([
                ('batch_id', '=', rec.batch_id.id),
                ('id', '!=', rec.id),
                ('state', 'in', ('generated', 'downloaded')),
            ])
            siblings.write({'state': 'superseded'})
        return records

    def action_download(self):
        self.ensure_one()
        if not self.attachment_id:
            raise UserError(_(
                "Export %s has no attached XML file. The export was "
                "either created in error or the attachment was "
                "deleted. Generate a fresh export from the batch.",
                self.message_id,
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
