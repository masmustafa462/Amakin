# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
Extend eh.batch.payment with a SEPA Credit Transfer export action.

The action assembles the PAIN.001 input dict from the batch's payments
and delegates to the pure-python generator. Output is stored as an
ir.attachment and an eh.sepa.export audit row.
"""

import base64
import uuid
from datetime import datetime
from decimal import Decimal

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.eh_account_sepa_ct.tools import pain_001
from odoo.addons.eh_account_sepa_ct.tools.sepa_charset import (
    sanitize_sepa_text,
)
from odoo.addons.eh_account_sepa_ct.tools.iban_validator import (
    validate_iban, IbanValidationError,
)
from odoo.addons.eh_account_sepa_ct.tools.bic_validator import (
    validate_bic, BicValidationError,
)
from odoo.addons.eh_account_batch_payment.models.batch_payment import (
    POSTED_STATES,
)


class EhBatchPayment(models.Model):
    _inherit = 'eh.batch.payment'

    sepa_export_ids = fields.One2many(
        'eh.sepa.export', 'batch_id',
        copy=False,
    )
    last_sepa_export_id = fields.Many2one(
        'eh.sepa.export',
        compute='_compute_last_export', store=True,
    )

    @api.depends('sepa_export_ids', 'sepa_export_ids.state')
    def _compute_last_export(self):
        for batch in self:
            active = batch.sepa_export_ids.filtered(
                lambda e: e.state in ('generated', 'downloaded'),
            ).sorted('generated_at', reverse=True)
            batch.last_sepa_export_id = active[:1]

    def action_export_sepa_ct(self):
        """Generate the PAIN.001 XML and persist it as an attachment.

        Strict prerequisites:
        * Batch is outbound (SEPA CT pays out).
        * Batch is posted (we do not export drafts that have not been
          authorised).
        * Originator config exists for the batch's journal.
        * Every payment has a partner with a primary IBAN bank account
          on the company.
        * Every IBAN and (optional) BIC validates locally.
        """
        self.ensure_one()
        # Bank-file segregation of duties (maker/checker). Generating the
        # PAIN.001 is a money-moving act: it is the instruction the bank
        # executes. Require the manager group, and require that the
        # exporter is a different user from the people who assembled the
        # batch (confirmer / poster). Without this gate the same user who
        # builds the batch can also cut the bank file, defeating the
        # four-eyes control.
        if not self.env.user.has_group('eh_account_base.group_eh_manager'):
            raise UserError(_(
                "Only an EH Accounting Manager can generate the SEPA "
                "Credit Transfer bank file.",
            ))
        if self.confirmed_by_id and self.confirmed_by_id == self.env.user:
            raise UserError(_(
                "Segregation of duties: the manager who confirmed this "
                "batch cannot also generate the SEPA bank file. A "
                "different EH Accounting Manager must export it.",
            ))
        if self.posted_by_id and self.posted_by_id == self.env.user:
            raise UserError(_(
                "Segregation of duties: the manager who posted this "
                "batch cannot also generate the SEPA bank file. A "
                "different EH Accounting Manager must export it.",
            ))
        if self.batch_type != 'outbound':
            raise UserError(_(
                "SEPA Credit Transfer is for outbound batches only.",
            ))
        if self.state != 'posted':
            raise UserError(_(
                "Export the SEPA file only after the batch is posted. "
                "This guarantees the bank receives the same payments "
                "the GL has booked.",
            ))
        originator = self.env['eh.sepa.originator'].search(
            [
                ('journal_id', '=', self.journal_id.id),
                ('journal_id.company_id', 'in',
                 [self.company_id.id, False]),
            ],
            limit=1,
        )
        if not originator:
            raise UserError(_(
                "Journal %s has no SEPA originator configured. Add "
                "one under Configuration > SEPA Originators.",
                self.journal_id.display_name,
            ))

        # Single-currency enforcement. ISO 20022 PAIN.001 expresses one
        # control sum at the message level, derived from amounts in a
        # single currency. Banks reject mixed-currency files; we refuse
        # at submission time so the user fixes the batch before the
        # bank does.
        currencies = self.payment_ids.filtered(
            lambda p: p.state in POSTED_STATES,
        ).mapped('currency_id')
        if len(currencies) > 1:
            raise UserError(_(
                "Batch contains payments in %(count)s different "
                "currencies (%(names)s). Split the batch by currency "
                "before exporting; SEPA Credit Transfer requires one "
                "currency per file.",
                count=len(currencies),
                names=', '.join(currencies.mapped('name')),
            ))
        # Euro enforcement. SEPA Credit Transfer is a euro-denominated
        # scheme and the generated pain.001 declares EUR at the amount
        # level. Refuse a non-euro batch here rather than emit a file
        # that mislabels the amounts as EUR.
        if currencies and currencies.name != 'EUR':
            raise UserError(_(
                "SEPA Credit Transfer files are euro-denominated, but "
                "this batch is in %(name)s. Convert the payments to EUR "
                "or use a non-SEPA payment method.",
                name=currencies.name,
            ))

        payload = self._eh_build_pain_001_payload(originator)
        version = originator.pain_001_version or '03'
        xml_bytes = pain_001.render(payload, version=version)
        attachment = self._eh_persist_sepa_attachment(payload, xml_bytes)
        export = self.env['eh.sepa.export'].create({
            'batch_id': self.id,
            'message_id': payload['message_id'],
            'transaction_count': sum(
                len(p['transactions']) for p in payload['payments']
            ),
            'control_sum': float(sum(
                Decimal(str(tx['amount']))
                for p in payload['payments']
                for tx in p['transactions']
            )),
            'file_hash': self.env['eh.sepa.export'].compute_hash(xml_bytes),
            'attachment_id': attachment.id,
        })
        self.message_post(body=_(
            "SEPA Credit Transfer file generated. Message ID: %s. "
            "Transactions: %d. Control sum: %.2f.",
            export.message_id,
            export.transaction_count,
            export.control_sum,
        ))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'download',
        }

    def _eh_build_pain_001_payload(self, originator):
        self.ensure_one()
        payments = self.payment_ids.filtered(
            lambda p: p.state in POSTED_STATES,
        )
        if not payments:
            raise UserError(_(
                "Batch contains no posted payments to export.",
            ))

        # Normalise originator IBAN/BIC (already validated at write time
        # by the originator's @api.constrains). The validator returns
        # the canonicalised form so we re-normalise defensively.
        try:
            dbtr_iban = validate_iban(originator.iban)
        except IbanValidationError as exc:
            raise UserError(_(
                "Originator IBAN failed validation: %s. Fix the SEPA "
                "originator config and retry.",
            ) % str(exc))
        dbtr_bic = None
        if originator.bic:
            try:
                dbtr_bic = validate_bic(originator.bic)
            except BicValidationError as exc:
                raise UserError(_(
                    "Originator BIC failed validation: %s.",
                ) % str(exc))

        transactions = []
        for idx, payment in enumerate(payments, start=1):
            partner_bank = self._eh_resolve_creditor_bank(payment)
            try:
                cdtr_iban = validate_iban(partner_bank.acc_number)
            except IbanValidationError as exc:
                raise UserError(_(
                    "Payment %(name)s: creditor IBAN invalid (%(err)s).",
                    name=payment.display_name,
                    err=str(exc),
                ))
            cdtr_bic = None
            if partner_bank.bank_bic:
                try:
                    cdtr_bic = validate_bic(partner_bank.bank_bic)
                except BicValidationError as exc:
                    raise UserError(_(
                        "Payment %(name)s: creditor BIC invalid "
                        "(%(err)s).",
                        name=payment.display_name,
                        err=str(exc),
                    ))
            transactions.append({
                'end_to_end_id': self._eh_clip(
                    payment.name or "PMT%05d" % idx, 35,
                ),
                'amount': Decimal(str(payment.amount)),
                'creditor': {
                    'name': self._eh_clip(
                        payment.partner_id.display_name, 70,
                    ),
                    'iban': cdtr_iban,
                    'bic': cdtr_bic,
                },
                'remittance_info': self._eh_clip(
                    payment.memo or '', 140,
                ) or None,
            })

        return {
            'message_id': self._eh_sepa_msg_id(),
            'creation_datetime': datetime.utcnow(),
            'initiating_party': {
                'name': self._eh_clip(originator.initiating_party_name, 70),
                'identifier': self._eh_clip(
                    originator.initiating_party_identifier or '', 35,
                ) or None,
            },
            'payments': [
                {
                    'payment_info_id': self._eh_clip(
                        self.name.replace('/', '-'), 35,
                    ),
                    'requested_execution_date': fields.Date.from_string(
                        fields.Date.to_string(self.payment_date),
                    ),
                    'debtor': {
                        'name': self._eh_clip(
                            originator.initiating_party_name, 70,
                        ),
                        'iban': dbtr_iban,
                        'bic': dbtr_bic,
                    },
                    'transactions': transactions,
                },
            ],
        }

    def _eh_resolve_creditor_bank(self, payment):
        """Pick the bank account the SEPA file should pay into.

        Rules, in order:
        * payment.partner_bank_id when set explicitly on the payment.
        * Otherwise the first bank account on the partner whose IBAN
          validates locally.

        Raises a clear UserError when no IBAN bank account exists. We
        do NOT silently fall through to a non-IBAN account; the bank
        rejects those, so naming the issue early is more useful.
        """
        self.ensure_one()
        if payment.partner_bank_id:
            return payment.partner_bank_id
        partner = payment.partner_id
        for bank in partner.bank_ids:
            try:
                validate_iban(bank.acc_number)
            except IbanValidationError:
                continue
            return bank
        raise UserError(_(
            "Payment %(name)s: partner %(partner)s has no IBAN bank "
            "account on file. Add one before exporting SEPA.",
            name=payment.display_name,
            partner=partner.display_name,
        ))

    @staticmethod
    def _eh_clip(value, max_length):
        if not value:
            return value
        return sanitize_sepa_text(value)[:max_length]

    def _eh_sepa_msg_id(self):
        """Globally unique SEPA MsgId (max 35 chars): a short sanitised
        batch name, a UTC-clock timestamp, and a uuid fragment so two
        exports in the same second never collide. The name part is capped
        so the length limit can never truncate the uuid.
        """
        self.ensure_one()
        name_part = sanitize_sepa_text(
            (self.name or 'EH').replace('/', '-'),
        )[:11]
        ts = fields.Datetime.now().strftime('%Y%m%d%H%M%S')
        return ("%s-%s-%s" % (name_part, ts, uuid.uuid4().hex[:8]))[:35]

    def _eh_persist_sepa_attachment(self, payload, xml_bytes):
        self.ensure_one()
        filename = "%s_%s.xml" % (
            self.name.replace('/', '_'),
            fields.Datetime.now().strftime('%Y%m%d%H%M%S'),
        )
        return self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(xml_bytes),
            'mimetype': 'application/xml',
            'res_model': self._name,
            'res_id': self.id,
        })
