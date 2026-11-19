# -*- coding: utf-8 -*-
"""Company level configuration for the metal fabrication application."""

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    dw_block_on_quality_failure = fields.Boolean(
        string="Block MO on failed mandatory quality check",
        default=True,
    )
    dw_allow_update_approved_cost = fields.Boolean(
        string="Allow the engine to update approved cost lines",
        default=False,
        help="When disabled, an approved cost line keeps its amount and every "
             "recomputation only writes an audit revision.",
    )
    dw_workcenter_cost_is_total = fields.Boolean(
        string="Work center cost per hour already includes labour",
        default=False,
        help="Enable when mrp.workcenter costs_hour is an all-in rate; the engine "
             "then stops adding a separate machine cost line.",
    )
    dw_cost_overrun_percent = fields.Float(string="Cost Overrun Alert (%)", default=10.0)
    dw_scrap_percent_limit = fields.Float(string="Scrap Alert (%)", default=5.0)
    dw_min_margin_percent = fields.Float(string="Minimum Margin (%)", default=10.0)
    dw_time_overrun_percent = fields.Float(string="Time Overrun Alert (%)", default=20.0)
    dw_require_project_on_mo = fields.Boolean(
        string="Require a project on manufacturing orders", default=False
    )
    dw_revenue_includes_tax = fields.Boolean(
        string="Report revenue including tax", default=False
    )


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    dw_block_on_quality_failure = fields.Boolean(
        related="company_id.dw_block_on_quality_failure", readonly=False
    )
    dw_allow_update_approved_cost = fields.Boolean(
        related="company_id.dw_allow_update_approved_cost", readonly=False
    )
    dw_workcenter_cost_is_total = fields.Boolean(
        related="company_id.dw_workcenter_cost_is_total", readonly=False
    )
    dw_cost_overrun_percent = fields.Float(
        related="company_id.dw_cost_overrun_percent", readonly=False
    )
    dw_scrap_percent_limit = fields.Float(
        related="company_id.dw_scrap_percent_limit", readonly=False
    )
    dw_min_margin_percent = fields.Float(
        related="company_id.dw_min_margin_percent", readonly=False
    )
    dw_time_overrun_percent = fields.Float(
        related="company_id.dw_time_overrun_percent", readonly=False
    )
    dw_require_project_on_mo = fields.Boolean(
        related="company_id.dw_require_project_on_mo", readonly=False
    )
    dw_revenue_includes_tax = fields.Boolean(
        related="company_id.dw_revenue_includes_tax", readonly=False
    )
