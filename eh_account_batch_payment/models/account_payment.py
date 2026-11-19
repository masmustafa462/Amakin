# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
account.payment extension for batch membership.

A payment is a member of at most one batch. The pointer is nullable
so existing payments are unaffected; assignment happens via the batch
build wizard or by editing the payment directly. ondelete='set null'
keeps payments alive even if a draft batch is deleted.
"""

from odoo import fields, models


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    eh_batch_payment_id = fields.Many2one(
        'eh.batch.payment',
        string="Batch",
        ondelete='set null',
        index=True,
        copy=False,
        help=(
            "Optional. When set, this payment is part of a batch run "
            "and is posted together with the batch's other members."
        ),
    )
