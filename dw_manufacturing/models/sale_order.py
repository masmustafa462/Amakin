# -*- coding: utf-8 -*-
"""Sales side of the metal fabrication flow."""

from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    dw_is_manufacturing_quote = fields.Boolean(
        string="Metal Fabrication Order", tracking=True
    )
    dw_relationship = fields.Selection(
        [
            ("external", "External Customer"),
            ("main_same_entity", "Main Company - Same Legal Entity"),
            ("main_separate_entity", "Main Company - Separate Legal Entity"),
        ],
        string="Relationship",
        default="external",
        tracking=True,
        help="Same legal entity work produces no accounting revenue; only an internal "
             "transfer value is reported for performance measurement.",
    )
    dw_project_id = fields.Many2one(
        "project.project",
        string="Manufacturing Project",
        copy=False,
        tracking=True,
        domain="[('company_id', 'in', [False, company_id])]",
    )
    dw_auto_create_project = fields.Boolean(
        string="Create Project Automatically", default=True
    )
    dw_opening_ids = fields.One2many(
        "dw.opening", "sale_order_id", string="Manufacturing Items"
    )
    dw_opening_count = fields.Integer(
        string="Item Count", compute="_compute_dw_opening_count"
    )
    dw_estimated_cost = fields.Monetary(
        string="Estimated Cost", compute="_compute_dw_totals", store=True
    )
    dw_actual_cost = fields.Monetary(
        string="Actual Cost", compute="_compute_dw_totals", store=True
    )
    dw_expected_profit = fields.Monetary(
        string="Expected Profit", compute="_compute_dw_totals", store=True
    )
    dw_actual_profit = fields.Monetary(
        string="Actual Profit", compute="_compute_dw_totals", store=True
    )
    dw_actual_margin_percent = fields.Float(
        string="Actual Margin %", compute="_compute_dw_totals", store=True
    )
    dw_internal_transfer_value = fields.Monetary(
        string="Internal Transfer Value", compute="_compute_dw_totals", store=True
    )
    dw_total_weight_kg = fields.Float(
        string="Total Weight (kg)", compute="_compute_dw_totals", store=True, digits=(16, 3)
    )

    @api.depends("dw_opening_ids")
    def _compute_dw_opening_count(self):
        for order in self:
            order.dw_opening_count = len(order.dw_opening_ids)

    @api.depends(
        "dw_opening_ids.estimated_cost",
        "dw_opening_ids.actual_cost",
        "dw_opening_ids.expected_profit",
        "dw_opening_ids.actual_profit",
        "dw_opening_ids.actual_revenue",
        "dw_opening_ids.internal_transfer_value",
        "dw_opening_ids.planned_weight_kg",
    )
    def _compute_dw_totals(self):
        for order in self:
            items = order.dw_opening_ids
            order.dw_estimated_cost = sum(items.mapped("estimated_cost"))
            order.dw_actual_cost = sum(items.mapped("actual_cost"))
            order.dw_expected_profit = sum(items.mapped("expected_profit"))
            order.dw_actual_profit = sum(items.mapped("actual_profit"))
            order.dw_internal_transfer_value = sum(items.mapped("internal_transfer_value"))
            order.dw_total_weight_kg = sum(items.mapped("planned_weight_kg"))
            revenue = sum(items.mapped("actual_revenue")) or order.dw_internal_transfer_value
            order.dw_actual_margin_percent = (
                order.dw_actual_profit / revenue * 100.0 if revenue else 0.0
            )

    def action_confirm(self):
        result = super().action_confirm()
        # An order that carries manufacturing items is a fabrication order even if
        # the box was never ticked by hand; otherwise its items would stay stuck
        # at "quoted" after the confirmation.
        for order in self.filtered(
            lambda so: so.dw_is_manufacturing_quote or so.dw_opening_ids
        ):
            order.dw_is_manufacturing_quote = True
            if order.dw_auto_create_project and not order.dw_project_id:
                order.dw_project_id = self.env["project.project"].create({
                    "name": "%s - %s" % (order.name, order.partner_id.display_name),
                    "partner_id": order.partner_id.id,
                    "company_id": order.company_id.id,
                })
            order.dw_opening_ids.filtered(
                lambda item: item.state == "quoted"
            ).write({"state": "confirmed"})
        return result

    def action_dw_view_openings(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Manufacturing Items"),
            "res_model": "dw.opening",
            "view_mode": "list,form",
            "domain": [("sale_order_id", "=", self.id)],
            "context": {"default_sale_order_id": self.id},
        }

    def action_dw_create_manufacturing_orders(self):
        for order in self:
            items = order.dw_opening_ids.filtered(
                lambda item: item.state == "confirmed" and not item.production_ids
            )
            items.action_create_manufacturing_order()
        return True


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    dw_opening_id = fields.Many2one(
        "dw.opening", string="Manufacturing Item", copy=False,
        ondelete="set null", index="btree_not_null",
    )


class ProjectProject(models.Model):
    _inherit = "project.project"

    dw_opening_ids = fields.One2many("dw.opening", "project_id", string="Manufacturing Items")
    dw_opening_count = fields.Integer(
        string="Manufacturing Item Count", compute="_compute_dw_profitability"
    )
    dw_production_ids = fields.One2many(
        "mrp.production", "dw_project_id", string="Manufacturing Orders"
    )
    dw_currency_id = fields.Many2one(
        related="company_id.currency_id", string="Fabrication Currency"
    )
    dw_expected_revenue = fields.Monetary(
        string="Expected Revenue",
        compute="_compute_dw_profitability", currency_field="dw_currency_id"
    )
    dw_invoiced_revenue = fields.Monetary(
        string="Invoiced Revenue",
        compute="_compute_dw_profitability", currency_field="dw_currency_id"
    )
    dw_internal_transfer_value = fields.Monetary(
        string="Internal Transfer Value",
        compute="_compute_dw_profitability", currency_field="dw_currency_id"
    )
    dw_estimated_cost = fields.Monetary(
        string="Estimated Cost",
        compute="_compute_dw_profitability", currency_field="dw_currency_id"
    )
    dw_actual_cost = fields.Monetary(
        string="Actual Cost",
        compute="_compute_dw_profitability", currency_field="dw_currency_id"
    )
    dw_expected_profit = fields.Monetary(
        string="Expected Profit",
        compute="_compute_dw_profitability", currency_field="dw_currency_id"
    )
    dw_actual_profit = fields.Monetary(
        string="Actual Profit",
        compute="_compute_dw_profitability", currency_field="dw_currency_id"
    )
    dw_expected_margin_percent = fields.Float(
        string="Expected Margin %", compute="_compute_dw_profitability"
    )
    dw_actual_margin_percent = fields.Float(
        string="Actual Margin %", compute="_compute_dw_profitability"
    )
    dw_cost_variance = fields.Monetary(
        string="Cost Variance",
        compute="_compute_dw_profitability", currency_field="dw_currency_id"
    )
    dw_revenue_variance = fields.Monetary(
        string="Revenue Variance",
        compute="_compute_dw_profitability", currency_field="dw_currency_id"
    )
    dw_completion_percent = fields.Float(
        string="Completion %", compute="_compute_dw_profitability"
    )
    dw_wip_value = fields.Monetary(
        compute="_compute_dw_profitability", currency_field="dw_currency_id",
        string="Work in Progress Value",
    )

    def _compute_dw_profitability(self):
        Entry = self.env["dw.project.cost.entry"]
        for project in self:
            items = project.dw_opening_ids
            project.dw_opening_count = len(items)
            project.dw_expected_revenue = sum(items.mapped("expected_revenue"))
            project.dw_invoiced_revenue = sum(items.mapped("invoiced_revenue"))
            project.dw_internal_transfer_value = sum(items.mapped("internal_transfer_value"))
            project.dw_estimated_cost = sum(items.mapped("estimated_cost"))
            item_cost = sum(items.mapped("actual_cost"))
            # Project level expenses that are not attached to a manufacturing order.
            standalone = Entry.search([
                ("project_id", "=", project.id),
                ("state", "=", "approved"),
                ("production_id", "=", False),
            ])
            project.dw_actual_cost = item_cost + sum(standalone.mapped("amount"))
            revenue = project.dw_invoiced_revenue or project.dw_internal_transfer_value
            project.dw_expected_profit = project.dw_expected_revenue - project.dw_estimated_cost
            project.dw_actual_profit = revenue - project.dw_actual_cost
            project.dw_expected_margin_percent = (
                project.dw_expected_profit / project.dw_expected_revenue * 100.0
                if project.dw_expected_revenue else 0.0
            )
            project.dw_actual_margin_percent = (
                project.dw_actual_profit / revenue * 100.0 if revenue else 0.0
            )
            project.dw_cost_variance = project.dw_actual_cost - project.dw_estimated_cost
            project.dw_revenue_variance = revenue - project.dw_expected_revenue
            delivered = len(items.filtered(lambda item: item.state in ("ready", "delivered")))
            project.dw_completion_percent = (
                delivered / len(items) * 100.0 if items else 0.0
            )
            project.dw_wip_value = max(project.dw_actual_cost - 0.0, 0.0) if items.filtered(
                lambda item: item.state == "production"
            ) else 0.0

    def action_dw_view_items(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Manufacturing Items"),
            "res_model": "dw.opening",
            "view_mode": "list,form",
            "domain": [("project_id", "=", self.id)],
            "context": {"default_project_id": self.id},
        }
