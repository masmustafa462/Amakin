# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import CustodyTestCommon


@tagged("post_install", "-at_install", "custody")
class TestCustodySecurity(CustodyTestCommon):

    def setUp(self):
        super().setUp()
        self.user_basic = self.env["res.users"].create({
            "name": "Basic User",
            "login": "basic_cust_user",
            "groups_id": [(6, 0, [
                self.env.ref("hr_employee_custody.group_custody_user").id,
            ])],
        })
        self.user_officer = self.env["res.users"].create({
            "name": "Officer",
            "login": "officer_cust_user",
            "groups_id": [(6, 0, [
                self.env.ref("hr_employee_custody.group_custody_officer").id,
            ])],
        })

    def test_01_basic_user_sees_only_own(self):
        other_emp = self.env["hr.employee"].create({"name": "Other Emp"})
        mine = self.env["employee.custody"].with_user(self.user_basic).create({
            "employee_id": other_emp.id,
            "custody_type_id": self.type_financial.id,
            "amount": 100.0,
        })
        # Created by the basic user, so user_id filter lets them read it.
        self.assertTrue(
            mine.with_user(self.user_basic).read(["name"])
        )
        # A custody created by someone else for another employee should be hidden.
        foreign = self.env["employee.custody"].create({
            "employee_id": other_emp.id,
            "custody_type_id": self.type_financial.id,
            "amount": 100.0,
            "user_id": self.user_officer.id,
        })
        with self.assertRaises(AccessError):
            foreign.with_user(self.user_basic).read(["name"])

    def test_02_officer_can_approve(self):
        custody = self.env["employee.custody"].create({
            "employee_id": self.employee.id,
            "custody_type_id": self.type_financial.id,
            "amount": 200.0,
        })
        custody.action_submit()
        # The officer should succeed.
        custody.with_user(self.user_officer).action_approve()
        self.assertEqual(custody.state, "approved")
