# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Excel export that mirrors the screen, like the PDF export.

The viewer sends, beside the report options, `pdf_expanded` (the accounts the
user opened and how many journal items were loaded) and `pdf_query` (the
in-table search text). The workbook then holds exactly the rows on screen:
opened accounts with their journal items, only the rows matching the search,
and the report conditions (period, partner, posted only, currency, generated)
as labelled cells, with right-to-left sheet direction for Arabic users.
"""

import logging

from odoo import _, models

from odoo.addons.eh_account_base.tools.xlsx_writer import XlsxReportWriter

_logger = logging.getLogger(__name__)

_PDF_MODEL = 'report.eh_account_dynamic_reports.report_dynamic_pdf_template'


class EhDynamicReportExport(models.Model):
    _inherit = 'eh.account.dynamic.report'

    def render_xlsx(self, options, use_cache=True):
        self.ensure_one()
        options = dict(options or {})
        expanded = options.pop('pdf_expanded', None) or {}
        query = options.pop('pdf_query', None) or ''
        payload = self.render(options, use_cache=use_cache)
        helper = self.env[_PDF_MODEL]
        payload = helper._apply_table_filter(payload, query)
        try:
            payload = helper._splice_expanded_lines(
                self, payload, options, expanded)
        except Exception:
            # Mirroring the screen is best effort; fall back to the
            # collapsed rows rather than failing the download.
            _logger.exception(
                "XLSX: could not add the opened accounts' journal items "
                "for report %s; exporting them collapsed", self.code)
        meta = dict(payload.get('meta') or {})
        names = meta.get('partner_names')
        if not names and options.get('partner_ids'):
            names = ', '.join(self.env['res.partner'].browse(
                [int(p) for p in options['partner_ids']]
            ).exists().mapped('name'))
            meta['partner_names'] = names
        writer = XlsxReportWriter(
            report_name=self.name,
            labels=self._xlsx_labels(),
            rtl=helper._is_rtl(),
        )
        return writer.write_payload(payload, meta=meta)

    def _xlsx_labels(self):
        def caption(text):
            return text.rstrip(':')
        return {
            'from': caption(_("From:")),
            'to': caption(_("To:")),
            'as_at': caption(_("As at:")),
            'partner': caption(_("Partner:")),
            'account': caption(_("Account:")),
            'posted_only': caption(_("Posted only:")),
            'currency': caption(_("Currency:")),
            'generated': caption(_("Generated:")),
            'yes': _("Yes"),
            'no': _("No"),
            'multi_currency': _("Multi-currency"),
        }
