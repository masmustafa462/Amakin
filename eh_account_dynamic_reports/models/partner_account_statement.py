# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
Customer / vendor account statement.

The same report as the General Ledger (per account: opening balance, every
journal item of the period with date, journal, entry, partner, label, debit,
credit, running balance and amount in currency, then the account total),
limited to ONE condition the user must set: the customer(s) or vendor(s)
chosen in the Partner filter.

Only the receivable and payable accounts are listed unless the user picks
accounts explicitly, so the statement reads as the partner's account with the
company. Everything else (lazy expansion, running balance, paging, currency
column, PDF / XLSX export) is inherited from the General Ledger handler.
"""

import re

from odoo import _, api, fields, models
from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate(__name__)

_PARTNER_ACCOUNT_TYPES = ('asset_receivable', 'liability_payable')

_AR_VARIANTS = str.maketrans({
    '\u0623': '\u0627', '\u0625': '\u0627', '\u0622': '\u0627',
    '\u0629': '\u0647', '\u0649': '\u064a',
})
_AR_DIACRITICS = re.compile('[\u064b-\u0652\u0640]')


def _normalize(text):
    """Fold Arabic spelling variants (hamza forms, ta marbuta, alef maksura,
    tashkeel) so a search matches however the name was typed."""
    return _AR_DIACRITICS.sub('', str(text or '')).translate(
        _AR_VARIANTS).lower()


class EhPartnerAccountStatementHandler(models.AbstractModel):
    _name = 'eh.account.dynamic.report.handler.partner_account_statement'
    _inherit = 'eh.account.dynamic.report.handler.general_ledger'
    _description = "Customer / vendor account statement handler"

    REPORT_CODE = 'partner_account_statement'
    REPORT_NAME = _lt("Customer / Vendor Account Statement")

    # ---- scope ----

    @api.model
    def _statement_options(self, options):
        """Options with the receivable / payable accounts applied when the
        user did not pick accounts. Never mutates the caller's dict."""
        scoped = dict(options or {})
        if not scoped.get('account_ids'):
            domain = [('account_type', 'in', _PARTNER_ACCOUNT_TYPES)]
            company_ids = scoped.get('company_ids')
            if company_ids:
                domain.append(('company_ids', 'in', [
                    int(c) for c in company_ids]))
            scoped['account_ids'] = self.env['account.account'].search(
                domain).ids or [0]
        return scoped

    @api.model
    def _partner_names(self, options):
        ids = [int(p) for p in (options.get('partner_ids') or [])]
        if not ids:
            return ''
        return ', '.join(
            self.env['res.partner'].browse(ids).exists().mapped('name'))

    # ---- handler API ----

    @api.model
    def statement_partner_choices(self, term='', limit=300):
        """Partners that have at least one receivable / payable journal item
        (customers, vendors and any other partner with a financial
        transaction on those accounts), for the statement's partner picker.
        `term` narrows by name; the result is [{'id', 'name'}] by name."""
        domain = [
            ('partner_id', '!=', False),
            ('parent_state', '!=', 'cancel'),
            ('account_id.account_type', 'in', _PARTNER_ACCOUNT_TYPES),
        ]
        term = (term or '').strip()
        if term:
            domain.append(('partner_id.name', 'ilike', term))
        groups = self.env['account.move.line']._read_group(
            domain, groupby=['partner_id'], order='partner_id',
            limit=int(limit or 300))
        return [{'id': partner.id, 'name': partner.display_name}
                for (partner,) in groups if partner]

    @api.model
    def _account_names(self, options):
        ids = [int(a) for a in (options.get('account_ids') or [])]
        if not ids:
            return ''
        return ', '.join(
            ('%s %s' % (acc.code or '', acc.name or '')).strip()
            for acc in self.env['account.account'].browse(ids).exists())

    @api.model
    def statement_account_choices(self, term='', limit=200):
        """Accounts for the statement's account picker, by account number or
        any part of the name. Every word typed must match the code or the
        name; Arabic spelling variants are folded when nothing matches."""
        Account = self.env['account.account']
        limit = int(limit or 200)
        words = (term or '').split()
        domain = []
        for word in words:
            domain += ['|', ('code', 'ilike', word), ('name', 'ilike', word)]
        found = Account.search(domain, order='code', limit=limit)
        if words and not found:
            wanted = [_normalize(w) for w in words]
            found = Account.search([], order='code', limit=5000).filtered(
                lambda a: all(
                    w in _normalize('%s %s' % (a.code, a.name))
                    for w in wanted))[:limit]
        return [{'id': a.id, 'code': a.code or '', 'name': a.name or ''}
                for a in found]

    @api.model
    def compute(self, options):
        if not (options.get('partner_ids') or options.get('account_ids')):
            return self._empty_payload(options)
        payload = super().compute(self._statement_options(options))
        meta = payload.setdefault('meta', {})
        meta['report_code'] = self.REPORT_CODE
        meta['partner_names'] = self._partner_names(options)
        meta['account_names'] = self._account_names(options)
        return payload

    @api.model
    def expand_account_line(self, options, line_id, offset=0, limit=None):
        return super().expand_account_line(
            self._statement_options(options), line_id,
            offset=offset, limit=limit)

    @api.model
    def get_drilldown_action(self, options, line_id):
        return super().get_drilldown_action(
            self._statement_options(options), line_id)

    @api.model
    def _empty_payload(self, options):
        """No partner or account chosen yet: one instruction row instead of an error,
        so opening the menu never shows a failure dialog."""
        date_from = self._extract_date(options, 'date_from')
        date_to = self._extract_date(options, 'date_to')
        company_ids = options.get('company_ids') or [self.env.company.id]
        columns = self._build_columns()
        notice = {
            'id': 'notice-select-scope',
            'name': _(
                "Select a customer / vendor or an account in the report "
                "conditions to show the account statement."),
            'level': 0,
            'columns': [
                {'expression_label': c['expression_label'], 'value': ''}
                for c in columns
            ],
            'unfoldable': False,
            'meta': {'kind': 'notice'},
        }
        return {
            'columns': columns,
            'lines': [notice],
            'totals': {},
            'generated_at': fields.Datetime.now().isoformat(),
            'meta': {
                'report_code': self.REPORT_CODE,
                'date_from': self._iso_date(date_from),
                'date_to': self._iso_date(date_to),
                'company_ids': sorted(int(c) for c in company_ids),
                'posted_only': bool(options.get('posted_only', True)),
                'partner_names': '',
                'account_names': '',
            },
        }
