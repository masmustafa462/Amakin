# -*- coding: utf-8 -*-
from odoo import api, models


class CustodyLedgerReport(models.AbstractModel):
    """Abstract report helper that composes a custody ledger per employee."""

    _name = "report.hr_employee_custody.report_custody_ledger"
    _description = "Custody Ledger Report"

    @api.model
    def _get_report_values(self, docids, data=None):
        custodies = self.env["employee.custody"].browse(docids)
        ledger = {}
        for custody in custodies:
            rows = []
            # Opening: the issue itself.
            if custody.issue_date:
                rows.append({
                    "date": custody.issue_date,
                    "ref": custody.name,
                    "description": "صرف العهدة",
                    "debit": custody.amount if custody.custody_kind == "financial" else 0.0,
                    "credit": 0.0,
                    "balance": custody.amount if custody.custody_kind == "financial" else 0.0,
                })
            # Settlements.
            running = custody.amount if custody.custody_kind == "financial" else 0.0
            for s in custody.settlement_ids.sorted("settlement_date"):
                if s.state != "posted":
                    continue
                amt = s.amount if custody.custody_kind == "financial" else 0.0
                running -= amt
                rows.append({
                    "date": s.settlement_date,
                    "ref": s.name,
                    "description": dict(s._fields["settlement_kind"].selection).get(
                        s.settlement_kind, ""
                    ),
                    "debit": 0.0,
                    "credit": amt,
                    "balance": running,
                })
            ledger[custody.id] = rows
        return {
            "doc_ids": docids,
            "doc_model": "employee.custody",
            "docs": custodies,
            "ledger": ledger,
        }
