# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
Integration tests for the outbound Peppol transmission flow.

Exercise action_eh_send_peppol against the manual default (queued), a
registered mock adapter (delivered with a transmission id), and an
adapter that fails (error recorded + UserError). No network.
"""

from odoo.tests import tagged

from odoo.addons.eh_account_base.tests.common import (
    EhAccountIntegrationTestCase,
)
from odoo.addons.eh_account_einvoice_peppol.tools import access_point_registry


class _MockAccessPoint:
    def __init__(self, config):
        self.config = config

    def submit(self, xml_bytes, recipient_endpoint_id,
               recipient_endpoint_scheme):
        return {'transmission_id': 'TX-1', 'status': 'delivered',
                'raw_response': 'OK'}

    def poll(self, since_iso):
        return []


class _ErrorAccessPoint:
    def __init__(self, config):
        self.config = config

    def submit(self, xml_bytes, recipient_endpoint_id,
               recipient_endpoint_scheme):
        raise access_point_registry.AccessPointError("gateway down")

    def poll(self, since_iso):
        return []


access_point_registry.register_adapter(
    'eh_test_mock_ap', lambda config: _MockAccessPoint(config))
access_point_registry.register_adapter(
    'eh_test_err_ap', lambda config: _ErrorAccessPoint(config))


@tagged('post_install', '-at_install')
class PeppolSendTest(EhAccountIntegrationTestCase):

    def setUp(self):
        super().setUp()
        au = self.env.ref('base.au')
        self.env.company.write({
            'country_id': au.id, 'vat': '83914571673',
            'street': '1 Seller Street', 'city': 'Sydney', 'zip': '2000',
        })
        self.env.company.partner_id.write({
            'eh_peppol_endpoint_scheme': '0151',
            'eh_peppol_endpoint_id': '83914571673',
        })
        self.partner = self.env['res.partner'].create({
            'name': 'Buyer Co', 'is_company': True, 'country_id': au.id,
            'vat': '53004085616',
            'eh_peppol_endpoint_scheme': '0151',
            'eh_peppol_endpoint_id': '53004085616',
            'street': '2 Buyer Street', 'city': 'Sydney', 'zip': '2000',
        })
        if not self.env['account.journal'].search(
            [('type', '=', 'sale'),
             ('company_id', '=', self.env.company.id)], limit=1):
            self.env['account.journal'].create({
                'name': 'Sales', 'code': 'INV', 'type': 'sale',
                'company_id': self.env.company.id,
            })

    def _post_invoice(self):
        product = self.env['product.product'].create({
            'name': 'Test Service', 'type': 'service',
        })
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'currency_id': self.env.company.currency_id.id,
            'invoice_date': '2026-05-01',
            'invoice_line_ids': [(0, 0, {
                'product_id': product.id, 'name': 'Consulting',
                'quantity': 10.0, 'price_unit': 100.0,
                'account_id': self.account_revenue.id,
            })],
        })
        move.action_post()
        return move

    def test_send_manual_is_queued(self):
        self.env.company.eh_peppol_access_point_key = 'manual'
        move = self._post_invoice()
        move.action_eh_send_peppol()
        self.assertEqual(move.eh_peppol_transmission_status, 'queued')
        self.assertEqual(move.eh_peppol_ap_key, 'manual')
        self.assertTrue(move.eh_peppol_sent_at)

    def test_send_via_adapter_records_delivery(self):
        self.env.company.eh_peppol_access_point_key = 'eh_test_mock_ap'
        self.env.company.eh_peppol_ap_config = '{"api_key": "k"}'
        move = self._post_invoice()
        move.action_eh_send_peppol()
        self.assertEqual(move.eh_peppol_transmission_status, 'delivered')
        self.assertEqual(move.eh_peppol_transmission_id, 'TX-1')
        self.assertEqual(move.eh_peppol_ap_key, 'eh_test_mock_ap')

    def test_send_adapter_error_records_and_notifies(self):
        self.env.company.eh_peppol_access_point_key = 'eh_test_err_ap'
        move = self._post_invoice()
        # No raise: the error is recorded on the move and returned as a
        # danger notification so the status survives the transaction.
        result = move.action_eh_send_peppol()
        self.assertEqual(result.get('tag'), 'display_notification')
        self.assertEqual(result['params']['type'], 'danger')
        self.assertEqual(move.eh_peppol_transmission_status, 'error')
        self.assertIn('gateway down',
                      move.eh_peppol_transmission_message or '')
