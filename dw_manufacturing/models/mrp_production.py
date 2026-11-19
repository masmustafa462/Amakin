# -*- coding: utf-8 -*-
"""Manufacturing order extensions: actual costing engine and quality gate."""

from odoo import api, fields, models
from odoo.exceptions import UserError


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    # ---- Links kept from phase 1 -------------------------------------------
    dw_opening_id = fields.Many2one(
        "dw.opening", string="Manufacturing Item", copy=False, ondelete="restrict", index=True
    )
    dw_project_id = fields.Many2one(
        "project.project", string="Manufacturing Project", copy=False, index=True
    )
    dw_sale_order_id = fields.Many2one(
        "sale.order", string="Sales Order", copy=False, index=True
    )
    dw_drawing_revision_id = fields.Many2one(
        "dw.drawing.revision", string="Drawing Revision", copy=False, index="btree_not_null"
    )
    dw_family_id = fields.Many2one(
        "dw.product.family", related="dw_opening_id.family_id", store=True, string="Product Family"
    )
    dw_partner_id = fields.Many2one(
        "res.partner", related="dw_sale_order_id.partner_id", store=True, string="Order Customer"
    )

    # ---- Actual cost --------------------------------------------------------
    dw_cost_line_ids = fields.One2many(
        "dw.production.cost.line", "production_id", string="Actual Cost Lines"
    )
    dw_cost_line_count = fields.Integer(
        string="Cost Line Count", compute="_compute_dw_cost_line_count"
    )
    dw_currency_id = fields.Many2one(
        related="company_id.currency_id", string="Cost Currency"
    )
    dw_material_cost = fields.Monetary(
        string="Actual Material Cost",
        compute="_compute_dw_costs", store=True, currency_field="dw_currency_id"
    )
    dw_labor_cost = fields.Monetary(
        string="Actual Labour Cost",
        compute="_compute_dw_costs", store=True, currency_field="dw_currency_id"
    )
    dw_machine_cost = fields.Monetary(
        string="Actual Machine Cost",
        compute="_compute_dw_costs", store=True, currency_field="dw_currency_id"
    )
    dw_outsourcing_cost = fields.Monetary(
        string="Actual Outsourcing Cost",
        compute="_compute_dw_costs", store=True, currency_field="dw_currency_id"
    )
    dw_scrap_cost = fields.Monetary(
        string="Actual Scrap Cost",
        compute="_compute_dw_costs", store=True, currency_field="dw_currency_id"
    )
    dw_overhead_cost = fields.Monetary(
        string="Actual Overhead Cost",
        compute="_compute_dw_costs", store=True, currency_field="dw_currency_id"
    )
    dw_other_cost = fields.Monetary(
        string="Actual Other Cost",
        compute="_compute_dw_costs", store=True, currency_field="dw_currency_id"
    )
    dw_actual_cost = fields.Monetary(
        string="Actual Cost",
        compute="_compute_dw_costs", store=True, currency_field="dw_currency_id"
    )
    dw_estimated_cost = fields.Monetary(
        related="dw_opening_id.estimated_cost", string="Estimated Cost",
        currency_field="dw_currency_id",
    )
    dw_cost_variance = fields.Monetary(
        string="Cost Variance",
        compute="_compute_dw_costs", store=True, currency_field="dw_currency_id"
    )
    dw_cost_variance_percent = fields.Float(
        string="Cost Variance %", compute="_compute_dw_costs", store=True
    )
    dw_last_cost_run = fields.Datetime(string="Last Cost Run", readonly=True, copy=False)

    # ---- Time and weight ----------------------------------------------------
    dw_planned_minutes = fields.Float(
        string="Planned Minutes", compute="_compute_dw_time", store=True
    )
    dw_actual_minutes = fields.Float(
        string="Actual Minutes", compute="_compute_dw_time", store=True
    )
    dw_time_variance_minutes = fields.Float(
        string="Time Variance (minutes)", compute="_compute_dw_time", store=True
    )
    dw_issued_weight_kg = fields.Float(
        string="Issued Weight (kg)", compute="_compute_dw_weight", store=True, digits=(16, 3)
    )
    dw_scrap_weight_kg = fields.Float(
        string="Scrap Weight (kg)", compute="_compute_dw_weight", store=True, digits=(16, 3)
    )
    dw_planned_weight_kg = fields.Float(
        related="dw_opening_id.planned_weight_kg", string="Planned Weight (kg)"
    )

    # ---- Quality ------------------------------------------------------------
    dw_quality_check_ids = fields.One2many(
        "dw.quality.check", "production_id", string="Quality Checks"
    )
    dw_quality_check_count = fields.Integer(
        string="Quality Check Count", compute="_compute_dw_quality_count"
    )
    dw_quality_state = fields.Selection(
        string="Quality Status",
        selection=[
            ("none", "No Check"),
            ("pending", "Pending"),
            ("pass", "Passed"),
            ("rework", "Needs Rework"),
            ("fail", "Rejected"),
        ],
        compute="_compute_dw_quality",
        store=True,
        default="none",
    )
    dw_offcut_ids = fields.One2many(
        "dw.material.offcut", "production_id", string="Off-cuts Produced"
    )

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends("dw_cost_line_ids.amount", "dw_cost_line_ids.cost_type",
                 "dw_cost_line_ids.state", "dw_opening_id.estimated_cost")
    def _compute_dw_costs(self):
        buckets = {
            "material": "dw_material_cost",
            "labor": "dw_labor_cost",
            "machine": "dw_machine_cost",
            "outsourcing": "dw_outsourcing_cost",
            "scrap": "dw_scrap_cost",
            "overhead": "dw_overhead_cost",
        }
        for production in self:
            totals = dict.fromkeys(buckets.values(), 0.0)
            other = 0.0
            lines = production.dw_cost_line_ids.filtered(lambda line: line.state != "cancel")
            for line in lines:
                field_name = buckets.get(line.cost_type)
                if field_name:
                    totals[field_name] += line.amount
                else:
                    other += line.amount
            for field_name, value in totals.items():
                production[field_name] = value
            production.dw_other_cost = other
            production.dw_actual_cost = sum(totals.values()) + other
            estimated = production.dw_opening_id.estimated_cost or 0.0
            production.dw_cost_variance = production.dw_actual_cost - estimated
            production.dw_cost_variance_percent = (
                production.dw_cost_variance / estimated * 100.0 if estimated else 0.0
            )

    @api.depends("dw_cost_line_ids")
    def _compute_dw_cost_line_count(self):
        for production in self:
            production.dw_cost_line_count = len(production.dw_cost_line_ids)

    @api.depends("workorder_ids.duration", "workorder_ids.duration_expected")
    def _compute_dw_time(self):
        for production in self:
            planned = sum(production.workorder_ids.mapped("duration_expected"))
            actual = sum(production.workorder_ids.mapped("duration"))
            production.dw_planned_minutes = planned
            production.dw_actual_minutes = actual
            production.dw_time_variance_minutes = actual - planned

    @api.depends("move_raw_ids.state", "move_raw_ids.quantity", "scrap_ids.state",
                 "scrap_ids.scrap_qty")
    def _compute_dw_weight(self):
        for production in self:
            issued = 0.0
            for move in production.move_raw_ids.filtered(lambda mv: mv.state == "done"):
                issued += (move.product_id.dw_weight_per_uom or 0.0) * move.quantity
            scrapped = 0.0
            for scrap in production.scrap_ids.filtered(lambda sc: sc.state == "done"):
                scrapped += (scrap.product_id.dw_weight_per_uom or 0.0) * scrap.scrap_qty
            production.dw_issued_weight_kg = issued
            production.dw_scrap_weight_kg = scrapped

    @api.depends("dw_quality_check_ids.result")
    def _compute_dw_quality(self):
        for production in self:
            checks = production.dw_quality_check_ids
            if not checks:
                production.dw_quality_state = "none"
            elif any(check.result == "fail" for check in checks):
                production.dw_quality_state = "fail"
            elif any(check.result == "rework" for check in checks):
                production.dw_quality_state = "rework"
            elif all(check.result == "pass" for check in checks):
                production.dw_quality_state = "pass"
            else:
                production.dw_quality_state = "pending"

    @api.depends("dw_quality_check_ids")
    def _compute_dw_quality_count(self):
        for production in self:
            production.dw_quality_check_count = len(production.dw_quality_check_ids)

    # ------------------------------------------------------------------
    # Quality generation and gate
    # ------------------------------------------------------------------
    def _dw_generate_quality_checks(self):
        Check = self.env["dw.quality.check"]
        Template = self.env["dw.quality.template"]
        for production in self:
            family = production.dw_opening_id.family_id
            domain = [("active", "=", True), ("company_id", "=", production.company_id.id)]
            templates = Template.browse()
            if family:
                templates |= Template.search(domain + [("family_id", "=", family.id)])
            templates |= Template.search(domain + [("family_id", "=", False)])
            existing = production.dw_quality_check_ids.mapped("template_id")
            for template in templates:
                if template in existing:
                    continue
                check = Check.create({
                    "template_id": template.id,
                    "stage": template.stage,
                    "is_mandatory": template.is_mandatory,
                    "company_id": production.company_id.id,
                    "production_id": production.id,
                    "opening_id": production.dw_opening_id.id,
                    "project_id": production.dw_project_id.id,
                    "product_id": production.product_id.id,
                    "partner_id": production.dw_partner_id.id,
                })
                check.write({
                    "line_ids": [
                        (0, 0, Check._prepare_line_values(line)) for line in template.line_ids
                    ]
                })
        return True

    def action_dw_generate_quality_checks(self):
        self._dw_generate_quality_checks()
        return True

    def _dw_check_quality_gate(self):
        for production in self:
            if not production.company_id.dw_block_on_quality_failure:
                continue
            blocking = production.dw_quality_check_ids.filtered(
                lambda check: check.is_mandatory and check.result != "pass"
            )
            if blocking:
                raise UserError(
                    self.env._(
                        "Manufacturing order %(order)s cannot be closed: mandatory quality "
                        "checks are not passed (%(checks)s).",
                        order=production.name,
                        checks=", ".join(blocking.mapped("display_name")),
                    )
                )

    def button_mark_done(self):
        self._dw_check_quality_gate()
        result = super().button_mark_done()
        done = self.filtered(lambda production: production.state == "done")
        if done:
            done._dw_recompute_actual_cost()
            for production in done:
                if production.dw_opening_id and production.dw_opening_id.state == "production":
                    production.dw_opening_id.state = "ready"
        return result

    # ------------------------------------------------------------------
    # Actual costing engine
    # ------------------------------------------------------------------
    def action_dw_recompute_actual_cost(self):
        self._dw_recompute_actual_cost()
        return True

    def _dw_recompute_actual_cost(self):
        """Rebuild the actual cost ledger of these orders. Safe to run repeatedly."""
        CostLine = self.env["dw.production.cost.line"].sudo()
        for production in self:
            targets = {}
            targets.update(production._dw_cost_targets_material())
            targets.update(production._dw_cost_targets_scrap())
            targets.update(production._dw_cost_targets_time())
            targets.update(production._dw_cost_targets_expense())
            targets.update(production._dw_cost_targets_rework())
            # Overhead depends on the other buckets, so it is computed last.
            targets.update(production._dw_cost_targets_overhead(targets))

            existing = CostLine.search([
                ("production_id", "=", production.id),
                ("is_automatic", "=", True),
            ])
            by_key = {line.source_key: line for line in existing}
            common = production._dw_cost_common_values()

            for key, values in targets.items():
                payload = dict(common, **values)
                payload.update({"source_key": key, "is_automatic": True})
                line = by_key.pop(key, None)
                if not line:
                    CostLine.create(payload)
                    continue
                if line.state == "approved":
                    changed = line._record_revision(
                        payload.get("amount", 0.0),
                        self.env._("Recomputed by the costing engine."),
                    )
                    if changed and production.company_id.dw_allow_update_approved_cost:
                        line.write(payload)
                    continue
                line.write(payload)

            obsolete = CostLine.browse([line.id for line in by_key.values()])
            approved = obsolete.filtered(lambda line: line.state == "approved")
            removable = obsolete - approved
            if removable:
                removable.unlink()
            for line in approved:
                line._record_revision(
                    line.amount,
                    self.env._("Source document no longer exists; approved line kept."),
                )
            production.dw_last_cost_run = fields.Datetime.now()
        return True

    def _dw_cost_common_values(self):
        self.ensure_one()
        return {
            "company_id": self.company_id.id,
            "currency_id": self.company_id.currency_id.id,
            "production_id": self.id,
            "opening_id": self.dw_opening_id.id or False,
            "sale_order_id": self.dw_sale_order_id.id or False,
            "project_id": self.dw_project_id.id or False,
            "family_id": self.dw_family_id.id or False,
            "partner_id": self.dw_partner_id.id or False,
            "analytic_account_id": self.dw_project_id.account_id.id or False,
            "state": "confirmed",
        }

    def _dw_move_value(self, move):
        """Actual valued amount of a done stock move.

        Odoo 19 stores inventory valuation directly on ``stock.move.value``
        (``stock.valuation.layer`` no longer exists). ``standard_price`` is only
        used when the move carries no valuation at all.
        """
        self.ensure_one()
        if move.is_valued and move.value:
            return abs(move.value)
        return abs(move.product_id.standard_price * move.quantity)

    def _dw_cost_targets_material(self):
        self.ensure_one()
        targets = {}
        for move in self.move_raw_ids:
            if move.state != "done" or not move.quantity:
                continue
            sign = 1.0 if move.location_dest_id.usage == "production" else -1.0
            product = move.product_id
            value = self._dw_move_value(move) * sign
            if product.dw_is_customer_supplied:
                value = 0.0
            targets["move:%s" % move.id] = {
                "cost_type": "material",
                "date": move.date or fields.Datetime.now(),
                "product_id": product.id,
                "description": product.display_name,
                "quantity": move.quantity * sign,
                "uom_id": move.product_uom.id,
                "unit_price": (value / move.quantity) if move.quantity else 0.0,
                "amount": value,
                "weight_kg": (product.dw_weight_per_uom or 0.0) * move.quantity * sign,
                "stock_move_id": move.id,
                "account_move_id": move.account_move_id.id or False,
            }
        return targets

    def _dw_cost_targets_scrap(self):
        self.ensure_one()
        targets = {}
        for scrap in self.scrap_ids:
            if scrap.state != "done":
                continue
            done_moves = scrap.move_ids.filtered(lambda move: move.state == "done")
            # Material scrapped straight out of stock is an extra cost. Material
            # scrapped from the production location was already consumed by a raw
            # move, so it is recorded with a zero amount to avoid double counting.
            from_stock = any(move.location_id.usage == "internal" for move in done_moves)
            amount = scrap.dw_value if from_stock else 0.0
            targets["scrap:%s" % scrap.id] = {
                "cost_type": "scrap",
                "date": scrap.date_done or fields.Datetime.now(),
                "product_id": scrap.product_id.id,
                "description": self.env._("Scrap %s", scrap.name),
                "quantity": scrap.scrap_qty,
                "uom_id": scrap.product_uom_id.id,
                "unit_price": (amount / scrap.scrap_qty) if scrap.scrap_qty else 0.0,
                "amount": amount,
                "weight_kg": scrap.dw_weight_kg,
                "stock_move_id": done_moves[:1].id or False,
                "note": False if from_stock else self.env._(
                    "Already consumed as raw material; recorded for weight tracking only."
                ),
            }
        return targets

    def _dw_cost_targets_time(self):
        self.ensure_one()
        targets = {}
        Rate = self.env["dw.labor.rate"]
        company = self.company_id
        machine_enabled = not company.dw_workcenter_cost_is_total
        hour_uom = self.env.ref("uom.product_uom_hour", raise_if_not_found=False)
        for workorder in self.workorder_ids:
            operation_type = workorder.dw_operation_type_id or self.env["dw.operation.type"].search(
                [("workcenter_id", "=", workorder.workcenter_id.id),
                 ("company_id", "in", [False, company.id])],
                limit=1,
            )
            logged = 0.0
            for entry in workorder.time_ids:
                duration = entry.duration or 0.0
                if not duration:
                    continue
                logged += duration
                rate = Rate._find_rate(
                    company=company,
                    workcenter=workorder.workcenter_id,
                    operation_type=operation_type,
                    user=entry.user_id,
                    date=(entry.date_start or fields.Datetime.now()).date(),
                )
                hourly = rate.hourly_cost if rate else 0.0
                targets["wo_time:%s" % entry.id] = {
                    "cost_type": "labor",
                    "date": entry.date_start or fields.Datetime.now(),
                    "description": self.env._(
                        "Labour %(wo)s - %(user)s",
                        wo=workorder.name or "",
                        user=entry.user_id.name or "",
                    ),
                    "quantity": duration / 60.0,
                    "uom_id": hour_uom.id if hour_uom else False,
                    "unit_price": hourly,
                    "amount": (duration / 60.0) * hourly,
                    "workorder_id": workorder.id,
                }
            residual = (workorder.duration or 0.0) - logged
            if residual > 0.0001:
                rate = Rate._find_rate(
                    company=company,
                    workcenter=workorder.workcenter_id,
                    operation_type=operation_type,
                )
                hourly = rate.hourly_cost if rate else 0.0
                targets["wo_labor:%s" % workorder.id] = {
                    "cost_type": "labor",
                    "date": workorder.date_finished or fields.Datetime.now(),
                    "description": self.env._("Labour %s (unlogged time)", workorder.name or ""),
                    "quantity": residual / 60.0,
                    "uom_id": hour_uom.id if hour_uom else False,
                    "unit_price": hourly,
                    "amount": (residual / 60.0) * hourly,
                    "workorder_id": workorder.id,
                }
            if machine_enabled and workorder.duration:
                machine_rate = workorder.costs_hour or workorder.workcenter_id.costs_hour or 0.0
                if machine_rate:
                    targets["wo_machine:%s" % workorder.id] = {
                        "cost_type": "machine",
                        "date": workorder.date_finished or fields.Datetime.now(),
                        "description": self.env._(
                            "Machine %s", workorder.workcenter_id.display_name or ""
                        ),
                        "quantity": workorder.duration / 60.0,
                        "uom_id": hour_uom.id if hour_uom else False,
                        "unit_price": machine_rate,
                        "amount": (workorder.duration / 60.0) * machine_rate,
                        "workorder_id": workorder.id,
                    }
        return targets

    def _dw_cost_targets_expense(self):
        self.ensure_one()
        targets = {}
        entries = self.env["dw.project.cost.entry"].search([
            ("production_id", "=", self.id),
            ("state", "=", "approved"),
        ])
        mapping = {
            "transport": "transport",
            "installation": "installation",
            "contractor": "contractor",
            "outsourcing": "outsourcing",
            "site": "direct",
            "rental": "direct",
            "direct": "direct",
            "other": "direct",
        }
        for entry in entries:
            targets["expense:%s" % entry.id] = {
                "cost_type": mapping.get(entry.cost_type, "direct"),
                "date": fields.Datetime.to_datetime(entry.date),
                "product_id": entry.product_id.id or False,
                "description": entry.name,
                "quantity": entry.quantity,
                "uom_id": entry.uom_id.id or False,
                "unit_price": entry.unit_price,
                "amount": entry.amount,
                "analytic_account_id": entry.analytic_account_id.id or False,
            }
        return targets

    def _dw_cost_targets_rework(self):
        self.ensure_one()
        targets = {}
        issues = self.env["dw.quality.issue"].search([
            ("production_id", "=", self.id),
            ("rework_cost", ">", 0.0),
        ])
        for issue in issues:
            targets["rework:%s" % issue.id] = {
                "cost_type": "rework",
                "date": fields.Datetime.now(),
                "description": self.env._("Rework: %s", issue.name),
                "quantity": 1.0,
                "unit_price": issue.rework_cost,
                "amount": issue.rework_cost,
            }
        return targets

    def _dw_cost_targets_overhead(self, other_targets):
        self.ensure_one()
        rule = self.env["dw.overhead.rule"]._find_rule(
            company=self.company_id, family=self.dw_family_id
        )
        if not rule:
            return {}
        material = sum(
            values.get("amount", 0.0)
            for values in other_targets.values()
            if values.get("cost_type") in ("material", "scrap")
        )
        labor = sum(
            values.get("amount", 0.0)
            for values in other_targets.values()
            if values.get("cost_type") in ("labor", "machine")
        )
        direct = sum(values.get("amount", 0.0) for values in other_targets.values())
        hours = sum(self.workorder_ids.mapped("duration")) / 60.0
        amount = rule._compute_amount(
            self.dw_opening_id,
            material_cost=material,
            labor_cost=labor,
            direct_cost=direct,
            hours=hours,
            order_value=direct,
        )
        if not amount:
            return {}
        return {
            "overhead:%s" % rule.id: {
                "cost_type": "overhead",
                "date": fields.Datetime.now(),
                "description": self.env._("Overhead: %s", rule.name),
                "quantity": 1.0,
                "unit_price": amount,
                "amount": amount,
            }
        }

    def action_dw_view_cost_lines(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Actual Cost Lines"),
            "res_model": "dw.production.cost.line",
            "view_mode": "list,pivot,form",
            "domain": [("production_id", "=", self.id)],
            "context": {"default_production_id": self.id},
        }

    def action_dw_view_quality_checks(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Quality Checks"),
            "res_model": "dw.quality.check",
            "view_mode": "list,form",
            "domain": [("production_id", "=", self.id)],
            "context": {"default_production_id": self.id},
        }


class MrpWorkorder(models.Model):
    _inherit = "mrp.workorder"

    dw_opening_id = fields.Many2one(
        related="production_id.dw_opening_id", store=True, string="Manufacturing Item"
    )
    dw_project_id = fields.Many2one(
        related="production_id.dw_project_id", store=True, string="Project"
    )
    dw_operation_type_id = fields.Many2one("dw.operation.type", string="Fabrication Operation")
    dw_currency_id = fields.Many2one(
        related="company_id.currency_id", string="Work Order Currency"
    )
    dw_labor_cost = fields.Monetary(
        string="Labour Cost",
        compute="_compute_dw_workorder_costs", currency_field="dw_currency_id"
    )
    dw_machine_cost = fields.Monetary(
        string="Machine Cost",
        compute="_compute_dw_workorder_costs", currency_field="dw_currency_id"
    )

    @api.depends("duration", "workcenter_id", "costs_hour")
    def _compute_dw_workorder_costs(self):
        Rate = self.env["dw.labor.rate"]
        for workorder in self:
            hours = (workorder.duration or 0.0) / 60.0
            rate = Rate._find_rate(
                company=workorder.company_id,
                workcenter=workorder.workcenter_id,
                operation_type=workorder.dw_operation_type_id,
            )
            workorder.dw_labor_cost = hours * (rate.hourly_cost if rate else 0.0)
            workorder.dw_machine_cost = hours * (
                workorder.costs_hour or workorder.workcenter_id.costs_hour or 0.0
            )


class MrpBom(models.Model):
    _inherit = "mrp.bom"

    dw_opening_id = fields.Many2one(
        "dw.opening", string="Manufacturing Item", index="btree_not_null", copy=False
    )
    dw_project_id = fields.Many2one(
        "project.project", string="Fabrication Project", index="btree_not_null", copy=False
    )
    dw_partner_id = fields.Many2one("res.partner", string="Customer", copy=False)
    dw_drawing_revision_id = fields.Many2one(
        "dw.drawing.revision", string="Drawing Revision", copy=False
    )
    dw_is_item_specific = fields.Boolean(
        string="Item Specific",
        copy=False,
        help="Generated for one manufacturing item; it never replaces a generic bill of materials.",
    )
    dw_is_reference = fields.Boolean(
        string="Reference Template",
        help="Reference bills of materials are copied, never consumed directly.",
    )

    def action_dw_copy_for_item(self):
        """Duplicate a reference BoM into an item specific copy."""
        self.ensure_one()
        copy = self.copy({
            "code": "%s (copy)" % (self.code or self.display_name),
            "dw_is_reference": False,
            "dw_is_item_specific": True,
        })
        return {
            "type": "ir.actions.act_window",
            "res_model": "mrp.bom",
            "res_id": copy.id,
            "view_mode": "form",
        }
