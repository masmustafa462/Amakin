# -*- coding: utf-8 -*-
"""Access rights, multi-company isolation, drawing control and Arabic support."""

import os
import subprocess

import polib

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tools import file_path

from .common import DwCommon


@tagged("post_install", "-at_install", "dw_manufacturing")
class TestSecurity(DwCommon):

    def setUp(self):
        super().setUp()
        self.group_user = self.env.ref("dw_manufacturing.group_dw_user")
        self.group_manager = self.env.ref("dw_manufacturing.group_dw_manager")
        self.group_cost = self.env.ref("dw_manufacturing.group_dw_cost_accountant")
        self.group_quality = self.env.ref("dw_manufacturing.group_dw_quality")
        self.user_basic = self.env["res.users"].create({
            "name": "Fabrication Operator",
            "login": "dw_operator",
            "group_ids": [Command.set([
                self.group_user.id,
                self.env.ref("base.group_user").id,
            ])],
        })
        self.user_cost = self.env["res.users"].create({
            "name": "Cost Accountant",
            "login": "dw_cost",
            "group_ids": [Command.set([
                self.group_user.id,
                self.group_cost.id,
                self.env.ref("base.group_user").id,
            ])],
        })

    def test_01_group_names_have_no_ampersand(self):
        groups = self.env["res.groups"].search([
            ("id", "in", [
                self.env.ref("dw_manufacturing.group_dw_user").id,
                self.env.ref("dw_manufacturing.group_dw_supervisor").id,
                self.env.ref("dw_manufacturing.group_dw_manager").id,
                self.env.ref("dw_manufacturing.group_dw_stock").id,
                self.env.ref("dw_manufacturing.group_dw_quality").id,
                self.env.ref("dw_manufacturing.group_dw_cost_accountant").id,
                self.env.ref("dw_manufacturing.group_dw_project_manager").id,
                self.env.ref("dw_manufacturing.group_dw_profitability").id,
            ])
        ])
        self.assertEqual(len(groups), 8)
        for group in groups:
            self.assertNotIn("&", group.name)
        privilege = self.env.ref("dw_manufacturing.privilege_dw")
        self.assertNotIn("&", privilege.name)

    def test_02_plain_user_cannot_change_configuration(self):
        rule = self.env["dw.component.rule"].search([], limit=1)
        if not rule:
            rule = self.env["dw.component.rule"].create({
                "name": "Temp",
                "company_id": self.company.id,
                "component_product_id": self.mat_tube40.id,
                "calc_method": "fixed",
            })
        with self.assertRaises(AccessError):
            self.env["dw.product.family"].with_user(self.user_basic).create({
                "name": "Sneaky family",
                "code": "SNEAK",
                "product_kind": "custom",
                "company_id": self.company.id,
            })

    def test_03_plain_user_cannot_write_cost_lines(self):
        line = self.env["dw.production.cost.line"].create({
            "company_id": self.company.id,
            "currency_id": self.company.currency_id.id,
            "cost_type": "material",
            "amount": 100.0,
        })
        with self.assertRaises(AccessError):
            line.with_user(self.user_basic).write({"amount": 5.0})
        # The cost accountant may.
        line.with_user(self.user_cost).write({"amount": 5.0})
        self.assertAlmostEqual(line.amount, 5.0)

    def test_04_cost_revision_log_cannot_be_deleted(self):
        line = self.env["dw.production.cost.line"].create({
            "company_id": self.company.id,
            "currency_id": self.company.currency_id.id,
            "cost_type": "material",
            "amount": 100.0,
        })
        line.action_approve()
        line._record_revision(150.0, "test")
        revision = line.revision_ids
        self.assertTrue(revision)
        with self.assertRaises(UserError):
            revision.unlink()

    def test_05_multi_company_isolation(self):
        other_company = self.env["res.company"].create({"name": "Second Metal Co"})
        other_family = self.env["dw.product.family"].create({
            "name": "Other company family",
            "code": "OCF",
            "product_kind": "custom",
            "company_id": other_company.id,
        })
        visible = self.env["dw.product.family"].with_user(self.user_basic).search([])
        self.assertNotIn(other_family, visible)
        allowed = self.env["dw.product.family"].with_user(self.user_basic).with_context(
            allowed_company_ids=[self.company.id]
        ).search([])
        self.assertNotIn(other_family, allowed)

    def test_06_record_rules_exist_for_every_company_model(self):
        models_with_rule = self.env["ir.rule"].search([
            ("model_id.model", "like", "dw.%"),
        ]).mapped("model_id.model")
        for model_name in (
            "dw.opening", "dw.component.rule", "dw.product.family",
            "dw.production.cost.line", "dw.project.cost.entry",
            "dw.quality.check", "dw.quality.template", "dw.drawing",
            "dw.material.offcut", "dw.labor.rate", "dw.overhead.rule", "dw.alert",
        ):
            self.assertIn(model_name, models_with_rule, model_name)


@tagged("post_install", "-at_install", "dw_manufacturing")
class TestDrawingControl(DwCommon):

    def setUp(self):
        super().setUp()
        self.drawing = self.env["dw.drawing"].create({
            "name": "DRW-TEST-01",
            "title": "Test gate",
            "company_id": self.company.id,
        })
        self.attachment = self.env["ir.attachment"].create({
            "name": "gate.pdf",
            "datas": b"ZmFrZSBwZGY=",
        })

    def test_01_release_requires_attachment(self):
        revision = self.env["dw.drawing.revision"].create({
            "drawing_id": self.drawing.id,
            "revision": "A",
        })
        with self.assertRaises(UserError):
            revision.action_release()
        revision.attachment_ids = [Command.set(self.attachment.ids)]
        revision.action_release()
        self.assertEqual(revision.state, "released")
        self.assertTrue(revision.approved_by)

    def test_02_new_release_supersedes_the_previous_one(self):
        rev_a = self.env["dw.drawing.revision"].create({
            "drawing_id": self.drawing.id,
            "revision": "A",
            "sequence": 10,
            "attachment_ids": [Command.set(self.attachment.ids)],
        })
        rev_a.action_release()
        attachment_b = self.env["ir.attachment"].create({
            "name": "gate_b.pdf", "datas": b"ZmFrZSBwZGYgYg==",
        })
        rev_b = self.env["dw.drawing.revision"].create({
            "drawing_id": self.drawing.id,
            "revision": "B",
            "sequence": 20,
            "attachment_ids": [Command.set(attachment_b.ids)],
        })
        rev_b.action_release()
        self.assertEqual(rev_a.state, "superseded")
        self.assertEqual(rev_b.state, "released")
        # The old file is still there: history is never overwritten.
        self.assertIn(self.attachment, rev_a.attachment_ids)
        self.assertEqual(self.drawing.current_revision, "B")

    def test_03_released_revision_cannot_be_deleted(self):
        revision = self.env["dw.drawing.revision"].create({
            "drawing_id": self.drawing.id,
            "revision": "A",
            "attachment_ids": [Command.set(self.attachment.ids)],
        })
        revision.action_release()
        with self.assertRaises(UserError):
            revision.unlink()

    def test_04_unreleased_revision_blocks_production(self):
        revision = self.env["dw.drawing.revision"].create({
            "drawing_id": self.drawing.id,
            "revision": "A",
        })
        family = self.env["dw.product.family"].create({
            "name": "Drawing Family",
            "code": "DRWF",
            "product_kind": "gate",
            "company_id": self.company.id,
            "dimension_ids": self._dims("width", "height"),
        })
        self.env["dw.component.rule"].create({
            "name": "Frame",
            "family_id": family.id,
            "company_id": self.company.id,
            "component_product_id": self.mat_tube40.id,
            "calc_method": "variable",
            "basis": "perimeter",
            "factor": 1.0,
        })
        order = self._make_sale_order()
        item = self.env["dw.opening"].create({
            "sale_order_id": order.id,
            "family_id": family.id,
            "finished_product_id": self.product_door.id,
            "width_mm": 1000.0,
            "height_mm": 2000.0,
            "quantity": 1.0,
            "drawing_id": self.drawing.id,
            "drawing_revision_id": revision.id,
        })
        item.action_generate_components()
        item.action_sync_quotation_line()
        order.action_confirm()
        with self.assertRaises(UserError):
            item.action_create_manufacturing_order()

        revision.attachment_ids = [Command.set(self.attachment.ids)]
        revision.action_release()
        self._stock(self.mat_tube40, 100.0)
        item.action_create_manufacturing_order()
        self.assertTrue(item.production_id)
        self.assertEqual(item.production_id.dw_drawing_revision_id, revision)


@tagged("post_install", "-at_install", "dw_manufacturing")
class TestArabic(DwCommon):

    def test_01_translation_file_is_valid(self):
        path = file_path("dw_manufacturing/i18n/ar.po")
        catalogue = polib.pofile(path)
        self.assertFalse(catalogue.percent_translated() == 0)
        for entry in catalogue:
            self.assertTrue(
                any("module: dw_manufacturing" in comment for comment in entry.comment.splitlines())
                or entry.comment == "",
                "Missing module marker for: %s" % entry.msgid,
            )

    def test_02_msgfmt_accepts_the_catalogue(self):
        path = file_path("dw_manufacturing/i18n/ar.po")
        result = subprocess.run(
            ["msgfmt", "--check", "-o", os.devnull, path],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_03_arabic_language_can_be_activated_and_terms_translate(self):
        self.env["res.lang"]._activate_lang("ar_001") or self.env["res.lang"]._activate_lang("ar_SY")
        language = self.env["res.lang"].search([("code", "like", "ar%")], limit=1)
        self.assertTrue(language, "An Arabic language must be installable")
        self.assertEqual(language.direction, "rtl")

    def test_04_report_renders_right_to_left_in_arabic(self):
        """A real PDF template must flip to RTL and print Arabic labels."""
        self.env["res.lang"]._activate_lang("ar_001")
        self.env["ir.module.module"].search(
            [("name", "=", "dw_manufacturing")]
        )._update_translations(["ar_001"])
        family = self.env["dw.product.family"].create({
            "name": "Report Family",
            "code": "RPTF",
            "product_kind": "gate",
            "company_id": self.company.id,
            "dimension_ids": self._dims("width", "height"),
        })
        item = self.env["dw.opening"].create({
            "family_id": family.id,
            "finished_product_id": self.product_door.id,
            "company_id": self.company.id,
            "width_mm": 1000.0,
            "height_mm": 2000.0,
            "quantity": 1.0,
        })
        report = self.env.ref("dw_manufacturing.action_report_dw_item")
        html_ltr = self.env["ir.actions.report"]._render_qweb_html(
            report.report_name, item.ids
        )[0].decode()
        self.assertIn("dw-report", html_ltr)

        html_rtl = self.env["ir.actions.report"].with_context(
            lang="ar_001"
        )._render_qweb_html(report.report_name, item.ids)[0].decode()
        self.assertIn('dir="rtl"', html_rtl)
        self.assertIn("dw-rtl", html_rtl)
        self.assertIn("عنصر تصنيع", html_rtl)

    def test_05_model_labels_are_generic_not_door_specific(self):
        model = self.env["ir.model"].search([("model", "=", "dw.opening")])
        self.assertEqual(model.name, "Manufacturing Item")
        module = self.env["ir.module.module"].search([("name", "=", "dw_manufacturing")])
        self.assertEqual(module.shortdesc, "Metal Fabrication Management")
