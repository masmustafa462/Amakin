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
import logging
import re
from datetime import datetime

from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_date, format_datetime

_logger = logging.getLogger(__name__)


_NUMERIC_FIGURE_TYPES = frozenset({
    'monetary', 'integer', 'float', 'percentage',
})

# A payload date value is an ISO "YYYY-MM-DD" string. Used to decide whether
# a cell in a "date" column can be rendered in the user's date format.
_ISO_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

# Arabic script blocks (Arabic, Supplement, Extended-A, Presentation Forms).
_ARABIC_CHAR_RE = re.compile(
    '[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]')
_ANY_ARABIC_RE = re.compile(r'[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]')
_MIXED_TRIGGER_RE = re.compile(r'[0-9A-Za-z\-/()%]')
_LATIN_OR_DIGIT_RE = re.compile(r'[0-9A-Za-z]')


class EhDynamicReportPdf(models.AbstractModel):
    _name = 'report.eh_account_dynamic_reports.report_dynamic_pdf_template'
    _description = "Render values for the universal dynamic report PDF"

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        # The printed report mirrors the screen. The viewer renders with
        # lazy_expand (each account is a collapsed header/opening/total) and
        # fetches journal items only for the accounts the user opened. It
        # sends that state as options['pdf_expanded'] = {line_id: number of
        # items loaded}. Split it off before rendering so the render (and its
        # cache key) is the same one the screen used.
        options = dict(data.get('options') or {})
        expanded = options.pop('pdf_expanded', None) or {}
        # The in-table search box: only the rows it leaves on screen print.
        table_query = options.pop('pdf_query', None) or ''
        DynamicReport = self.env['eh.account.dynamic.report']
        docs = DynamicReport.browse(docids)
        rendered = []
        is_rtl = self._is_rtl()
        for doc in docs:
            payload = doc.render(options)
            payload = self._apply_table_filter(payload, table_query)
            try:
                payload = self._splice_expanded_lines(
                    doc, payload, options, expanded)
            except Exception:
                # Mirroring the screen is best effort: a failure while
                # fetching an opened account's items must never block the
                # printout, which then falls back to the collapsed rows.
                _logger.exception(
                    "PDF: could not add the opened accounts' journal items "
                    "for report %s; printing them collapsed", doc.code)
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

    @api.model
    def _splice_expanded_lines(self, doc, payload, options, expanded):
        """Add the journal items of every account the user opened on screen.

        `expanded` maps a lazy line id to the number of items the screen had
        loaded for it. Each is fetched with the same expand_line RPC the
        viewer uses (same filters, running balance and currency handling),
        and inserted after the account's opening-balance row so the running
        balance reads top to bottom. Accounts that were collapsed on screen
        stay collapsed. When the screen had only loaded part of an account,
        a final note row says so. The payload is returned unchanged when
        nothing is expanded. Only lines flagged lazy are looked up, so a
        report rendered eagerly (no lazy lines) is never altered.
        """
        if not expanded or not isinstance(expanded, dict):
            return payload
        lines = payload.get('lines') or []
        spliced = []
        i = 0
        while i < len(lines):
            line = lines[i]
            spliced.append(line)
            i += 1
            count = expanded.get(line.get('id')) if line.get('lazy') else None
            if not count:
                continue
            try:
                limit = max(int(count), 1)
            except (TypeError, ValueError):
                continue
            # Keep the opening-balance row ahead of the items.
            nxt = lines[i] if i < len(lines) else None
            if nxt and (nxt.get('meta') or {}).get('kind') == 'opening_balance':
                spliced.append(nxt)
                i += 1
            result = doc.expand_line(options, line['id'], 0, limit)
            spliced.extend(result.get('child_lines') or [])
            if result.get('has_more'):
                spliced.append({
                    'id': 'more-%s' % line['id'],
                    'name': _(
                        "Showing %(shown)s of %(total)s journal items, "
                        "as displayed on screen",
                        shown=len(result.get('child_lines') or []),
                        total=result.get('total_count') or 0,
                    ),
                    'level': (line.get('level') or 0) + 1,
                    'columns': [],
                    'meta': {'kind': 'load_more'},
                })
        payload = dict(payload, lines=spliced)
        return payload

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
    def _apply_table_filter(self, payload, query):
        """Keep only the rows the viewer's in-table search leaves visible.

        Same rule as the screen (computeFilterKeepSet in report_table_logic):
        every row whose name contains the query, plus its ancestors (context)
        and the descendants of a matched group. An empty query keeps all.
        """
        q = (query or '').strip().lower()
        lines = payload.get('lines') or []
        if not q or not lines:
            return payload
        by_id = {line.get('id'): line for line in lines}
        direct = {line.get('id') for line in lines
                  if q in (line.get('name') or '').lower()}
        keep = set()
        for line_id in direct:
            keep.add(line_id)
            seen = set()
            parent_id = (by_id.get(line_id) or {}).get('parent_id')
            while parent_id and parent_id not in seen:
                seen.add(parent_id)
                keep.add(parent_id)
                parent_id = (by_id.get(parent_id) or {}).get('parent_id')
        for line in lines:
            if line.get('id') in keep:
                continue
            seen = set()
            parent_id = line.get('parent_id')
            while parent_id and parent_id not in seen:
                seen.add(parent_id)
                if parent_id in direct:
                    keep.add(line.get('id'))
                    break
                parent_id = (by_id.get(parent_id) or {}).get('parent_id')
        return dict(payload, lines=[
            line for line in lines if line.get('id') in keep])

    @api.model
    def _bidi_safe(self, text, rtl=True):
        """Work around a wkhtmltopdf (Qt WebKit) bidi bug that prints the
        glyphs of some cells on top of each other.

        Arabic text that also holds digits, Latin letters or neutral
        punctuation ("20020001 اعادة تأهيل المصنع - صيانة 1", "إجمالي
        13900001 ...") is laid out wrongly by wkhtmltopdf: parts overprint,
        or the words before a " - " are pushed past the cell edge and cut.
        Right-to-left marks (zero width) at both ends and around every
        space pin the direction of each run and render it correctly. Pure
        Arabic text, and text without Arabic, is left untouched.
        """
        if not rtl or not text or not isinstance(text, str):
            return text
        if (_ANY_ARABIC_RE.search(text)
                and _MIXED_TRIGGER_RE.search(text)):
            mark = '\u200f'
            return mark + text.replace(' ', mark + ' ' + mark) + mark
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
            'date_from': date_from,
            'partner_names': meta.get('partner_names') or '',
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
