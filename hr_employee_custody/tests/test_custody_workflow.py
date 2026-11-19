# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import CustodyTestCommon


@tagged("post_install", "-at_install", "custody")
class TestCustodyWorkflow(CustodyTestCommon):

    def _make_financial_custody(self, amount=1000.0):
        return self.env["employee.custody"].create({
            "employee_id": self.employee.id,
            "custody_type_id": self.type_financial.id,
            "amount": amount,
        })

    def test_01_full_lifecycle(self):
        custody = self._make_financial_custody(500.0)
        self.assertEqual(custody.state, "draft")

        custody.action_submit()
        self.assertEqual(custody.state, "submitted")

        custody.action_approve()
        self.assertEqual(custody.state, "approved")

        custody.action_issue()
        self.assertEqual(custody.state, "issued")
        self.assertTrue(custody.issue_move_id)
        self.assertEqual(custody.issue_move_id.state, "posted")

    def test_02_amount_positive(self):
        with self.assertRaises(ValidationError):
            self.env["employee.custody"].create({
                "employee_id": self.employee.id,
                "custody_type_id": self.type_financial.id,
                "amount": 0.0,
            })

    def test_03_cannot_approve_from_draft_directly_for_user(self):
        custody = self._make_financial_custody()
        # Skipping the submit step should fail — state machine strictness.
        with self.assertRaises(UserError):
            custody.action_issue()

    def test_04_cannot_edit_locked_fields_after_issue(self):
        custody = self._make_financial_custody()
        custody.action_submit()
        custody.action_approve()
        custody.action_issue()
        # Non-admin user should not be able to rewrite amount.
        non_admin = self.env["res.users"].create({
            "name": "Officer",
            "login": "officer_lock_test",
            "groups_id": [(6, 0, [
                self.env.ref("hr_employee_custody.group_custody_officer").id,
            ])],
        })
        with self.assertRaises(UserError):
            custody.with_user(non_admin).write({"amount": 999.0})

    def test_05_cancel_prevents_after_settle(self):
        custody = self._make_financial_custody()
        custody.action_submit()
        custody.action_approve()
        custody.action_issue()
        custody.state = "settled"
        with self.assertRaises(UserError):
            custody.action_cancel()

    def test_06_expected_date_before_issue_date_invalid(self):
        custody = self._make_financial_custody()
        custody.action_submit()
        custody.action_approve()
        custody.issue_date = "2026-03-01"
        with self.assertRaises(ValidationError):
            custody.expected_return_date = "2026-02-15"
