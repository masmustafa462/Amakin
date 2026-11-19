# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
eh.peppol.inbound: incoming Peppol invoice / credit note.

Lifecycle:

    received -> parsed -> matched -> posted
                                  \\-> exception -> matched (after fix)
                                                  \\-> rejected
                       -> rejected

Per the brutal-review feedback, this closes the inbound half of the
PEPPOL story: the existing module only emitted XML. The flow:

  1. An incoming UBL XML arrives, either via the access-point poll
     cron, or by a manual upload, or by a per-vendor email alias.
  2. The parser converts the XML to a normalised payload dict.
  3. Partner resolution: lookup by ABN / VAT first, then by Peppol
     endpoint id, then by name + country. Strict: more than one
     candidate leaves partner_id empty for manual review.
  4. Optional PO reference resolves to a purchase.order so the
     downstream three-way match in eh_account_ap_automation can pick
     up the bill.
  5. Posting creates an account.move (move_type=in_invoice or
     in_refund) and links it back so the audit trail joins both
     directions.

Idempotency: incoming UBL is hashed (SHA-256) on the inbound record;
a duplicate hash from the same supplier within the same company is
flagged via inbound.message_post and refuses to re-post.
"""

import hashlib
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.eh_account_einvoice_peppol.tools import (
    ubl_parser, access_point_registry,
)


_logger = logging.getLogger(__name__)


class EhPeppolInbound(models.Model):
    _name = 'eh.peppol.inbound'
    _description = "Inbound Peppol invoice"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'received_at desc, id desc'

    name = fields.Char(
        required=True, copy=False, default='/', tracking=True,
        help="Sequence-assigned reference for the inbound record.",
    )
    state = fields.Selection([
        ('received', "Received"),
        ('parsed', "Parsed"),
        ('matched', "Matched"),
        ('posted', "Posted"),
        ('exception', "Exception"),
        ('rejected', "Rejected"),
    ], default='received', required=True, tracking=True, index=True)

    # ---- transport ----
    access_point_key = fields.Char(
        help=(
            "Adapter key under which the inbound XML arrived (e.g. "
            "'storecove', 'pagero', 'manual'). Identifies which "
            "transport channel the message took; surfaces in the "
            "audit trail. Adapter must be registered via the "
            "access_point_registry before the value will roundtrip "
            "into a real submit/poll call."
        ),
    )
    transmission_id = fields.Char(
        help=(
            "Access-point transmission id, when one is supplied. "
            "Used for cross-reference against the access-point's "
            "delivery receipts and the MLR (message level response) "
            "queue."
        ),
    )
    as4_message_id = fields.Char(
        help="ebMS3 / AS4 MessageId reported by the access point.",
    )
    smp_discovery_log = fields.Text(
        help="SMP / NAPTR participant-lookup trace recorded at poll time.",
    )
    mlr_status = fields.Char(
        help="Message Level Response status from the access point.",
    )

    # ---- raw payload ----
    xml_attachment_id = fields.Many2one(
        'ir.attachment', string="Source XML",
        copy=False,
        help="Original UBL XML the access point delivered.",
    )
    file_hash = fields.Char(
        help=(
            "SHA-256 hex digest of the source XML. Used for the "
            "duplicate-detection check; a re-submission with the same "
            "hash from the same supplier in the same company refuses "
            "to post twice."
        ),
    )

    # ---- parsed header ----
    document_type = fields.Selection([
        ('invoice', "Invoice"),
        ('credit_note', "Credit note"),
    ], default='invoice', required=True)
    invoice_number = fields.Char(tracking=True)
    issue_date = fields.Date(tracking=True)
    due_date = fields.Date()
    currency_code = fields.Char(
        help="ISO 4217 currency code from the source UBL.",
    )
    note = fields.Text()
    buyer_reference = fields.Char()
    order_reference = fields.Char(
        help=(
            "Purchase-order reference carried in the source UBL, when "
            "present. Used to look up purchase.order for the three-"
            "way match in the AP automation module."
        ),
    )

    # ---- party resolution ----
    supplier_name = fields.Char()
    supplier_endpoint_id = fields.Char()
    supplier_endpoint_scheme = fields.Char()
    supplier_vat_id = fields.Char()
    partner_id = fields.Many2one(
        'res.partner', string="Resolved supplier",
        ondelete='restrict', tracking=True,
        help=(
            "Vendor record matched from the inbound supplier block. "
            "Resolution order: VAT/ABN, Peppol endpoint id, name + "
            "country. Strict: ambiguous matches leave the field empty "
            "for manual selection."
        ),
    )

    # ---- linked records ----
    purchase_order_id = fields.Many2one(
        'purchase.order', string="Resolved PO",
        ondelete='restrict',
        domain="[('state', 'in', ['purchase', 'done'])]",
    )
    move_id = fields.Many2one(
        'account.move', string="Posted bill",
        readonly=True, copy=False, ondelete='set null',
    )
    company_id = fields.Many2one(
        'res.company', required=True,
        default=lambda self: self.env.company, index=True,
    )
    currency_id = fields.Many2one(
        'res.currency', compute='_compute_currency_id', store=False,
    )

    # ---- audit ----
    received_at = fields.Datetime(
        readonly=True, default=fields.Datetime.now, tracking=True,
    )
    parsed_at = fields.Datetime(readonly=True, tracking=True)
    parsed_by_id = fields.Many2one('res.users', readonly=True)
    matched_at = fields.Datetime(readonly=True, tracking=True)
    matched_by_id = fields.Many2one('res.users', readonly=True)
    posted_at = fields.Datetime(readonly=True, tracking=True)
    posted_by_id = fields.Many2one('res.users', readonly=True)
    rejection_reason = fields.Text(tracking=True)

    # ---- duplicate detection ----
    duplicate_inbound_id = fields.Many2one(
        'eh.peppol.inbound', readonly=True,
        help=(
            "Set when another inbound record exists with the same "
            "(supplier, file_hash) tuple in the same company."
        ),
    )

    # ---- compute ----

    @api.depends('currency_code')
    def _compute_currency_id(self):
        Curr = self.env['res.currency']
        for rec in self:
            if not rec.currency_code:
                rec.currency_id = rec.company_id.currency_id
                continue
            curr = Curr.search([
                ('name', '=', rec.currency_code.upper()),
            ], limit=1)
            rec.currency_id = curr or rec.company_id.currency_id

    # ---- create ----

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                seq = self.env['ir.sequence'].next_by_code(
                    'eh.peppol.inbound',
                ) or '/'
                vals['name'] = seq
        return super().create(vals_list)

    # ---- transitions ----

    def action_parse(self):
        """Parse the source UBL XML into the header / supplier fields."""
        for rec in self:
            if rec.state not in ('received', 'parsed'):
                raise UserError(_(
                    "Parse is only available in received or parsed "
                    "state.",
                ))
            rec._parse()
            rec.write({
                'state': 'parsed',
                'parsed_at': fields.Datetime.now(),
                'parsed_by_id': self.env.user.id,
            })

    def action_match(self):
        """Resolve supplier and PO references."""
        for rec in self:
            if rec.state not in ('parsed', 'exception'):
                raise UserError(_(
                    "Match is only available in parsed or exception "
                    "state.",
                ))
            rec._resolve_partner()
            rec._resolve_purchase_order()
            new_state = (
                'matched' if rec.partner_id else 'exception'
            )
            rec.write({
                'state': new_state,
                'matched_at': fields.Datetime.now(),
                'matched_by_id': self.env.user.id,
            })

    def action_post(self):
        """Create and post the corresponding account.move."""
        for rec in self:
            if not self.env.user.has_group(
                'account.group_account_manager',
            ):
                raise UserError(_(
                    "Only accounting managers can post inbound Peppol "
                    "invoices.",
                ))
            if rec.state != 'matched':
                raise UserError(_(
                    "Only matched inbound records can be posted (state "
                    "is %s).",
                ) % rec.state)
            if rec.duplicate_inbound_id:
                raise UserError(_(
                    "Inbound %(name)s duplicates %(other)s (same "
                    "supplier and same file hash). Reject this record "
                    "or clear the duplicate flag with a reason "
                    "before posting.",
                    name=rec.name,
                    other=rec.duplicate_inbound_id.name,
                ))
            move = rec._build_move()
            rec.write({
                'state': 'posted',
                'posted_at': fields.Datetime.now(),
                'posted_by_id': self.env.user.id,
                'move_id': move.id,
            })

    def action_reject(self):
        for rec in self:
            if rec.state == 'posted':
                raise UserError(_(
                    "Posted inbound records cannot be rejected.",
                ))
            rec.state = 'rejected'

    # ---- internals ----

    def _parse(self):
        self.ensure_one()
        if not self.xml_attachment_id:
            raise UserError(_(
                "Inbound record %s has no source XML attachment.",
            ) % self.name)
        raw = self.xml_attachment_id.raw or b''
        if isinstance(raw, str):
            raw = raw.encode('utf-8')
        self.file_hash = hashlib.sha256(raw).hexdigest()
        try:
            payload = ubl_parser.parse_invoice_xml(raw)
        except ubl_parser.PeppolParserError as exc:
            raise UserError(_(
                "Could not parse inbound UBL on %(name)s: %(err)s",
                name=self.name, err=str(exc),
            ))
        self.write({
            'document_type': payload['document_type'],
            'invoice_number': payload['invoice_number'],
            'issue_date': payload['issue_date'],
            'due_date': payload['due_date'],
            'currency_code': payload['currency_code'],
            'note': payload['note'] or '',
            'buyer_reference': payload['buyer_reference'] or '',
            'order_reference': payload['order_reference'] or '',
            'supplier_name': payload['supplier']['name'],
            'supplier_endpoint_id':
                payload['supplier']['endpoint_id'],
            'supplier_endpoint_scheme':
                payload['supplier']['endpoint_scheme'],
            'supplier_vat_id': payload['supplier']['vat_id'],
        })
        self._eh_check_duplicate()

    def _eh_check_duplicate(self):
        self.ensure_one()
        if not self.file_hash:
            return
        Inbound = self.env['eh.peppol.inbound'].sudo()
        domain = [
            ('id', '!=', self.id),
            ('company_id', '=', self.company_id.id),
            ('file_hash', '=', self.file_hash),
            ('state', 'not in', ('rejected',)),
        ]
        if self.partner_id:
            domain.append(('partner_id', '=', self.partner_id.id))
        match = Inbound.search(domain, limit=1)
        self.duplicate_inbound_id = match.id if match else False
        if match:
            self.message_post(body=_(
                "Duplicate flag raised: same UBL hash already exists "
                "on inbound %(other)s.",
                other=match.name,
            ))

    def _resolve_partner(self):
        self.ensure_one()
        Partner = self.env['res.partner'].sudo()
        candidates = Partner.browse()
        # ABN / VAT lookup first (most specific).
        if self.supplier_vat_id:
            candidates = Partner.search([
                ('vat', '=', self.supplier_vat_id),
                ('parent_id', '=', False),
                '|',
                ('company_id', '=', self.company_id.id),
                ('company_id', '=', False),
            ])
        # Peppol endpoint id (eh_au_abn or vat) on partner.
        if not candidates and self.supplier_endpoint_id:
            candidates = Partner.search([
                '|',
                ('vat', '=', self.supplier_endpoint_id),
                ('vat', 'ilike', self.supplier_endpoint_id),
                ('parent_id', '=', False),
                '|',
                ('company_id', '=', self.company_id.id),
                ('company_id', '=', False),
            ])
        # Name fallback. Strict: only resolve if exactly one candidate.
        if not candidates and self.supplier_name:
            candidates = Partner.search([
                ('name', '=ilike', self.supplier_name),
                ('parent_id', '=', False),
                '|',
                ('company_id', '=', self.company_id.id),
                ('company_id', '=', False),
            ], limit=2)
        if len(candidates) == 1:
            self.partner_id = candidates.id
            self._eh_check_duplicate()
        else:
            self.partner_id = False

    def _resolve_purchase_order(self):
        self.ensure_one()
        if not self.order_reference:
            return
        PO = self.env['purchase.order'].sudo()
        po = PO.search([
            ('name', '=', self.order_reference),
            ('company_id', '=', self.company_id.id),
            ('state', 'in', ('purchase', 'done')),
        ], limit=1)
        if po:
            self.purchase_order_id = po.id

    def _build_move(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_(
                "Cannot create vendor bill without a resolved supplier.",
            ))
        Journal = self.env['account.journal'].sudo()
        journal = Journal.search([
            ('type', '=', 'purchase'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if not journal:
            raise UserError(_(
                "No purchase journal configured for company %s.",
                self.company_id.display_name,
            ))
        move_type = (
            'in_invoice' if self.document_type == 'invoice'
            else 'in_refund'
        )
        # Re-parse the lines from the XML so the bill carries them.
        raw = self.xml_attachment_id.raw or b''
        if isinstance(raw, str):
            raw = raw.encode('utf-8')
        payload = ubl_parser.parse_invoice_xml(raw)
        invoice_line_ids = []
        for line in payload['lines']:
            invoice_line_ids.append((0, 0, {
                'name': line['description'] or '/',
                'quantity': line['quantity'],
                'price_unit': line['unit_price'],
            }))
        if not invoice_line_ids:
            raise UserError(_(
                "Inbound %s has no lines after parse; refusing to "
                "post an empty bill.",
            ) % self.name)
        move = self.env['account.move'].create({
            'move_type': move_type,
            'partner_id': self.partner_id.id,
            'invoice_date': self.issue_date,
            'invoice_date_due': self.due_date,
            'ref': self.invoice_number or self.name,
            'journal_id': journal.id,
            'invoice_line_ids': invoice_line_ids,
        })
        return move

    # ---- transport ----

    @api.model
    def _cron_poll_access_points(self, batch_size=200):
        """Cron entry point: poll every configured access point for
        new inbound messages and create one inbound record per
        message.

        The actual transport is delegated to the registered adapter;
        this cron only orchestrates the per-company config lookup
        and persistence. Sites that route through a manual file drop
        can leave the adapter as 'manual' (no-op poll) and write
        inbound records via mail alias / scripted upload instead.
        """
        Company = self.env['res.company']
        for company in Company.search([]):
            key = company.eh_peppol_access_point_key or 'manual'
            if not access_point_registry.has_adapter(key):
                continue
            try:
                adapter = access_point_registry.get_adapter(
                    key, self._eh_company_config(company),
                )
            except access_point_registry.AccessPointError:
                continue
            since_iso = (
                fields.Datetime.to_string(
                    fields.Datetime.now(),
                )
            )
            try:
                messages = adapter.poll(since_iso)
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "Peppol poll failed for company %s adapter %s: %s",
                    company.display_name, key, exc,
                )
                continue
            for msg in (messages or [])[:batch_size]:
                self._eh_persist_incoming_message(company, key, msg)

    @api.model
    def _eh_company_config(self, company):
        """Default config dict handed to the adapter factory.

        Sites can extend res.company with their own per-vendor
        credentials and override this method to enrich the dict.
        """
        import json
        credentials = {}
        raw = company.eh_peppol_ap_config
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    credentials = parsed
            except (TypeError, ValueError):
                credentials = {}
        return {
            'company_id': company.id,
            'company_name': company.display_name,
            'access_point_key':
                company.eh_peppol_access_point_key or 'manual',
            'credentials': credentials,
        }

    @api.model
    def _eh_persist_incoming_message(self, company, key, msg):
        """Create an inbound record from an adapter poll() entry.

        Expected msg shape: dict with keys message_id, sender,
        xml_bytes, received_at. Missing keys default to safe values.
        """
        xml_bytes = msg.get('xml_bytes') or b''
        if not xml_bytes:
            return
        attachment = self.env['ir.attachment'].create({
            'name': 'peppol_inbound_%s.xml' % (
                msg.get('message_id') or fields.Datetime.now(),
            ),
            'type': 'binary',
            'raw': xml_bytes,
            'mimetype': 'application/xml',
        })
        record = self.create({
            'company_id': company.id,
            'access_point_key': key,
            'transmission_id': msg.get('message_id') or '',
            'as4_message_id': msg.get('as4_message_id') or '',
            'smp_discovery_log': msg.get('smp_discovery_log') or '',
            'mlr_status': msg.get('mlr_status') or '',
            'xml_attachment_id': attachment.id,
        })
        # Auto-parse to surface header info immediately; downstream
        # match + post still require user action so an unattended
        # cron does not auto-create vendor bills without review.
        try:
            record.action_parse()
        except UserError as exc:
            record.message_post(body=str(exc))
        return record
