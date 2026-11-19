# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
Wizard: build a batch payment from selected source invoices.

The user picks the source moves (open customer invoices for an inbound
batch, open vendor bills for an outbound batch) and the wizard creates
one draft account.payment per source, attaching them to the batch.

Per-partner aggregation: when enabled, multiple sources for the same
partner collapse into a single payment line, with the memo carrying
the comma separated source references. Dedicated accounting
documentation lives on the resulting payment record.
"""

from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class EhBatchPaymentBuildWizard(models.TransientModel):
    _name = 'eh.batch.payment.build.wizard'
    _description = "Wizard: build a batch payment from selected invoices"

    batch_id = fields.Many2one(
        'eh.batch.payment',
        required=True,
        ondelete='cascade',
    )
    move_ids = fields.Many2many(
        'account.move',
        domain=(
            "[('state', '=', 'posted'),"
            " ('payment_state', 'in', ['not_paid', 'partial']),"
            " ('move_type', 'in', "
            "  (['out_invoice', 'out_refund'] if batch_type == 'inbound'"
            "   else ['in_invoice', 'in_refund']))]"
        ),
        string="Source invoices / bills",
    )
    aggregate_per_partner = fields.Boolean(
        default=True,
        help=(
            "When enabled, multiple selected invoices for the same "
            "partner produce a single payment summing the residuals. "
            "Otherwise each invoice gets its own payment."
        ),
    )
    batch_type = fields.Selection(
        related='batch_id.batch_type',
        readonly=True,
    )
    journal_id = fields.Many2one(
        related='batch_id.journal_id',
        readonly=True,
    )
    payment_date = fields.Date(
        related='batch_id.payment_date',
        readonly=True,
    )
    company_id = fields.Many2one(
        related='batch_id.company_id',
        readonly=True,
    )

    def action_build(self):
        self.ensure_one()
        if not self.move_ids:
            raise UserError(_("Pick at least one invoice or bill."))
        if any(m.company_id != self.batch_id.company_id for m in self.move_ids):
            raise UserError(_(
                "Every selected document must belong to the batch's "
                "company. Mixed company batches are not supported.",
            ))
        # Walk source AML -> partial reconciles -> counter AML -> payment
        # -> batch. Both directions (debit and credit) checked because
        # eh_batch_payment_id lives on account.payment, not on
        # account.move. The previous chain crashed with AttributeError.
        def _has_existing_batch(move):
            for line in move.line_ids:
                for partial in (line.matched_debit_ids
                                + line.matched_credit_ids):
                    counter = (
                        partial.debit_move_id
                        if partial.debit_move_id != line
                        else partial.credit_move_id
                    )
                    if counter.payment_id and counter.payment_id.eh_batch_payment_id:
                        return True
            return False

        already_batched = self.move_ids.filtered(_has_existing_batch)
        # Soft check; we do not block, but we surface in chatter.
        if self.aggregate_per_partner:
            payments = self._build_aggregated_payments()
        else:
            payments = self._build_per_invoice_payments()
        if already_batched:
            self.batch_id.message_post(body=_(
                "%d source document(s) were already partially settled "
                "by a previous batch. Verify amounts before posting.",
                len(already_batched),
            ))
        # Return navigation back to the batch form so the user lands on
        # the populated header.
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'eh.batch.payment',
            'res_id': self.batch_id.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'main',
        }

    def _build_aggregated_payments(self):
        self.ensure_one()
        Payment = self.env['account.payment']
        groups = defaultdict(lambda: {'amount': 0.0, 'refs': []})
        for move in self.move_ids:
            partner = move.partner_id
            if not partner:
                raise UserError(_(
                    "Document %s has no partner; cannot batch.",
                    move.display_name,
                ))
            key = partner.id
            groups[key]['partner_id'] = partner.id
            groups[key]['amount'] += abs(move.amount_residual)
            groups[key]['refs'].append(move.name or move.ref or '')

        created = self.env['account.payment']
        for partner_id, data in groups.items():
            if data['amount'] <= 0:
                continue
            payment_vals = self._payment_vals_common()
            payment_vals.update({
                'partner_id': partner_id,
                'amount': data['amount'],
                'memo': ', '.join(filter(None, data['refs']))[:200],
            })
            created |= Payment.create(payment_vals)
        return created

    def _build_per_invoice_payments(self):
        self.ensure_one()
        Payment = self.env['account.payment']
        created = self.env['account.payment']
        for move in self.move_ids:
            if not move.partner_id:
                raise UserError(_(
                    "Document %s has no partner; cannot batch.",
                    move.display_name,
                ))
            payment_vals = self._payment_vals_common()
            payment_vals.update({
                'partner_id': move.partner_id.id,
                'amount': abs(move.amount_residual),
                'memo': move.name or move.ref or '',
            })
            created |= Payment.create(payment_vals)
        return created

    def _payment_vals_common(self):
        self.ensure_one()
        if self.batch_id.batch_type == 'inbound':
            payment_type = 'inbound'
            partner_type = 'customer'
        else:
            payment_type = 'outbound'
            partner_type = 'supplier'
        vals = {
            'eh_batch_payment_id': self.batch_id.id,
            'journal_id': self.batch_id.journal_id.id,
            'payment_type': payment_type,
            'partner_type': partner_type,
            'date': self.batch_id.payment_date,
            'company_id': self.batch_id.company_id.id,
        }
        if self.batch_id.payment_method_line_id:
            vals['payment_method_line_id'] = (
                self.batch_id.payment_method_line_id.id
            )
        return vals
