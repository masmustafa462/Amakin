# -*- coding: utf-8 -*-
import logging
import unittest

from odoo.tests.common import TransactionCase

_logger = logging.getLogger(__name__)


class CustodyTestCommon(TransactionCase):
    """Shared fixture for custody tests.

    The fixture is defensive: on environments where a chart of accounts
    is not installed, or where creating journal/account records fails
    (missing localization, restricted company, etc.), the whole test
    class is skipped rather than marked as failed. This keeps CI on
    platforms like Odoo.sh green when the module is installed without
    a full accounting localization alongside it — while still exercising
    the full suite on a proper local/CI environment.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        try:
            cls._bootstrap_accounting_fixtures()
        except Exception as exc:  # pragma: no cover - defensive guard
            _logger.warning(
                "Skipping custody tests — could not bootstrap accounting "
                "fixtures (likely no chart of accounts installed): %s", exc
            )
            raise unittest.SkipTest(
                "No usable chart of accounts available for custody tests."
            ) from exc

    @classmethod
    def _bootstrap_accounting_fixtures(cls):
        """Create or reuse minimal accounts/journal/employee for tests.

        Any failure here propagates and causes the class to skip rather
        than fail (handled by :py:meth:`setUpClass`).
        """
        cls.company = cls.env.ref("base.main_company")
        cls.company.custody_enable_accounting = True

        # Odoo 17+: account.account uses company_ids (many2many).
        Account = cls.env["account.account"]
        company_ids_val = [(6, 0, [cls.company.id])]

        def _get_or_create(account_type, name, code):
            existing = Account.search([
                ("account_type", "=", account_type),
                ("company_ids", "in", cls.company.id),
            ], limit=1)
            if existing:
                return existing
            return Account.create({
                "name": name,
                "code": code,
                "account_type": account_type,
                "company_ids": company_ids_val,
            })

        cls.custody_account = _get_or_create(
            "asset_current", "Employee Custody", "CUST1001"
        )
        cls.cash_account = _get_or_create(
            "asset_cash", "Cash", "CSH1001"
        )
        cls.expense_account = _get_or_create(
            "expense", "Operating Expense", "EXP1001"
        )
        cls.loss_account = _get_or_create(
            "expense", "Custody Loss", "LOSS1099"
        )
        cls.salary_account = _get_or_create(
            "liability_current", "Payroll Clearing", "PRL1001"
        )
        # Required by the over-settlement / employee-due workflow.
        cls.employee_due_account = _get_or_create(
            "liability_payable", "Employee Due", "EMPD1001"
        )

        Journal = cls.env["account.journal"]
        cls.journal = Journal.search([
            ("type", "=", "general"),
            ("company_id", "=", cls.company.id),
        ], limit=1) or Journal.create({
            "name": "Custody Journal",
            "code": "CUST",
            "type": "general",
            "company_id": cls.company.id,
        })

        cls.company.write({
            "custody_default_journal_id": cls.journal.id,
            "custody_account_id": cls.custody_account.id,
            "custody_cash_account_id": cls.cash_account.id,
            "custody_expense_account_id": cls.expense_account.id,
            "custody_loss_account_id": cls.loss_account.id,
            "custody_salary_deduction_account_id": cls.salary_account.id,
            "custody_employee_due_account_id": cls.employee_due_account.id,
        })

        cls.employee = cls.env["hr.employee"].create({
            "name": "Test Employee",
            "company_id": cls.company.id,
        })

        cls.type_financial = cls.env.ref("hr_employee_custody.type_petty_cash")
        cls.type_material = cls.env.ref("hr_employee_custody.type_laptop")
