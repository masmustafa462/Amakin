# -*- encoding: utf-8 -*-
"""Rename the statement report to "Account Statement" / "كشف حساب".

The report, its client action and its menu were first shipped as
"Customer / Vendor Account Statement"; the stored Arabic translations of the
old name survive a plain upgrade, so write both languages explicitly.
"""

from odoo import SUPERUSER_ID, api

_REFS = (
    'eh_account_dynamic_reports.report_partner_account_statement',
    'eh_account_dynamic_reports.action_open_partner_account_statement_viewer',
    'eh_account_dynamic_reports.menu_partner_account_statement',
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    langs = [code for code, _name in env['res.lang'].get_installed()]
    for xmlid in _REFS:
        record = env.ref(xmlid, raise_if_not_found=False)
        if not record:
            continue
        record.with_context(lang='en_US').write({'name': 'Account Statement'})
        for lang in langs:
            if lang.startswith('ar'):
                record.with_context(lang=lang).write({'name': 'كشف حساب'})
