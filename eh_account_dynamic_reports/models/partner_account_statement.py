# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
Account statement (كشف حساب).

The same report as the General Ledger (per account: opening balance, every
journal item of the period with date, journal, entry, partner, label, debit,
credit, running balance and amount in currency, then the account total),
limited to the account(s) the user must choose in the Account condition.
Lazy expansion, running balance, paging, currency column and PDF / XLSX
export are inherited from the General Ledger handler.

(The technical code stays `partner_account_statement` so existing installs
keep their report record and menu.)
"""

from odoo import _, api, fields, models
from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate(__name__)


class EhPartnerAccountStatementHandler(models.AbstractModel):
    _name = 'eh.account.dynamic.report.handler.partner_account_statement'
    _inherit = 'eh.account.dynamic.report.handler.general_ledger'
    _description = "Account statement handler"

    REPORT_CODE = 'partner_account_statement'
    REPORT_NAME = _lt("Account Statement")

    @api.model
    def _account_names(self, options):
        ids = [int(a) for a in (options.get('account_ids') or [])]
        if not ids:
            return ''
        return ', '.join(
            '%s %s' % (acc.code or '', acc.name or '')
            for acc in self.env['account.account'].browse(ids).exists())

    @api.model
    def compute(self, options):
        if not options.get('account_ids'):
            return self._empty_payload(options)
        payload = super().compute(options)
        meta = payload.setdefault('meta', {})
        meta['report_code'] = self.REPORT_CODE
        meta['account_names'] = self._account_names(options).strip()
        return payload

    @api.model
    def _empty_payload(self, options):
        """No partner chosen yet: one instruction row instead of an error,
        so opening the menu never shows a failure dialog."""
        date_from = self._extract_date(options, 'date_from')
        date_to = self._extract_date(options, 'date_to')
        company_ids = options.get('company_ids') or [self.env.company.id]
        columns = self._build_columns()
        notice = {
            'id': 'notice-select-partner',
            'name': _(
                "Select an account in the Account condition to show "
                "the account statement."),
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
                'account_names': '',
            },
        }
