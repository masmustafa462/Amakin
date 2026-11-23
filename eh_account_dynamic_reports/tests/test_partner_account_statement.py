# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Customer / vendor account statement: General Ledger layout scoped to the
partner chosen in the Partner filter, on receivable / payable accounts."""

from odoo import fields
from odoo.tests import tagged

from odoo.addons.eh_account_base.tests.common import EhAccountIntegrationTestCase


@tagged('eh_account_dynamic_reports', 'integration', 'post_install', '-at_install')
class TestPartnerAccountStatement(EhAccountIntegrationTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.handler = cls.env[
            'eh.account.dynamic.report.handler.partner_account_statement']
        cls.partner_x = cls.env['res.partner'].create({'name': 'Stmt X'})
        cls.partner_y = cls.env['res.partner'].create({'name': 'Stmt Y'})
        date = fields.Date.from_string('2026-06-15')
        for partner, amount in ((cls.partner_x, 100.0), (cls.partner_y, 40.0)):
            cls.post_balanced_move([
                {'account': cls.account_receivable, 'debit': amount,
                 'partner': partner},
                {'account': cls.account_revenue, 'credit': amount},
            ], date=date)

    def setUp(self):
        super().setUp()
        self.options = {
            'date': {'date_from': '2026-01-01', 'date_to': '2026-12-31'},
            'company_ids': [self.company.id],
            'posted_only': True,
        }

    def test_without_partner_returns_instruction_row(self):
        result = self.handler.compute(self.options)
        kinds = [(l.get('meta') or {}).get('kind') for l in result['lines']]
        self.assertEqual(kinds, ['notice'])

    def test_lists_only_selected_partner_on_partner_accounts(self):
        result = self.handler.compute(
            dict(self.options, partner_ids=[self.partner_x.id]))
        entries = [l for l in result['lines']
                   if (l.get('meta') or {}).get('kind') == 'aml']
        self.assertEqual(len(entries), 1)
        cells = {c['expression_label']: c['value']
                 for c in entries[0]['columns']}
        self.assertEqual(cells['partner'], 'Stmt X')
        accounts = {(l.get('meta') or {}).get('account_id')
                    for l in result['lines']}
        self.assertNotIn(self.account_revenue.id, accounts)
        self.assertEqual(result['meta']['partner_names'], 'Stmt X')

    def test_same_columns_as_general_ledger(self):
        gl = self.env['eh.account.dynamic.report.handler.general_ledger']
        self.assertEqual(
            [c['expression_label'] for c in self.handler._build_columns()],
            [c['expression_label'] for c in gl._build_columns()])
