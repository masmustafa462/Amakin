# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
PDF render values and helpers for dynamic report PDFs.

Two pieces in this module:

1. An AbstractModel `report.eh_account_dynamic_reports.report_dynamic_pdf_template`
   that Odoo's reporting machinery picks up automatically when the Qweb
   template of the same name runs. Its `_get_report_values` returns the
   structure the template iterates over.

2. A model extension on `eh.account.dynamic.report` that adds `render_pdf`
   and `export_pdf_attachment`. These mirror the XLSX equivalents and let
   the OWL viewer (or any other caller) get a printable artifact.

The shared formatting helpers (_format_value, _line_css_class) are kept on
the AbstractModel so they are easy to override per locality if needed.
Concrete handlers do not need to know about PDF rendering at all; they
return the standard payload shape, and the template plus this helper do
the rest.
"""

import base64
import re
from datetime import datetime

from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_date, format_datetime


_NUMERIC_FIGURE_TYPES = frozenset({
    'monetary', 'integer', 'float', 'percentage',
})

# A payload date value is an ISO "YYYY-MM-DD" string. Used to decide whether
# a cell in a "date" column can be rendered in the user's date format.
_ISO_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

# Arabic script blocks (Arabic, Supplement, Extended-A, Presentation Forms).
_ARABIC_CHAR_RE = re.compile(
    '[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]')
_LATIN_OR_DIGIT_RE = re.compile(r'[0-9A-Za-z]')


class EhDynamicReportPdf(models.AbstractModel):
    _name = 'report.eh_account_dynamic_reports.report_dynamic_pdf_template'
    _description = "Render values for the universal dynamic report PDF"

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        # A printed report must contain every journal item. The viewer sends
        # its screen options, which carry lazy_expand (accounts start
        # collapsed and load their items on demand), so force the eager path
        # or each account would print only header, opening and total.
        options = dict(data.get('options') or {}, eager_expand=True)
        DynamicReport = self.env['eh.account.dynamic.report']
        docs = DynamicReport.browse(docids)
        rendered = []
        is_rtl = self._is_rtl()
        for doc in docs:
            payload = doc.render(options)
            rendered.append({
                'doc': doc,
                'payload': payload,
                'lines': self._render_lines(payload),
                'meta_display': self._build_meta_display(payload),
                'col_widths': self._column_widths(payload.get('columns')),
                'is_rtl': is_rtl,
            })
        return {
            'docs': docs,
            'doc_ids': docids,
            'doc_model': 'eh.account.dynamic.report',
            'data': data,
            'rendered': rendered,
        }

    # Relative width weights per column, keyed by expression_label. The
    # table uses table-layout: fixed so a long unbroken value (a vendor
    # reference, a long move name) wraps inside its own cell instead of
    # running over the neighbouring column.
    _COLUMN_WEIGHTS = {
        'description': 22, 'date': 8, 'journal': 6, 'move': 12,
        'partner': 13, 'label': 15, 'foreign': 11,
    }
    _WEIGHT_FIRST_COLUMN = 24
    _WEIGHT_NUMERIC = 10
    _WEIGHT_TEXT = 12

    @api.model
    def _column_widths(self, columns):
        """Percentage width of every column, summing to 100.

        Known General Ledger columns use their weight; any other column
        gets a default by type (numeric columns narrower than text ones,
        the first column wider). Returns [] when there are no columns.
        """
        weights = []
        for idx, col in enumerate(columns or []):
            weight = self._COLUMN_WEIGHTS.get(col.get('expression_label'))
            if weight is None:
                if idx == 0:
                    weight = self._WEIGHT_FIRST_COLUMN
                elif col.get('figure_type') in _NUMERIC_FIGURE_TYPES:
                    weight = self._WEIGHT_NUMERIC
                else:
                    weight = self._WEIGHT_TEXT
            weights.append(weight)
        total = float(sum(weights))
        if not total:
            return []
        return [round(w * 100.0 / total, 2) for w in weights]

    @api.model
    def _bidi_safe(self, text, rtl=True):
        """Work around a wkhtmltopdf (Qt WebKit) bidi bug that prints the
        glyphs of some cells on top of each other.

        A bold run that mixes Arabic with digits or Latin letters and ends
        with an Arabic letter ("13900001 إيرادات مؤجلة", an account header
        or total row) is laid out with its parts at the same position. A
        trailing no-break space avoids it. It is added only for exactly
        that case: pure Arabic text, or mixed text that already ends in a
        digit or punctuation, renders correctly and a trailing character
        would shift it.
        """
        if not rtl or not text or not isinstance(text, str):
            return text
        if (_ARABIC_CHAR_RE.match(text[-1])
                and _LATIN_OR_DIGIT_RE.search(text)):
            return text + ' '
        return text

    @api.model
    def _is_rtl(self):
        """True when the language of the current environment is written
        right to left (Arabic, Hebrew, Persian, ...). Drives the page
        direction, column order and alignment of the PDF template."""
        lang = self.env['res.lang']._lang_get(self.env.lang or 'en_US')
        return bool(lang) and lang.direction == 'rtl'

    @api.model
    def _format_iso_date(self, value):
        """Render an ISO "YYYY-MM-DD" string in the user's date format.
        Anything that is not an ISO date is returned unchanged."""
        if isinstance(value, str) and _ISO_DATE_RE.match(value):
            try:
                return format_date(self.env, value)
            except (ValueError, TypeError):
                return value
        return value

    @api.model
    def _format_generated_at(self, value):
        """Render the payload's ISO timestamp (naive UTC) as a localised
        date and time in the user's timezone, without microseconds."""
        if not value:
            return ''
        try:
            return format_datetime(self.env, datetime.fromisoformat(value))
        except (ValueError, TypeError):
            return value

    @api.model
    def _build_meta_display(self, payload):
        """Display ready strings for the strip under the report title.

        Kept in Python so that the period range and the Yes / No answer go
        through Odoo's translation machinery and the user's date format
        instead of printing raw ISO values.
        """
        meta = payload.get('meta') or {}
        date_from = self._format_iso_date(meta.get('date_from') or '')
        date_to = self._format_iso_date(meta.get('date_to') or '')
        period = ''
        if date_from and date_to:
            period = _("%(date_from)s to %(date_to)s",
                       date_from=date_from, date_to=date_to)
        return {
            'period': period,
            'date_to': date_to,
            'posted_only': _("Yes") if meta.get('posted_only') else _("No"),
            'generated_at': self._format_generated_at(
                payload.get('generated_at')),
        }

    @api.model
    def _render_lines(self, payload):
        columns = payload.get('columns') or []
        currency = payload.get('currency') or {}
        rtl = self._is_rtl()
        rendered = []
        for line in payload.get('lines') or []:
            cells = []
            line_columns = line.get('columns') or []
            for i, line_col in enumerate(line_columns):
                col_def = columns[i + 1] if (i + 1) < len(columns) else {}
                figure_type = col_def.get('figure_type', 'string')
                cell_value = line_col.get('value') if line_col else None
                display = self._format_value(
                    cell_value, figure_type, currency=currency)
                if col_def.get('expression_label') == 'date':
                    display = self._format_iso_date(display)
                elif figure_type not in _NUMERIC_FIGURE_TYPES:
                    display = self._bidi_safe(display, rtl)
                cells.append({
                    'value': cell_value,
                    'display': display,
                    'align_right': figure_type in _NUMERIC_FIGURE_TYPES,
                })
            rendered.append({
                'id': line.get('id'),
                'name': self._bidi_safe(line.get('name', ''), rtl),
                'level': int(line.get('level') or 0),
                'kind': (line.get('meta') or {}).get('kind', ''),
                'cells': cells,
                'css_class': self._line_css_class(line),
            })
        return rendered

    @api.model
    def _format_value(self, value, figure_type, currency=None):
        """Return a display string for a value, applying accounting
        conventions: comma thousands, decimals from the currency block
        (default 2) for monetary, parentheses around negatives, currency
        symbol on monetary cells when the scope is single currency.
        Empty when value is None or empty string.
        """
        currency = currency or {}
        if value is None or value == '':
            return ''
        if figure_type == 'monetary':
            if isinstance(value, (int, float)):
                decimals = int(currency.get('decimal_places') or 2)
                abs_val = abs(value)
                fmt = "{:,.%df}" % decimals
                formatted = fmt.format(abs_val)
                symbol = currency.get('symbol') or ''
                multi = currency.get('multi_currency')
                if symbol and not multi:
                    if currency.get('position') == 'before':
                        body = "%s %s" % (symbol, formatted)
                    else:
                        body = "%s %s" % (formatted, symbol)
                else:
                    body = formatted
                return ("(%s)" % body) if value < 0 else body
            return str(value)
        if figure_type == 'integer':
            if isinstance(value, (int, float)):
                return "{:,}".format(int(value))
            return str(value)
        if figure_type == 'float':
            if isinstance(value, (int, float)):
                return "{:,.4f}".format(value)
            return str(value)
        if figure_type == 'percentage':
            if isinstance(value, (int, float)):
                return "{:.2%}".format(value)
            return str(value)
        return str(value)

    @api.model
    def _line_css_class(self, line):
        """Return the space separated CSS class string for a row, based on
        line level and meta.kind. The Qweb template uses these classes to
        style headers, totals, computed lines, and balance checks.
        """
        classes = []
        level = int(line.get('level') or 0)
        if level == 0:
            classes.append('eh_pdf_section_row')
        else:
            classes.append('eh_pdf_data_row')
        kind = (line.get('meta') or {}).get('kind')
        if kind == 'section_header':
            classes.append('eh_pdf_section_header')
        elif kind == 'section_total':
            classes.append('eh_pdf_section_total')
        elif kind == 'account_header':
            classes.append('eh_pdf_account_header')
        elif kind == 'account_total':
            classes.append('eh_pdf_account_total')
        elif kind == 'partner_header':
            classes.append('eh_pdf_partner_header')
        elif kind == 'partner_total':
            classes.append('eh_pdf_partner_total')
        elif kind in ('net_profit', 'net_change',
                      'computed_total', 'current_year_earnings'):
            classes.append('eh_pdf_computed')
        elif kind == 'balance_check':
            classes.append('eh_pdf_balance_check')
        elif kind == 'opening_balance':
            classes.append('eh_pdf_opening')
        elif kind == 'cash_balance':
            classes.append('eh_pdf_cash_balance')
        return ' '.join(classes)


class EhAccountDynamicReportPdf(models.Model):
    _inherit = 'eh.account.dynamic.report'

    def render_pdf(self, options):
        """Render the report to PDF bytes.

        Resolves the universal PDF action, delegates to Odoo's standard
        Qweb to PDF pipeline, returning the bytes blob.
        """
        self.ensure_one()
        action = self.env.ref(
            'eh_account_dynamic_reports.action_report_dynamic_pdf',
            raise_if_not_found=False,
        )
        if not action:
            raise UserError(
                "PDF report action not found. Reinstall eh_account_dynamic_reports."
            )
        data = {'options': options}
        # Odoo's report rendering expects a list of docids; we pass our
        # report id and the abstract model picks it up in _get_report_values.
        report_ref = action.report_name
        rendering = self.env['ir.actions.report']._render_qweb_pdf(
            report_ref, [self.id], data=data,
        )
        # _render_qweb_pdf returns a tuple (bytes, content_type) on Odoo 17+.
        # In --test-enable mode Odoo 19 returns HTML bytes rather than
        # invoking wkhtmltopdf; both are valid for our callers because
        # downstream uses the bytes as a binary blob.
        if isinstance(rendering, tuple):
            return rendering[0]
        return rendering

    def export_pdf_attachment(self, options):
        """Render to PDF, persist as ir.attachment, return a download action.

        Mirrors export_xlsx_attachment so the OWL viewer can hand the user
        a downloadable file with one RPC call.
        """
        self.ensure_one()
        content = self.render_pdf(options)
        date_block = options.get('date') or {}
        filename = "%s_%s_to_%s.pdf" % (
            self.code,
            date_block.get('date_from') or '',
            date_block.get('date_to') or '',
        )
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(content),
            'mimetype': 'application/pdf',
            'res_model': self._name,
            'res_id': self.id,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'download',
        }
