# -*- coding: utf-8 -*-
"""Read-only SQL views feeding the analysis dashboards.

Both models are plain database views (``_auto = False``): they never duplicate
data and always reflect the current ledger.
"""

from odoo import fields, models, tools


class DwProfitabilityReport(models.Model):
    """One row per manufacturing item, with every dimension needed to slice
    profitability by project, sales order, customer, family, company or period.
    """

    _name = "dw.profitability.report"
    _description = "Fabrication Profitability Analysis"
    _auto = False
    _order = "date desc"
    _rec_name = "opening_id"

    opening_id = fields.Many2one("dw.opening", string="Manufacturing Item", readonly=True)
    date = fields.Datetime(readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    currency_id = fields.Many2one("res.currency", readonly=True)
    project_id = fields.Many2one("project.project", string="Project", readonly=True)
    sale_order_id = fields.Many2one("sale.order", string="Sales Order", readonly=True)
    partner_id = fields.Many2one("res.partner", string="Customer", readonly=True)
    family_id = fields.Many2one("dw.product.family", string="Product Family", readonly=True)
    product_id = fields.Many2one("product.product", string="Finished Product", readonly=True)
    production_id = fields.Many2one("mrp.production", string="Manufacturing Order", readonly=True)
    state = fields.Char(readonly=True)
    relationship = fields.Char(string="Relationship", readonly=True)

    quantity = fields.Float(readonly=True)
    weight_kg = fields.Float(string="Planned Weight (kg)", readonly=True)
    area_m2 = fields.Float(string="Area (m2)", readonly=True)
    length_m = fields.Float(string="Length (m)", readonly=True)

    estimated_cost = fields.Monetary(readonly=True)
    actual_cost = fields.Monetary(readonly=True)
    cost_variance = fields.Monetary(readonly=True)
    expected_revenue = fields.Monetary(readonly=True)
    invoiced_revenue = fields.Monetary(readonly=True)
    actual_revenue = fields.Monetary(readonly=True)
    internal_transfer_value = fields.Monetary(readonly=True)
    expected_profit = fields.Monetary(readonly=True)
    actual_profit = fields.Monetary(readonly=True)

    cost_per_kg = fields.Float(string="Cost per kg", readonly=True, aggregator="avg")
    cost_per_m2 = fields.Float(string="Cost per m2", readonly=True, aggregator="avg")
    cost_per_m = fields.Float(string="Cost per Linear Meter", readonly=True, aggregator="avg")

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    o.id AS id,
                    o.id AS opening_id,
                    COALESCE(so.date_order, o.create_date) AS date,
                    o.company_id AS company_id,
                    o.currency_id AS currency_id,
                    o.project_id AS project_id,
                    o.sale_order_id AS sale_order_id,
                    o.partner_id AS partner_id,
                    o.family_id AS family_id,
                    o.finished_product_id AS product_id,
                    o.production_id AS production_id,
                    o.state AS state,
                    COALESCE(so.dw_relationship, 'external') AS relationship,
                    o.quantity AS quantity,
                    o.planned_weight_kg AS weight_kg,
                    o.area_m2 * o.quantity AS area_m2,
                    o.total_length_m * o.quantity AS length_m,
                    o.estimated_cost AS estimated_cost,
                    o.actual_cost AS actual_cost,
                    o.cost_variance AS cost_variance,
                    o.expected_revenue AS expected_revenue,
                    o.invoiced_revenue AS invoiced_revenue,
                    o.actual_revenue AS actual_revenue,
                    o.internal_transfer_value AS internal_transfer_value,
                    o.expected_profit AS expected_profit,
                    o.actual_profit AS actual_profit,
                    CASE WHEN o.planned_weight_kg > 0
                         THEN o.actual_cost / o.planned_weight_kg ELSE 0 END AS cost_per_kg,
                    CASE WHEN (o.area_m2 * o.quantity) > 0
                         THEN o.actual_cost / (o.area_m2 * o.quantity) ELSE 0 END AS cost_per_m2,
                    CASE WHEN (o.total_length_m * o.quantity) > 0
                         THEN o.actual_cost / (o.total_length_m * o.quantity) ELSE 0 END AS cost_per_m
                FROM dw_opening o
                LEFT JOIN sale_order so ON so.id = o.sale_order_id
                WHERE o.active IS TRUE
            )
        """ % self._table)


class DwCostVarianceReport(models.Model):
    """One row per manufacturing order: cost, time and weight variances."""

    _name = "dw.cost.variance.report"
    _description = "Cost and Time Variance Analysis"
    _auto = False
    _order = "date_start desc"
    _rec_name = "production_id"

    production_id = fields.Many2one("mrp.production", string="Manufacturing Order", readonly=True)
    opening_id = fields.Many2one("dw.opening", string="Manufacturing Item", readonly=True)
    project_id = fields.Many2one("project.project", string="Project", readonly=True)
    partner_id = fields.Many2one("res.partner", string="Customer", readonly=True)
    family_id = fields.Many2one("dw.product.family", string="Product Family", readonly=True)
    product_id = fields.Many2one("product.product", string="Product", readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    currency_id = fields.Many2one("res.currency", readonly=True)
    date_start = fields.Datetime(readonly=True)
    state = fields.Char(readonly=True)

    estimated_cost = fields.Monetary(readonly=True)
    actual_cost = fields.Monetary(readonly=True)
    cost_variance = fields.Monetary(readonly=True)
    material_cost = fields.Monetary(readonly=True)
    labor_cost = fields.Monetary(readonly=True)
    machine_cost = fields.Monetary(readonly=True)
    outsourcing_cost = fields.Monetary(readonly=True)
    scrap_cost = fields.Monetary(readonly=True)
    overhead_cost = fields.Monetary(readonly=True)

    estimated_material_cost = fields.Monetary(readonly=True)
    material_variance = fields.Monetary(readonly=True)
    estimated_labor_cost = fields.Monetary(readonly=True)
    labor_variance = fields.Monetary(readonly=True)

    planned_minutes = fields.Float(readonly=True)
    actual_minutes = fields.Float(readonly=True)
    time_variance_minutes = fields.Float(readonly=True)

    planned_weight_kg = fields.Float(readonly=True)
    issued_weight_kg = fields.Float(readonly=True)
    scrap_weight_kg = fields.Float(readonly=True)
    weight_variance_kg = fields.Float(readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    mo.id AS id,
                    mo.id AS production_id,
                    mo.dw_opening_id AS opening_id,
                    mo.dw_project_id AS project_id,
                    mo.dw_partner_id AS partner_id,
                    mo.dw_family_id AS family_id,
                    mo.product_id AS product_id,
                    mo.company_id AS company_id,
                    c.currency_id AS currency_id,
                    mo.date_start AS date_start,
                    mo.state AS state,
                    COALESCE(o.estimated_cost, 0) AS estimated_cost,
                    COALESCE(mo.dw_actual_cost, 0) AS actual_cost,
                    COALESCE(mo.dw_cost_variance, 0) AS cost_variance,
                    COALESCE(mo.dw_material_cost, 0) AS material_cost,
                    COALESCE(mo.dw_labor_cost, 0) AS labor_cost,
                    COALESCE(mo.dw_machine_cost, 0) AS machine_cost,
                    COALESCE(mo.dw_outsourcing_cost, 0) AS outsourcing_cost,
                    COALESCE(mo.dw_scrap_cost, 0) AS scrap_cost,
                    COALESCE(mo.dw_overhead_cost, 0) AS overhead_cost,
                    COALESCE(o.material_cost, 0) AS estimated_material_cost,
                    COALESCE(mo.dw_material_cost, 0) - COALESCE(o.material_cost, 0) AS material_variance,
                    COALESCE(o.labor_cost, 0) + COALESCE(o.machine_cost, 0) AS estimated_labor_cost,
                    COALESCE(mo.dw_labor_cost, 0) + COALESCE(mo.dw_machine_cost, 0)
                        - COALESCE(o.labor_cost, 0) - COALESCE(o.machine_cost, 0) AS labor_variance,
                    COALESCE(mo.dw_planned_minutes, 0) AS planned_minutes,
                    COALESCE(mo.dw_actual_minutes, 0) AS actual_minutes,
                    COALESCE(mo.dw_time_variance_minutes, 0) AS time_variance_minutes,
                    COALESCE(o.planned_weight_kg, 0) AS planned_weight_kg,
                    COALESCE(mo.dw_issued_weight_kg, 0) AS issued_weight_kg,
                    COALESCE(mo.dw_scrap_weight_kg, 0) AS scrap_weight_kg,
                    COALESCE(mo.dw_issued_weight_kg, 0) - COALESCE(o.planned_weight_kg, 0) AS weight_variance_kg
                FROM mrp_production mo
                LEFT JOIN dw_opening o ON o.id = mo.dw_opening_id
                LEFT JOIN res_company c ON c.id = mo.company_id
                WHERE mo.dw_opening_id IS NOT NULL
            )
        """ % self._table)
