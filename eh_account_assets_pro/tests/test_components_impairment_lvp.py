# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
Tests for component accounting, impairment, and AU low-value pool.
"""

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import EhAssetTestCase


@tagged('eh_account_assets_pro', 'integration', 'post_install', '-at_install')
class TestComponentAccounting(EhAssetTestCase):

    def test_component_links_to_parent(self):
        parent = self._make_asset(code='BLDG-001', acquisition_cost=1_000_000.0)
        component = self._make_asset(
            code='BLDG-001-HVAC',
            acquisition_cost=80_000.0,
            parent_asset_id=parent.id,
        )
        self.assertEqual(component.parent_asset_id, parent)
        self.assertEqual(parent.component_count, 1)
        self.assertEqual(parent.component_ids, component)

    def test_rolled_up_cost_includes_components(self):
        parent = self._make_asset(code='BLDG-002', acquisition_cost=900_000.0)
        self._make_asset(
            code='BLDG-002-HVAC',
            acquisition_cost=70_000.0,
            parent_asset_id=parent.id,
        )
        self._make_asset(
            code='BLDG-002-LIFT',
            acquisition_cost=30_000.0,
            parent_asset_id=parent.id,
        )
        parent.invalidate_recordset(['rolled_up_cost'])
        self.assertAlmostEqual(parent.rolled_up_cost, 1_000_000.0, places=2)
        self.assertEqual(parent.component_count, 2)

    def test_leaf_asset_rolled_up_equals_own(self):
        a = self._make_asset(code='LEAF-1', acquisition_cost=12000.0)
        self.assertEqual(a.rolled_up_cost, a.acquisition_cost)
        self.assertEqual(a.rolled_up_nbv, a.net_book_value)


@tagged('eh_account_assets_pro', 'integration', 'post_install', '-at_install')
class TestImpairment(EhAssetTestCase):

    def setUp(self):
        super().setUp()
        self.asset = self._make_asset(
            acquisition_cost=50_000.0,
            method='straight_line',
            useful_life_months=60,
            prorate_first_period=False,
        )
        self.asset.action_compute_schedule()
        self.asset.action_activate()

    def test_impairment_charge_reduces_nbv(self):
        before = self.asset.net_book_value
        impairment = self.env['eh.asset.impairment'].create({
            'asset_id': self.asset.id,
            'impairment_date': '2026-06-30',
            'amount': 5_000.0,
            'is_reversal': False,
            'reason': 'Recoverable amount fell below carrying amount',
        })
        impairment.action_post()
        self.asset.invalidate_recordset(
            ['net_book_value', 'accumulated_impairment'],
        )
        self.assertAlmostEqual(
            self.asset.net_book_value, before - 5_000.0, places=2,
        )
        self.assertAlmostEqual(
            self.asset.accumulated_impairment, 5_000.0, places=2,
        )

    def test_draft_impairment_does_not_change_nbv(self):
        """Reported net book value must reflect only posted impairments.
        A draft (unposted) impairment must not reduce NBV or accumulated
        impairment; posting it applies the reduction. This keeps the
        displayed carrying amount in sync with the posted ledger."""
        before_nbv = self.asset.net_book_value
        before_accum = self.asset.accumulated_impairment
        impairment = self.env['eh.asset.impairment'].create({
            'asset_id': self.asset.id,
            'impairment_date': '2026-06-30',
            'amount': 5_000.0,
            'is_reversal': False,
            'reason': 'Draft impairment pending review',
        })
        self.assertEqual(impairment.state, 'draft')
        self.asset.invalidate_recordset(
            ['net_book_value', 'accumulated_impairment'],
        )
        # Draft impairment leaves reported figures untouched.
        self.assertAlmostEqual(
            self.asset.net_book_value, before_nbv, places=2,
        )
        self.assertAlmostEqual(
            self.asset.accumulated_impairment, before_accum, places=2,
        )
        # Posting the impairment applies the reduction.
        impairment.action_post()
        self.asset.invalidate_recordset(
            ['net_book_value', 'accumulated_impairment'],
        )
        self.assertAlmostEqual(
            self.asset.net_book_value, before_nbv - 5_000.0, places=2,
        )
        self.assertAlmostEqual(
            self.asset.accumulated_impairment, before_accum + 5_000.0,
            places=2,
        )

    def test_impairment_reversal_restores_nbv(self):
        # Charge first, then reverse (both posted to the ledger).
        self.env['eh.asset.impairment'].create({
            'asset_id': self.asset.id,
            'impairment_date': '2026-06-30',
            'amount': 5_000.0,
            'reason': 'Initial loss',
        }).action_post()
        self.asset.invalidate_recordset(
            ['net_book_value', 'accumulated_impairment'],
        )
        baseline = self.asset.net_book_value
        self.env['eh.asset.impairment'].create({
            'asset_id': self.asset.id,
            'impairment_date': '2026-12-31',
            'amount': 2_000.0,
            'is_reversal': True,
            'reason': 'Conditions reversed',
        }).action_post()
        self.asset.invalidate_recordset(
            ['net_book_value', 'accumulated_impairment'],
        )
        self.assertAlmostEqual(
            self.asset.net_book_value, baseline + 2_000.0, places=2,
        )
        self.assertAlmostEqual(
            self.asset.accumulated_impairment, 3_000.0, places=2,
        )

    def test_reversal_above_charges_blocked(self):
        self.env['eh.asset.impairment'].create({
            'asset_id': self.asset.id,
            'impairment_date': '2026-06-30',
            'amount': 1_000.0,
            'reason': 'Small loss',
        })
        with self.assertRaises(ValidationError):
            self.env['eh.asset.impairment'].create({
                'asset_id': self.asset.id,
                'impairment_date': '2026-12-31',
                'amount': 2_000.0,
                'is_reversal': True,
                'reason': 'Reversal exceeds charges',
            })

    def test_impairment_post_creates_move(self):
        impairment = self.env['eh.asset.impairment'].create({
            'asset_id': self.asset.id,
            'impairment_date': '2026-06-30',
            'amount': 5_000.0,
            'reason': 'Test charge',
        })
        impairment.action_post()
        self.assertEqual(impairment.state, 'posted')
        self.assertTrue(impairment.move_id)
        self.assertEqual(impairment.move_id.state, 'posted')

    def test_non_manager_cannot_post_impairment(self):
        """SoD: a non-manager (group_eh_user only) is blocked from posting
        an impairment charge to the GL; a manager succeeds and the move
        balances."""
        impairment = self.env['eh.asset.impairment'].create({
            'asset_id': self.asset.id,
            'impairment_date': '2026-06-30',
            'amount': 5_000.0,
            'reason': 'SoD test charge',
        })
        clerk = self._make_non_manager_user()
        with self.assertRaises(UserError):
            impairment.with_user(clerk).action_post()
        self.assertEqual(impairment.state, 'draft')
        self.assertFalse(impairment.move_id)
        # Manager path succeeds and the move balances.
        impairment.action_post()
        self.assertEqual(impairment.state, 'posted')
        move = impairment.move_id
        self.assertEqual(move.state, 'posted')
        self.assertAlmostEqual(
            sum(move.line_ids.mapped('debit')),
            sum(move.line_ids.mapped('credit')),
            places=2,
        )

    def test_non_manager_cannot_post_depreciation(self):
        """SoD: a non-manager cannot post a depreciation line to the GL;
        a manager succeeds and the move balances."""
        line = self.asset.depreciation_line_ids.sorted('sequence')[0]
        clerk = self._make_non_manager_user()
        with self.assertRaises(UserError):
            line.with_user(clerk).action_post()
        self.assertFalse(line.is_posted)
        self.assertFalse(line.move_id)
        # Manager path succeeds and the move balances.
        line.action_post()
        self.assertTrue(line.is_posted)
        move = line.move_id
        self.assertEqual(move.state, 'posted')
        self.assertAlmostEqual(
            sum(move.line_ids.mapped('debit')),
            sum(move.line_ids.mapped('credit')),
            places=2,
        )

    def _impair_asset(self, **overrides):
        """Build, schedule, and activate a clean straight-line asset for
        the IAS 36 schedule tests. 60,000 over 60 months, no salvage, no
        proration: original depreciation is a flat 1,000 per period."""
        vals = {
            'acquisition_cost': 60_000.0,
            'method': 'straight_line',
            'useful_life_months': 60,
            'salvage_value': 0.0,
            'prorate_first_period': False,
        }
        vals.update(overrides)
        asset = self._make_asset(**vals)
        asset.action_compute_schedule()
        asset.action_activate()
        return asset

    def _post_first_lines(self, asset, count):
        for line in asset.depreciation_line_ids.sorted('sequence')[:count]:
            line.action_post()

    def test_impairment_rebuilds_remaining_schedule(self):
        """IAS 36.63: after an impairment charge is posted, future
        depreciation is re-amortised on the impaired carrying amount over
        the remaining life, so total depreciation plus impairment never
        exceeds cost less salvage (no over-depreciation)."""
        asset = self._impair_asset(code='IMP-REBUILD')
        self._post_first_lines(asset, 5)
        asset.invalidate_recordset(['net_book_value', 'total_depreciated'])
        self.assertAlmostEqual(asset.net_book_value, 55_000.0, places=2)

        self.env['eh.asset.impairment'].create({
            'asset_id': asset.id,
            'impairment_date': '2026-06-30',
            'amount': 11_000.0,
            'reason': 'Recoverable amount below carrying amount',
            'impairment_account_id': self.account_impairment.id,
            'accumulated_account_id': self.account_accum_dep.id,
        }).action_post()
        asset.invalidate_recordset(
            ['net_book_value', 'accumulated_impairment'],
        )

        self.assertAlmostEqual(asset.net_book_value, 44_000.0, places=2)
        unposted = asset.depreciation_line_ids.filtered(
            lambda l: not l.is_posted,
        )
        # Remaining schedule now re-amortises only the impaired NBV.
        self.assertAlmostEqual(
            sum(unposted.mapped('amount')), 44_000.0, places=2,
        )
        # Total scheduled depreciation plus impairment equals cost.
        total = sum(asset.depreciation_line_ids.mapped('amount'))
        self.assertAlmostEqual(
            total + asset.accumulated_impairment, 60_000.0, places=2,
        )

    def test_reversal_capped_at_depreciated_historical_cost(self):
        """IAS 36.117: a reversal cannot lift the carrying amount above the
        depreciated historical cost. After an impairment plus continued
        depreciation on the lower base, reversing the full charge would
        breach that ceiling and is blocked even though it does not exceed
        the cumulative charge."""
        asset = self._impair_asset(code='IMP-CEIL')
        self._post_first_lines(asset, 2)
        self.env['eh.asset.impairment'].create({
            'asset_id': asset.id,
            'impairment_date': '2026-03-31',
            'amount': 12_000.0,
            'reason': 'Loss',
            'impairment_account_id': self.account_impairment.id,
            'accumulated_account_id': self.account_accum_dep.id,
        }).action_post()
        # Post three of the rebuilt (lower) periods so depreciation has run
        # on the impaired base.
        for line in (
            asset.depreciation_line_ids
            .filtered(lambda l: not l.is_posted)
            .sorted('sequence')[:3]
        ):
            line.action_post()
        with self.assertRaises(ValidationError):
            self.env['eh.asset.impairment'].create({
                'asset_id': asset.id,
                'impairment_date': '2026-06-30',
                'amount': 12_000.0,
                'is_reversal': True,
                'reason': 'Full reversal exceeds the IAS 36.117 ceiling',
            })

    def test_reversal_within_ceiling_allowed(self):
        """A reversal that stays under both the cumulative charge and the
        depreciated historical cost ceiling is permitted."""
        asset = self._impair_asset(code='IMP-OK')
        self._post_first_lines(asset, 2)
        self.env['eh.asset.impairment'].create({
            'asset_id': asset.id,
            'impairment_date': '2026-03-31',
            'amount': 12_000.0,
            'reason': 'Loss',
            'impairment_account_id': self.account_impairment.id,
            'accumulated_account_id': self.account_accum_dep.id,
        }).action_post()
        for line in (
            asset.depreciation_line_ids
            .filtered(lambda l: not l.is_posted)
            .sorted('sequence')[:3]
        ):
            line.action_post()
        reversal = self.env['eh.asset.impairment'].create({
            'asset_id': asset.id,
            'impairment_date': '2026-06-30',
            'amount': 3_000.0,
            'is_reversal': True,
            'reason': 'Partial recovery within the ceiling',
        })
        self.assertTrue(reversal)


@tagged('eh_account_assets_pro', 'integration', 'post_install', '-at_install')
class TestLowValuePool(EhAssetTestCase):

    def setUp(self):
        super().setUp()
        # Distinct pool asset account so the transfer reclassification move
        # moves carrying value between different GL accounts (not onto the
        # asset's own account).
        self.account_pool = self._ensure_account(
            self.env, '1540', 'Low-Value Pool', 'asset_fixed',
        )
        self.pool = self.env['eh.asset.lvp.pool'].create({
            'name': 'LVP 2026',
            'company_id': self.company.id,
            'threshold': 1000.0,
            'pool_account_id': self.account_pool.id,
            'accumulated_account_id': self.account_accum_dep.id,
            'expense_account_id': self.account_dep_expense.id,
            'journal_id': self.journal_misc.id,
        })

    def test_transfer_eligible_asset(self):
        small_asset = self._make_asset(
            code='LV-1', acquisition_cost=800.0,
        )
        self.pool.action_transfer_asset(small_asset)
        self.assertEqual(small_asset.lvp_pool_id, self.pool)
        self.assertEqual(self.pool.asset_count, 1)
        self.assertAlmostEqual(self.pool.transferred_in_total, 800.0, places=2)

    def test_transfer_above_threshold_blocked(self):
        big_asset = self._make_asset(
            code='LV-2', acquisition_cost=5000.0,
        )
        with self.assertRaises(UserError):
            self.pool.action_transfer_asset(big_asset)

    def test_compute_year_first_year_rate(self):
        # Asset transferred in 2026 -> first-year rate (18.75%) applies
        # to additions; opening balance is zero in year 1.
        small_asset = self._make_asset(
            code='LV-3',
            acquisition_cost=1000.0,
            in_service_date='2026-03-15',
        )
        self.pool.action_transfer_asset(small_asset)
        line = self.pool.action_compute_year(year=2026)
        # additions = 1000, opening = 0
        # depreciation = 0 + 0.1875 * 1000 = 187.5
        self.assertAlmostEqual(line.amount, 187.5, places=2)

    def test_compute_year_subsequent_year_rate(self):
        # Asset added in 2025 -> appears in opening balance for 2026.
        small_asset = self._make_asset(
            code='LV-4',
            acquisition_cost=1000.0,
            in_service_date='2025-06-01',
        )
        self.pool.action_transfer_asset(small_asset)
        # Year 1 (2025): additions=1000, opening=0 -> 187.5
        line_2025 = self.pool.action_compute_year(year=2025)
        # Year 2 (2026): the same asset is now in opening_balance
        # (post prior-year dep). opening = 1000 - 187.5 = 812.5
        # depreciation = 0.375 * 812.5 = 304.6875 -> rounded
        line_2026 = self.pool.action_compute_year(year=2026)
        self.assertAlmostEqual(line_2025.amount, 187.5, places=2)
        self.assertAlmostEqual(line_2026.amount, 304.69, places=2)

    def test_compute_year_idempotent(self):
        small_asset = self._make_asset(
            code='LV-5', acquisition_cost=800.0,
            in_service_date='2026-01-01',
        )
        self.pool.action_transfer_asset(small_asset)
        self.pool.action_compute_year(year=2026)
        with self.assertRaises(UserError):
            self.pool.action_compute_year(year=2026)

    def test_transfer_posts_balanced_reclass_move(self):
        """When the pool carries its own GL accounts, transferring an asset
        posts the balanced reclassification move claimed in the docstring:
        the asset's net book value lands in the pool asset account and the
        entry balances by construction."""
        small_asset = self._make_asset(
            code='LV-RECLASS', acquisition_cost=900.0,
        )
        nbv = small_asset.net_book_value
        self.pool.action_transfer_asset(small_asset)
        move = self.env['account.move'].search([
            ('ref', 'like', 'LVP transfer%'),
            ('company_id', '=', self.company.id),
        ], limit=1)
        self.assertTrue(move, "A reclassification move should be posted.")
        self.assertEqual(move.state, 'posted')
        total_debit = sum(move.line_ids.mapped('debit'))
        total_credit = sum(move.line_ids.mapped('credit'))
        self.assertAlmostEqual(total_debit, total_credit, places=2)
        # Net book value lands in the pool asset account on the debit side.
        pool_line = move.line_ids.filtered(
            lambda l: l.account_id == self.pool.pool_account_id,
        )
        self.assertAlmostEqual(sum(pool_line.mapped('debit')), nbv, places=2)

    def test_tax_only_pool_transfer_posts_no_move(self):
        """A pool with no GL accounts is a tax-only pool: the transfer
        records the operational link but posts no journal entry, matching
        the corrected docstring."""
        tax_pool = self.env['eh.asset.lvp.pool'].create({
            'name': 'LVP tax-only',
            'company_id': self.company.id,
            'threshold': 1000.0,
        })
        small_asset = self._make_asset(
            code='LV-TAXONLY', acquisition_cost=700.0,
        )
        before = self.env['account.move'].search_count([
            ('company_id', '=', self.company.id),
        ])
        tax_pool.action_transfer_asset(small_asset)
        after = self.env['account.move'].search_count([
            ('company_id', '=', self.company.id),
        ])
        self.assertEqual(before, after)
        self.assertEqual(small_asset.lvp_pool_id, tax_pool)

    def test_non_manager_cannot_post_pool_depreciation(self):
        """SoD: a non-manager cannot post the pool's annual depreciation to
        the GL; a manager succeeds and the move balances."""
        small_asset = self._make_asset(
            code='LV-SOD', acquisition_cost=1000.0,
            in_service_date='2026-03-15',
        )
        self.pool.action_transfer_asset(small_asset)
        line = self.pool.action_compute_year(year=2026)
        clerk = self._make_non_manager_user()
        with self.assertRaises(UserError):
            line.with_user(clerk).action_post()
        self.assertFalse(line.is_posted)
        self.assertFalse(line.move_id)
        # Manager path succeeds and the move balances.
        line.action_post()
        self.assertTrue(line.is_posted)
        move = line.move_id
        self.assertEqual(move.state, 'posted')
        self.assertAlmostEqual(
            sum(move.line_ids.mapped('debit')),
            sum(move.line_ids.mapped('credit')),
            places=2,
        )
