# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
Single line of an IFRS 16 lease amortisation schedule.

On posting (lessee default), two journal entries are produced atomically
as one move:

* Lease entry: Dr Lease Liability (principal), Dr Interest Expense
  (interest), Cr Cash/Payables (payment); plus, when a lease / non-lease
  component split is set, Dr Lease/Service Expense (service share) and a
  matching extra Cr Cash so the cash leg settles the full contractual
  payment (IFRS 16.13-16).
* ROU depreciation: Dr ROU Depreciation, Cr ROU Accumulated Depreciation.

Exempt leases (IFRS 16.6) post Dr Lease Expense / Cr Cash only.
Operating lessors (IFRS 16.81) post Dr Cash / Cr Rental Income.
Finance lessors (IFRS 16.75) post Dr Cash, Cr Interest Income
(interest), Cr Net Investment (principal recovery).

Storing all legs on one move keeps the period view tight and reconciles
the lease liability (or net investment) cleanly.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class EhLeaseScheduleLine(models.Model):
    _name = 'eh.lease.schedule.line'
    _description = "Lease Amortisation Schedule Line"
    _order = 'lease_id, sequence'

    lease_id = fields.Many2one(
        'eh.lease.contract', required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(required=True, default=10)
    period_date = fields.Date(required=True)

    liability_open = fields.Monetary()
    payment_amount = fields.Monetary(
        help=(
            "Lease-component payment for the period (the amount the "
            "liability amortisation runs on). When a lease / non-lease "
            "split is set, the service share sits in service_amount and "
            "the cash leg settles payment_amount + service_amount."
        ),
    )
    service_amount = fields.Monetary(
        string="Service (non-lease) share",
        help=(
            "Non-lease component share of the period's contractual "
            "payment (IFRS 16.13-16); posts straight to the lease / "
            "service expense account, never into the liability or ROU."
        ),
    )
    interest = fields.Monetary()
    principal = fields.Monetary()
    liability_close = fields.Monetary()

    rou_amount = fields.Monetary(string="ROU Depreciation")
    rou_accumulated = fields.Monetary()

    is_posted = fields.Boolean(default=False, copy=False, readonly=True)
    posted_at = fields.Datetime(readonly=True, copy=False)
    posted_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    move_id = fields.Many2one(
        'account.move', readonly=True, copy=False, ondelete='set null',
    )

    currency_id = fields.Many2one(
        related='lease_id.currency_id', store=True, readonly=True,
    )
    company_id = fields.Many2one(
        related='lease_id.company_id', store=True, readonly=True,
    )

    _uniq_lease_sequence = models.Constraint(
        'unique(lease_id, sequence)',
        'Sequence must be unique within a lease.',
    )

    def action_post(self):
        if not self.env.user.has_group('eh_account_base.group_eh_manager'):
            raise UserError(_(
                "Only an accounting manager can post a lease schedule "
                "line to the general ledger. This posting is a "
                "segregation-of-duties control point.",
            ))
        for line in self:
            if line.is_posted:
                raise UserError(_(
                    "Lease schedule line already posted.",
                ))
            lease = line.lease_id
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'eh_sealed': True,
                'date': line.period_date,
                'journal_id': lease.journal_id.id,
                'ref': _("Lease %(name)s period %(seq)s",
                         name=lease.display_name, seq=line.sequence),
                'line_ids': line._build_move_lines(),
            })
            move.action_post()
            line.write({
                'is_posted': True,
                'posted_at': fields.Datetime.now(),
                'posted_by_id': self.env.user.id,
                'move_id': move.id,
            })

    def _build_move_lines(self):
        self.ensure_one()
        lease = self.lease_id
        # IFRS 16.6 exemption: straight-line expense, no ROU / liability.
        if lease.exemption != 'none':
            return [
                (0, 0, {
                    'name': _("Lease expense (exempt) %s", lease.display_name),
                    'account_id': lease.lease_expense_account_id.id,
                    'debit': self.payment_amount,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': _("Lease payment %s", lease.display_name),
                    'account_id': lease.cash_account_id.id,
                    'debit': 0.0,
                    'credit': self.payment_amount,
                }),
            ]
        # IFRS 16.81 operating lessor: straight-line rental income.
        if lease.lessor_mode == 'operating':
            return [
                (0, 0, {
                    'name': _("Lease receipt %s", lease.display_name),
                    'account_id': lease.cash_account_id.id,
                    'debit': self.payment_amount,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': _("Rental income %s", lease.display_name),
                    'account_id': lease.lessor_income_account_id.id,
                    'debit': 0.0,
                    'credit': self.payment_amount,
                }),
            ]
        # IFRS 16.75 finance lessor: receipt splits into interest income
        # and net-investment principal recovery.
        if lease.lessor_mode == 'finance':
            lines = []
            if self.payment_amount > 0:
                lines.append((0, 0, {
                    'name': _("Lease receipt %s", lease.display_name),
                    'account_id': lease.cash_account_id.id,
                    'debit': self.payment_amount,
                    'credit': 0.0,
                }))
            if self.interest > 0:
                lines.append((0, 0, {
                    'name': _("Interest income %s", lease.display_name),
                    'account_id': lease.lessor_interest_income_account_id.id,
                    'debit': 0.0,
                    'credit': self.interest,
                }))
            if self.principal > 0:
                lines.append((0, 0, {
                    'name': _("Net investment recovery %s",
                              lease.display_name),
                    'account_id': lease.net_investment_account_id.id,
                    'debit': 0.0,
                    'credit': self.principal,
                }))
            return lines
        lines = []
        # Liability principal
        if self.principal > 0:
            lines.append((0, 0, {
                'name': _("Lease principal %s", lease.display_name),
                'account_id': lease.lease_liability_account_id.id,
                'debit': self.principal,
                'credit': 0.0,
            }))
        # Interest expense
        if self.interest > 0:
            lines.append((0, 0, {
                'name': _("Lease interest %s", lease.display_name),
                'account_id': lease.interest_expense_account_id.id,
                'debit': self.interest,
                'credit': 0.0,
            }))
        # Non-lease (service) component: straight to expense, cash leg
        # below settles the full contractual payment (IFRS 16.13-16).
        if self.service_amount > 0:
            lines.append((0, 0, {
                'name': _("Service component %s", lease.display_name),
                'account_id': lease.lease_expense_account_id.id,
                'debit': self.service_amount,
                'credit': 0.0,
            }))
        # Cash / payable
        cash_total = (self.payment_amount or 0.0) + (self.service_amount or 0.0)
        if cash_total > 0:
            lines.append((0, 0, {
                'name': _("Lease payment %s", lease.display_name),
                'account_id': lease.cash_account_id.id,
                'debit': 0.0,
                'credit': cash_total,
            }))
        # ROU depreciation
        if self.rou_amount > 0:
            lines.append((0, 0, {
                'name': _("ROU depreciation %s", lease.display_name),
                'account_id': lease.rou_depreciation_account_id.id,
                'debit': self.rou_amount,
                'credit': 0.0,
            }))
            lines.append((0, 0, {
                'name': _("ROU accumulated depreciation %s", lease.display_name),
                'account_id': lease.rou_accumulated_depreciation_account_id.id,
                'debit': 0.0,
                'credit': self.rou_amount,
            }))
        return lines

    def action_view_move(self):
        self.ensure_one()
        if not self.move_id:
            raise UserError(_("No journal entry has been posted yet."))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
        }
