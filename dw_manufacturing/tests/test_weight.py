# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import DwCommon


@tagged("post_install", "-at_install", "dw_manufacturing")
class TestTheoreticalWeight(DwCommon):
    """Theoretical weights are checked against published steel section tables."""

    def test_01_square_hollow_section(self):
        # SHS 40x40x2 -> about 2.36 kg/m in commercial tables (sharp corners 2.39)
        self.assertAlmostEqual(self.profile_shs40.weight_per_m, 2.3864, places=3)
        self.assertEqual(self.profile_shs40.weight_basis, "length")

    def test_02_rectangular_hollow_section(self):
        profile = self.env.ref("dw_manufacturing.profile_rhs_60x40x2")
        self.assertAlmostEqual(profile.weight_per_m, 3.014, places=3)

    def test_03_round_pipe(self):
        # Pipe 48.3 x 3.2 -> 3.56 kg/m
        self.assertAlmostEqual(self.profile_pipe.weight_per_m, 3.559, places=3)

    def test_04_angle(self):
        profile = self.env.ref("dw_manufacturing.profile_angle_50x50x5")
        self.assertAlmostEqual(profile.weight_per_m, 3.729, places=3)

    def test_05_round_bar(self):
        profile = self.env.ref("dw_manufacturing.profile_round_bar_12")
        self.assertAlmostEqual(profile.weight_per_m, 0.888, places=3)

    def test_06_sheet(self):
        # 2 mm mild steel sheet -> 15.7 kg/m2
        self.assertAlmostEqual(self.profile_sheet2.weight_per_m2, 15.7, places=3)
        self.assertEqual(self.profile_sheet2.weight_basis, "area")

    def test_07_density_follows_grade(self):
        stainless = self.env.ref("dw_manufacturing.metal_type_stainless")
        profile = self.env["dw.metal.profile"].create({
            "name": "SS Sheet 2mm",
            "shape": "sheet",
            "metal_type_id": stainless.id,
            "thickness_mm": 2.0,
        })
        self.assertAlmostEqual(profile.density, 7930.0)
        self.assertAlmostEqual(profile.weight_per_m2, 15.86, places=2)

    def test_08_manual_weight_override(self):
        profile = self.env["dw.metal.profile"].create({
            "name": "Special extrusion",
            "shape": "custom_linear",
            "manual_weight_per_m": 4.321,
        })
        self.assertAlmostEqual(profile.weight_per_m, 4.321, places=3)

    def test_09_product_weight_per_uom(self):
        self.assertAlmostEqual(self.mat_tube40.dw_weight_per_uom, 2.3864, places=3)
        self.assertAlmostEqual(self.mat_sheet.dw_weight_per_uom, 15.7, places=3)
        self.assertAlmostEqual(self.mat_tube40.dw_theoretical_weight(10.0), 23.864, places=3)

    def test_10_item_weight_from_components(self):
        family = self.env["dw.product.family"].create({
            "name": "Weight Family",
            "code": "WF",
            "product_kind": "gate",
            "weight_method": "components",
            "company_id": self.company.id,
            "dimension_ids": self._dims("width", "height"),
        })
        item = self.env["dw.opening"].create({
            "family_id": family.id,
            "finished_product_id": self.product_door.id,
            "company_id": self.company.id,
            "width_mm": 2000.0,
            "height_mm": 2000.0,
            "quantity": 3.0,
        })
        self.env["dw.opening.component"].create({
            "opening_id": item.id,
            "product_id": self.mat_tube40.id,
            "qty_per_unit": 10.0,
        })
        item.invalidate_recordset()
        self.assertAlmostEqual(item.theoretical_weight_kg, 23.864, places=3)
        self.assertAlmostEqual(item.planned_weight_kg, 71.592, places=3)

    def test_11_item_weight_per_area(self):
        family = self.env["dw.product.family"].create({
            "name": "Area Weight Family",
            "code": "AWF",
            "product_kind": "sheet_metal",
            "weight_method": "per_area",
            "weight_factor": 12.5,
            "company_id": self.company.id,
            "dimension_ids": self._dims("length", "width"),
        })
        item = self.env["dw.opening"].create({
            "family_id": family.id,
            "finished_product_id": self.product_canopy.id,
            "company_id": self.company.id,
            "length_mm": 4000.0,
            "width_mm": 2000.0,
            "quantity": 2.0,
        })
        # length x width because there is no height
        self.assertAlmostEqual(item.area_m2, 8.0, places=4)
        self.assertAlmostEqual(item.theoretical_weight_kg, 100.0, places=3)
        self.assertAlmostEqual(item.planned_weight_kg, 200.0, places=3)
