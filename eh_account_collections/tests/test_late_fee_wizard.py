# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
Late-fee wizard tax tests.

A late-fee invoice is a tax invoice. In a GST-registered jurisdiction it
must carry output tax on the fee line; issuing it with no tax understates
output GST. These tests pin that the wizard applies the company's default
sale tax to the fee line, that an explicit tax selection wins, and that the
byte-identical no-tax fallback holds when the company configures no default.
"""

from datetime import date, timedelta

from odoo.tests import tagged

from odoo.addons.eh_account_base.tests.common import EhAccountIntegrationTestCase


@tagged('eh_account_collections', 'integration', 'post_install', '-at_install')
class TestLateFeeWizardTax(EhAccountIntegrationTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Case = cls.env['eh.collections.case']
        cls.Wizard = cls.env['eh.collections.late_fee.wizard']
        cls.Tax = cls.env['account.tax']
        # account.tax.country_id is NOT NULL on Odoo 16, and posting refuses a
        # tax whose country differs from the company fiscal country. Resolve a
        # single fiscal country, pin it on the company when blank, and stamp it
        # on every test tax.
        au_us = cls.env.ref('base.us')
        if not cls.company.country_id:
            cls.company.sudo().country_id = au_us.id
        cls._fiscal_country = (
            cls.company.account_fiscal_country_id
            or cls.company.country_id or au_us)
        # A 10% output (sale) tax standing in for GST.
        cls.gst = cls._make_sale_tax('GST 10% (test)', 10.0)

    @classmethod
    def _make_sale_tax(cls, name, amount):
        vals = {
            'name': name,
            'amount': amount,
            'amount_type': 'percent',
            'type_tax_use': 'sale',
            'company_id': cls.company.id,
        }
        if 'country_id' in cls.Tax._fields:
            vals['country_id'] = cls._fiscal_country.id
        return cls.Tax.create(vals)

    def _make_case(self, total=1000.0, days=45):
        return self.Case.create({
            'partner_id': self.partner_a.id,
            'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
            'total_overdue_amount': total,
            'oldest_overdue_date': date.today() - timedelta(days=days),
            'days_overdue_max': days,
        })

    def _make_wizard(self, case, **overrides):
        vals = {
            'case_id': case.id,
            'fee_mode': 'flat',
            'flat_amount': 50.0,
            'income_account_id': self.account_revenue.id,
            'journal_id': self.journal_sale.id,
        }
        vals.update(overrides)
        return self.Wizard.create(vals)

    def test_default_sale_tax_applied_to_fee_line(self):
        """With a company default sale tax set, the fee line carries it.

        This FAILS before the fix: the line was created with no tax_ids,
        so a GST-registered issuer produced a tax invoice with zero output
        tax.
        """
        self.company.account_sale_tax_id = self.gst
        case = self._make_case()
        wizard = self._make_wizard(case)
        action = wizard.action_apply()
        move = self.env['account.move'].browse(action['res_id'])
        fee_line = move.invoice_line_ids
        self.assertEqual(
            fee_line.tax_ids, self.gst,
            "Late-fee line must carry the company default sale tax so a "
            "GST-registered issuer charges output tax.",
        )
        # And the move actually accrues output tax on that base.
        self.assertGreater(
            move.amount_tax, 0.0,
            "A late-fee tax invoice must show non-zero output tax.",
        )

    def test_explicit_tax_selection_wins(self):
        other = self._make_sale_tax('GST 15% (test)', 15.0)
        self.company.account_sale_tax_id = self.gst
        case = self._make_case()
        wizard = self._make_wizard(case, tax_ids=[(6, 0, other.ids)])
        action = wizard.action_apply()
        move = self.env['account.move'].browse(action['res_id'])
        self.assertEqual(
            move.invoice_line_ids.tax_ids, other,
            "An explicit tax selection must override the company default.",
        )

    def test_no_default_tax_keeps_line_untaxed(self):
        """Byte-identical fallback: no company default sale tax means no tax.

        Pre-existing behaviour where the jurisdiction is not GST-registered
        (or the company simply has no default sale tax) must be unchanged.
        """
        self.company.account_sale_tax_id = False
        case = self._make_case()
        wizard = self._make_wizard(case)
        action = wizard.action_apply()
        move = self.env['account.move'].browse(action['res_id'])
        self.assertFalse(
            move.invoice_line_ids.tax_ids,
            "With no default sale tax and no explicit selection, the fee "
            "line must stay untaxed.",
        )
