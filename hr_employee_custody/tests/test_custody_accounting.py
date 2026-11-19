# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import CustodyTestCommon


@tagged("post_install", "-at_install", "custody")
class TestCustodyAccounting(CustodyTestCommon):

    def _issue_custody(self, amount=1000.0):
        custody = self.env["employee.custody"].create({
            "employee_id": self.employee.id,
            "custody_type_id": self.type_financial.id,
            "amount": amount,
        })
        custody.action_submit()
        custody.action_approve()
        custody.action_issue()
        return custody

    def test_01_issue_move_debits_custody_credits_cash(self):
        custody = self._issue_custody(500.0)
        move = custody.issue_move_id
        self.assertEqual(move.state, "posted")
        debit_line = move.line_ids.filtered(lambda l: l.debit > 0)
        credit_line = move.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(debit_line.account_id, self.custody_account)
        self.assertEqual(credit_line.account_id, self.cash_account)
        self.assertEqual(debit_line.debit, 500.0)
        self.assertEqual(credit_line.credit, 500.0)

    def test_02_expense_settlement_creates_move(self):
        custody = self._issue_custody(1000.0)
        settlement = self.env["employee.custody.settlement"].create({
            "custody_id": custody.id,
            "settlement_kind": "expense",
            "amount": 400.0,
        })
        settlement._onchange_settlement_kind()
        settlement.action_post()
        self.assertEqual(settlement.state, "posted")
        self.assertTrue(settlement.move_id)
        self.assertEqual(settlement.move_id.state, "posted")
        self.assertEqual(custody.amount_settled, 400.0)
        self.assertEqual(custody.balance_amount, 600.0)
        self.assertEqual(custody.state, "partial")

    def test_03_full_settlement_moves_to_settled(self):
        custody = self._issue_custody(500.0)
        s = self.env["employee.custody.settlement"].create({
            "custody_id": custody.id,
            "settlement_kind": "expense",
            "amount": 500.0,
        })
        s._onchange_settlement_kind()
        s.action_post()
        self.assertEqual(custody.state, "settled")
        self.assertEqual(custody.balance_amount, 0.0)

    def test_04_over_settlement_blocked(self):
        custody = self._issue_custody(500.0)
        with self.assertRaises(ValidationError):
            self.env["employee.custody.settlement"].create({
                "custody_id": custody.id,
                "settlement_kind": "expense",
                "amount": 600.0,
            })

    def test_05_salary_deduction_uses_salary_account(self):
        custody = self._issue_custody(200.0)
        s = self.env["employee.custody.settlement"].create({
            "custody_id": custody.id,
            "settlement_kind": "salary",
            "amount": 200.0,
        })
        s._onchange_settlement_kind()
        s.action_post()
        debit = s.move_id.line_ids.filtered(lambda l: l.debit > 0)
        self.assertEqual(debit.account_id, self.salary_account)

    def test_06_cancel_settlement_reverses_move(self):
        custody = self._issue_custody(300.0)
        s = self.env["employee.custody.settlement"].create({
            "custody_id": custody.id,
            "settlement_kind": "expense",
            "amount": 100.0,
        })
        s._onchange_settlement_kind()
        s.action_post()
        move = s.move_id
        s.action_cancel()
        self.assertEqual(s.state, "cancelled")
        # A reversal move must exist.
        self.assertTrue(
            self.env["account.move"].search([
                ("custody_id", "=", custody.id),
                ("reversed_entry_id", "=", move.id),
            ])
        )
