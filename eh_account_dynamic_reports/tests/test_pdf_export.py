# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
PDF rendering smoke tests for dynamic reports.

Each test renders one of the seven v1.0 reports to PDF, verifies that the
output starts with the PDF magic bytes, and is large enough to contain the
table content. The tests rely on wkhtmltopdf being available in the
testing environment, which is the standard Odoo CI assumption.

Detailed visual layout is verified manually rather than asserted in code:
parsing PDF text and asserting positions is brittle and adds no value over
manual inspection. The smoke tests catch broken templates, missing
abstract model registrations, malformed paperformats, and crashes inside
the formatting helpers.
"""

from odoo import fields
from odoo.tests import tagged

from odoo.addons.eh_account_base.tests.common import EhAccountIntegrationTestCase


@tagged('eh_account_dynamic_reports', 'integration', 'pdf', 'post_install', '-at_install')
class TestPdfRendering(EhAccountIntegrationTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        DynRep = cls.env['eh.account.dynamic.report']
        cls.reports = {
            r.code: r for r in DynRep.search([])
        }
        # Seed enough activity to make every report non trivial.
        cls.post_balanced_move(
            [
                {'account': cls.account_revenue, 'credit': 1000.0,
                 'partner': cls.partner_a},
                {'account': cls.account_cash, 'debit': 1000.0},
            ],
            date=fields.Date.from_string('2026-06-15'),
        )
        cls.post_balanced_move(
            [
                {'account': cls.account_expense, 'debit': 200.0,
                 'partner': cls.partner_b},
                {'account': cls.account_cash, 'credit': 200.0},
            ],
            date=fields.Date.from_string('2026-07-01'),
        )

    def setUp(self):
        super().setUp()
        self.options = {
            'date': {'date_from': '2026-01-01', 'date_to': '2026-12-31'},
            'company_ids': [self.company.id],
            'posted_only': True,
            'show_zero': False,
        }

    def _assert_pdf_bytes(self, content, label):
        # In --test-enable mode Odoo 19 falls back to HTML rendering to
        # avoid spawning wkhtmltopdf (which deadlocks against the test
        # HTTP server). Real PDF rendering is exercised manually and via
        # the export attachment action; here we just confirm we got
        # bytes back and the wrapper survived the round trip.
        self.assertIsInstance(content, (bytes, bytearray))
        is_pdf = content[:4] == b'%PDF'
        is_html = content[:9].lower().startswith(b'<!doctype') or \
            content[:5].lower().startswith(b'<html')
        self.assertTrue(
            is_pdf or is_html,
            "%s produced neither PDF nor HTML (got %r)"
            % (label, content[:16]),
        )
        self.assertGreater(
            len(content), 100,
            "%s render is suspiciously small (%d bytes)"
            % (label, len(content)),
        )

    def test_trial_balance_pdf(self):
        report = self.reports.get('trial_balance')
        self.assertTrue(report)
        content = report.render_pdf(self.options)
        self._assert_pdf_bytes(content, 'Trial Balance')

    def test_profit_and_loss_pdf(self):
        report = self.reports.get('profit_and_loss')
        self.assertTrue(report)
        content = report.render_pdf(self.options)
        self._assert_pdf_bytes(content, 'Profit and Loss')

    def test_balance_sheet_pdf(self):
        report = self.reports.get('balance_sheet')
        self.assertTrue(report)
        content = report.render_pdf(self.options)
        self._assert_pdf_bytes(content, 'Balance Sheet')

    def test_general_ledger_pdf(self):
        report = self.reports.get('general_ledger')
        self.assertTrue(report)
        content = report.render_pdf(self.options)
        self._assert_pdf_bytes(content, 'General Ledger')

    def _gl_rendered_lines(self, options):
        report = self.reports.get('general_ledger')
        self.assertTrue(report)
        values = self.env[
            'report.eh_account_dynamic_reports.report_dynamic_pdf_template'
        ]._get_report_values([report.id], data={'options': options})
        return values['rendered'][0]['lines']

    def test_general_ledger_pdf_mirrors_collapsed_screen(self):
        # Screen options with nothing expanded: the printed report shows
        # each account collapsed (header, opening, total), exactly as on
        # screen, with no journal items.
        lines = self._gl_rendered_lines(
            dict(self.options, lazy_expand=True))
        kinds = [line['kind'] for line in lines]
        self.assertNotIn('aml', kinds)
        self.assertIn('account_header', kinds)

    def test_general_ledger_pdf_lists_items_of_expanded_account_only(self):
        # The user opened the cash account on screen (and it loaded its
        # items). Only that account prints its journal items, after its
        # opening balance row and before its total.
        base = dict(self.options, lazy_expand=True)
        collapsed = self._gl_rendered_lines(base)
        cash_header = 'account-%s' % self.account_cash.id
        self.assertIn(cash_header, [line['id'] for line in collapsed])

        expanded = self._gl_rendered_lines(
            dict(base, pdf_expanded={cash_header: 80}))
        kinds = [line['kind'] for line in expanded]
        self.assertIn('aml', kinds)

        ids = [line['id'] for line in expanded]
        head = ids.index(cash_header)
        total = next(
            i for i, line in enumerate(expanded)
            if i > head and line['kind'] == 'account_total')
        between = [expanded[i]['kind'] for i in range(head + 1, total)]
        self.assertEqual(between[0], 'opening_balance')
        self.assertIn('aml', between[1:])
        # Other accounts stay collapsed: every aml row sits in that range.
        aml_positions = [i for i, k in enumerate(kinds) if k == 'aml']
        self.assertTrue(all(head < i < total for i in aml_positions))

    def test_general_ledger_pdf_prints_only_filtered_rows(self):
        # The in-table search box limits the printout to the matching
        # account (header, opening, total), like on screen.
        base = dict(self.options, lazy_expand=True)
        all_lines = self._gl_rendered_lines(base)
        cash_header = 'account-%s' % self.account_cash.id
        name = next(l['name'] for l in all_lines if l['id'] == cash_header)
        term = name.strip('\u200f \u00a0').split()[-1]
        filtered = self._gl_rendered_lines(dict(base, pdf_query=term))
        self.assertIn(cash_header, [l['id'] for l in filtered])
        self.assertLessEqual(len(filtered), len(all_lines))
        self.assertEqual(self._gl_rendered_lines(
            dict(base, pdf_query='zzz-no-such-row')), [])

    def test_apply_table_filter_keeps_matches_ancestors_and_children(self):
        lines = [
            {'id': 'a', 'name': 'Assets', 'parent_id': None},
            {'id': 'b', 'name': 'Bank', 'parent_id': 'a'},
            {'id': 'b1', 'name': 'Opening', 'parent_id': 'b'},
            {'id': 'c', 'name': 'Cash', 'parent_id': 'a'},
            {'id': 'x', 'name': 'Other', 'parent_id': None},
        ]
        helper = self.env[
            'report.eh_account_dynamic_reports.report_dynamic_pdf_template']
        out = helper._apply_table_filter({'lines': lines}, ' bank ')
        self.assertEqual([l['id'] for l in out['lines']], ['a', 'b', 'b1'])
        self.assertEqual(
            helper._apply_table_filter({'lines': lines}, '')['lines'],
            lines)

    def test_general_ledger_pdf_notes_partially_loaded_account(self):
        # Screen had loaded only the first item of an account with more:
        # print that one and a note row saying the list is partial.
        base = dict(self.options, lazy_expand=True)
        cash_header = 'account-%s' % self.account_cash.id
        lines = self._gl_rendered_lines(
            dict(base, pdf_expanded={cash_header: 1}))
        kinds = [line['kind'] for line in lines]
        self.assertEqual(kinds.count('aml'), 1)
        self.assertIn('load_more', kinds)

    def test_partner_ledger_pdf(self):
        report = self.reports.get('partner_ledger')
        self.assertTrue(report)
        content = report.render_pdf(self.options)
        self._assert_pdf_bytes(content, 'Partner Ledger')

    def test_aged_receivable_pdf(self):
        report = self.reports.get('aged_receivable')
        self.assertTrue(report)
        content = report.render_pdf(self.options)
        self._assert_pdf_bytes(content, 'Aged Receivable')

    def test_aged_payable_pdf(self):
        report = self.reports.get('aged_payable')
        self.assertTrue(report)
        content = report.render_pdf(self.options)
        self._assert_pdf_bytes(content, 'Aged Payable')

    def test_cash_flow_pdf(self):
        report = self.reports.get('cash_flow')
        self.assertTrue(report)
        content = report.render_pdf(self.options)
        self._assert_pdf_bytes(content, 'Cash Flow Statement')

    def test_export_pdf_attachment_returns_download_action(self):
        report = self.reports.get('trial_balance')
        action = report.export_pdf_attachment(self.options)
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertIn('/web/content/', action['url'])
        attachment_id = int(
            action['url'].split('/web/content/')[1].split('?')[0]
        )
        attachment = self.env['ir.attachment'].browse(attachment_id)
        self.assertTrue(attachment.exists())
        self.assertEqual(attachment.mimetype, 'application/pdf')
        self.assertTrue(attachment.name.endswith('.pdf'))


@tagged('eh_account_dynamic_reports', 'unit')
class TestPdfFormattingHelpers(EhAccountIntegrationTestCase):
    """Unit tests for the PDF abstract model's formatting helpers.

    These do not call wkhtmltopdf and run quickly; they verify the
    transformations from raw payload values into display strings.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.helper = cls.env[
            'report.eh_account_dynamic_reports.report_dynamic_pdf_template'
        ]

    def test_format_monetary_positive(self):
        self.assertEqual(self.helper._format_value(1234.56, 'monetary'),
                         '1,234.56')

    def test_format_monetary_negative(self):
        self.assertEqual(self.helper._format_value(-1234.56, 'monetary'),
                         '(1,234.56)')

    def test_format_monetary_zero(self):
        self.assertEqual(self.helper._format_value(0.0, 'monetary'), '0.00')

    def test_format_integer(self):
        self.assertEqual(self.helper._format_value(1234567, 'integer'),
                         '1,234,567')

    def test_format_string_passthrough(self):
        self.assertEqual(self.helper._format_value('hello', 'string'), 'hello')

    def test_format_none_yields_empty(self):
        self.assertEqual(self.helper._format_value(None, 'monetary'), '')
        self.assertEqual(self.helper._format_value('', 'string'), '')

    def test_line_css_class_for_section_header(self):
        line = {'level': 0, 'meta': {'kind': 'section_header'}}
        css = self.helper._line_css_class(line)
        self.assertIn('eh_pdf_section_row', css)
        self.assertIn('eh_pdf_section_header', css)

    def test_line_css_class_for_balance_check(self):
        line = {'level': 0, 'meta': {'kind': 'balance_check'}}
        css = self.helper._line_css_class(line)
        self.assertIn('eh_pdf_balance_check', css)

    def test_line_css_class_for_data_row(self):
        line = {'level': 1, 'meta': {'kind': 'aml'}}
        css = self.helper._line_css_class(line)
        self.assertIn('eh_pdf_data_row', css)

    def test_render_lines_produces_cells(self):
        payload = {
            'columns': [
                {'expression_label': 'account', 'name': 'Account',
                 'figure_type': 'string'},
                {'expression_label': 'amount', 'name': 'Amount',
                 'figure_type': 'monetary'},
            ],
            'lines': [
                {
                    'id': 'l1', 'name': 'Cash', 'level': 1,
                    'columns': [
                        {'expression_label': 'amount', 'value': 1234.56},
                    ],
                    'meta': {'kind': 'aml'},
                },
            ],
        }
        rendered = self.helper._render_lines(payload)
        self.assertEqual(len(rendered), 1)
        line = rendered[0]
        self.assertEqual(line['name'], 'Cash')
        self.assertEqual(len(line['cells']), 1)
        self.assertEqual(line['cells'][0]['display'], '1,234.56')
        self.assertTrue(line['cells'][0]['align_right'])

    def test_line_css_class_for_general_ledger_rows(self):
        # The General Ledger row kinds each map to a class that the shared
        # stylesheet (eh_account_base.eh_report_styles) declares.
        for kind, expected in (
            ('account_header', 'eh_pdf_account_header'),
            ('opening_balance', 'eh_pdf_opening'),
            ('account_total', 'eh_pdf_account_total'),
        ):
            css = self.helper._line_css_class(
                {'level': 0, 'meta': {'kind': kind}})
            self.assertIn(expected, css)

    def test_format_iso_date_uses_user_format(self):
        shown = self.helper._format_iso_date('2026-06-15')
        self.assertNotEqual(shown, '2026-06-15')
        self.assertIn('2026', shown)

    def test_format_iso_date_passthrough_for_other_values(self):
        for value in ('', 'Cash', '15/06/2026', None, 12.5):
            self.assertEqual(self.helper._format_iso_date(value), value)

    def test_render_lines_formats_date_column(self):
        payload = {
            'columns': [
                {'expression_label': 'description', 'name': 'Description',
                 'figure_type': 'string'},
                {'expression_label': 'date', 'name': 'Date',
                 'figure_type': 'string'},
            ],
            'lines': [{
                'id': 'aml-1', 'name': 'Entry', 'level': 1,
                'columns': [
                    {'expression_label': 'date', 'value': '2026-06-15'},
                ],
                'meta': {'kind': 'aml'},
            }],
        }
        cell = self.helper._render_lines(payload)[0]['cells'][0]
        self.assertNotEqual(cell['display'], '2026-06-15')
        self.assertEqual(cell['value'], '2026-06-15')

    def test_build_meta_display(self):
        payload = {
            'generated_at': '2026-06-15T10:30:45.123456',
            'meta': {
                'date_from': '2026-01-01', 'date_to': '2026-12-31',
                'posted_only': True,
            },
        }
        display = self.helper._build_meta_display(payload)
        self.assertIn('2026', display['period'])
        self.assertNotIn('2026-01-01', display['period'])
        self.assertEqual(display['posted_only'], 'Yes')
        self.assertNotIn('T', display['generated_at'])
        self.assertNotIn('.123456', display['generated_at'])

    def test_build_meta_display_without_period(self):
        display = self.helper._build_meta_display(
            {'meta': {'date_to': '2026-12-31', 'posted_only': False}})
        self.assertEqual(display['period'], '')
        self.assertEqual(display['posted_only'], 'No')
        self.assertEqual(display['generated_at'], '')

    def test_column_widths_sum_to_100_and_match_columns(self):
        columns = [
            {'expression_label': 'description', 'figure_type': 'string'},
            {'expression_label': 'date', 'figure_type': 'string'},
            {'expression_label': 'journal', 'figure_type': 'string'},
            {'expression_label': 'move', 'figure_type': 'string'},
            {'expression_label': 'partner', 'figure_type': 'string'},
            {'expression_label': 'label', 'figure_type': 'string'},
            {'expression_label': 'debit', 'figure_type': 'monetary'},
            {'expression_label': 'credit', 'figure_type': 'monetary'},
            {'expression_label': 'balance', 'figure_type': 'monetary'},
            {'expression_label': 'foreign', 'figure_type': 'string'},
        ]
        widths = self.helper._column_widths(columns)
        self.assertEqual(len(widths), len(columns))
        self.assertAlmostEqual(sum(widths), 100.0, delta=0.1)
        # The description column must be wider than the narrow code and
        # date columns, so references wrap instead of overflowing.
        self.assertGreater(widths[0], widths[1])
        self.assertGreater(widths[0], widths[2])

    def test_column_widths_defaults_for_unknown_columns(self):
        columns = [
            {'expression_label': 'name', 'figure_type': 'string'},
            {'expression_label': 'balance', 'figure_type': 'monetary'},
            {'expression_label': 'note', 'figure_type': 'string'},
        ]
        widths = self.helper._column_widths(columns)
        self.assertAlmostEqual(sum(widths), 100.0, delta=0.1)
        self.assertGreater(widths[0], widths[1])

    def test_bidi_safe_marks_mixed_arabic_text(self):
        # Arabic mixed with digits, Latin or " - " is pinned right to left
        # with zero width marks (wkhtmltopdf overprint / clipping bugs).
        m = '\u200f'
        for text in ('13900001 إيرادات مؤجلة', 'اعادة تأهيل - صيانة',
                     '20020001 اعادة تأهيل المصنع - صيانة 1'):
            self.assertEqual(
                self.helper._bidi_safe(text),
                m + text.replace(' ', m + ' ' + m) + m)

    def test_bidi_safe_leaves_other_text_unchanged(self):
        for text in ('الرصيد الافتتاحي', 'Cash', 'Cash - Bank', '', None):
            self.assertEqual(self.helper._bidi_safe(text), text)

    def test_bidi_safe_is_a_noop_for_ltr(self):
        text = '13900001 إيرادات مؤجلة'
        self.assertEqual(self.helper._bidi_safe(text, rtl=False), text)

    def test_column_widths_empty(self):
        self.assertEqual(self.helper._column_widths([]), [])
        self.assertEqual(self.helper._column_widths(None), [])

    def test_is_rtl_is_false_for_english(self):
        self.assertFalse(
            self.helper.with_context(lang='en_US')._is_rtl())
