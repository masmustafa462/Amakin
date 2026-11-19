# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import CustodyTestCommon


@tagged("post_install", "-at_install", "custody")
class TestCustodyMaterial(CustodyTestCommon):

    def _issue_material(self, qty=3):
        custody = self.env["employee.custody"].create({
            "employee_id": self.employee.id,
            "custody_type_id": self.type_material.id,
            "asset_description": "Dell Latitude 7440",
            "quantity": qty,
        })
        custody.action_submit()
        custody.action_approve()
        custody.action_issue()
        return custody

    def test_01_material_return_reduces_qty(self):
        custody = self._issue_material(3)
        s = self.env["employee.custody.settlement"].create({
            "custody_id": custody.id,
            "settlement_kind": "return",
            "returned_quantity": 2,
        })
        s.action_post()
        self.assertEqual(custody.returned_quantity, 2)
        self.assertEqual(custody.remaining_quantity, 1)
        self.assertEqual(custody.state, "partial")

    def test_02_full_return_sets_returned_state(self):
        custody = self._issue_material(2)
        s = self.env["employee.custody.settlement"].create({
            "custody_id": custody.id,
            "settlement_kind": "return",
            "returned_quantity": 2,
        })
        s.action_post()
        self.assertEqual(custody.state, "returned")

    def test_03_over_return_blocked(self):
        custody = self._issue_material(2)
        with self.assertRaises(ValidationError):
            self.env["employee.custody.settlement"].create({
                "custody_id": custody.id,
                "settlement_kind": "return",
                "returned_quantity": 5,
            })

    def test_04_mark_lost(self):
        custody = self._issue_material(1)
        custody.action_mark_lost()
        self.assertEqual(custody.state, "lost")
