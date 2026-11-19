# -*- coding: utf-8 -*-
"""Alert detection attached to manufacturing orders."""

from odoo import fields, models


class MrpProductionAlerts(models.Model):
    _inherit = "mrp.production"

    def _dw_alert_threshold(self, alert_type, fallback):
        self.ensure_one()
        rule = self.env["dw.alert.rule"]._get_rule(
            self.company_id, alert_type, self.dw_family_id
        )
        return rule.threshold if rule and rule.threshold else fallback

    def _dw_scan_alerts(self):
        Alert = self.env["dw.alert"]
        for production in self:
            company = production.company_id
            item = production.dw_opening_id
            project = production.dw_project_id
            family = production.dw_family_id

            # 1. Actual cost above estimate.
            estimated = production.dw_estimated_cost or 0.0
            if estimated:
                overrun = (production.dw_actual_cost - estimated) / estimated * 100.0
                limit = production._dw_alert_threshold(
                    "cost_overrun", company.dw_cost_overrun_percent
                )
                if overrun > limit:
                    Alert._raise_alert(
                        "cost_overrun", company,
                        self.env._(
                            "Actual cost exceeds the estimate by %.2f%% on %s.",
                            overrun, production.name,
                        ),
                        value=overrun, opening=item, production=production,
                        project=project, family=family,
                    )

            # 2. Scrap above the allowed percentage (by weight when available).
            planned_weight = production.dw_planned_weight_kg or 0.0
            if planned_weight and production.dw_scrap_weight_kg:
                scrap_percent = production.dw_scrap_weight_kg / planned_weight * 100.0
                limit = production._dw_alert_threshold(
                    "scrap_overrun", company.dw_scrap_percent_limit
                )
                if scrap_percent > limit:
                    Alert._raise_alert(
                        "scrap_overrun", company,
                        self.env._(
                            "Scrap reached %.2f%% of the planned weight on %s.",
                            scrap_percent, production.name,
                        ),
                        value=scrap_percent, opening=item, production=production,
                        project=project, family=family,
                    )

            # 3. Failed mandatory quality check.
            failed = production.dw_quality_check_ids.filtered(
                lambda check: check.is_mandatory and check.result == "fail"
            )
            if failed:
                Alert._raise_alert(
                    "quality_failure", company,
                    self.env._(
                        "Mandatory quality checks failed: %s",
                        ", ".join(failed.mapped("display_name")),
                    ),
                    opening=item, production=production, project=project, family=family,
                )

            # 4. Rework recorded.
            rework = self.env["dw.quality.issue"].search_count([
                ("production_id", "=", production.id),
                ("rework_required", "=", True),
            ])
            if rework:
                Alert._raise_alert(
                    "rework", company,
                    self.env._("%s rework issue(s) recorded on %s.", rework, production.name),
                    value=rework, opening=item, production=production,
                    project=project, family=family,
                )

            # 5. Unreleased drawing used.
            revision = production.dw_drawing_revision_id
            if revision and revision.state != "released":
                Alert._raise_alert(
                    "unreleased_drawing", company,
                    self.env._(
                        "Drawing revision %s is not released but is used on %s.",
                        revision.display_name, production.name,
                    ),
                    opening=item, production=production, project=project, family=family,
                )

            # 6. Manufacturing order without project.
            if company.dw_require_project_on_mo and not project:
                Alert._raise_alert(
                    "no_project", company,
                    self.env._("Manufacturing order %s has no project.", production.name),
                    opening=item, production=production, family=family,
                )

            # 7. Cost line without a source document.
            orphan = production.dw_cost_line_ids.filtered(
                lambda line: line.is_automatic and not line.source_key
            )
            manual_unapproved = production.dw_cost_line_ids.filtered(
                lambda line: not line.is_automatic and line.state == "draft" and line.amount
            )
            if orphan or manual_unapproved:
                Alert._raise_alert(
                    "cost_without_source", company,
                    self.env._(
                        "%s cost line(s) have no source document or approval on %s.",
                        len(orphan) + len(manual_unapproved), production.name,
                    ),
                    value=len(orphan) + len(manual_unapproved),
                    opening=item, production=production, project=project, family=family,
                )

            # 8. Margin below the configured floor.
            if item:
                revenue = item.actual_revenue or item.internal_transfer_value or item.expected_revenue
                if revenue:
                    margin = (revenue - production.dw_actual_cost) / revenue * 100.0
                    limit = production._dw_alert_threshold(
                        "low_margin", company.dw_min_margin_percent
                    )
                    if margin < limit:
                        Alert._raise_alert(
                            "low_margin", company,
                            self.env._(
                                "Margin dropped to %.2f%% on %s.", margin, production.name
                            ),
                            value=margin, opening=item, production=production,
                            project=project, family=family,
                        )

            # 9. Planned manufacturing time exceeded.
            planned = production.dw_planned_minutes
            if planned:
                overrun = (production.dw_actual_minutes - planned) / planned * 100.0
                limit = production._dw_alert_threshold(
                    "late_production", company.dw_time_overrun_percent
                )
                if overrun > limit:
                    Alert._raise_alert(
                        "late_production", company,
                        self.env._(
                            "Manufacturing time exceeded the plan by %.2f%% on %s.",
                            overrun, production.name,
                        ),
                        value=overrun, opening=item, production=production,
                        project=project, family=family,
                    )

            # 10. Final inspection missing on a finished order.
            if production.state == "done":
                final_checks = production.dw_quality_check_ids.filtered(
                    lambda check: check.stage in ("final", "pre_delivery")
                    and check.state == "done"
                )
                if not final_checks:
                    Alert._raise_alert(
                        "missing_final_check", company,
                        self.env._("No final inspection recorded on %s.", production.name),
                        opening=item, production=production, project=project, family=family,
                    )
        return True

    def _dw_recompute_actual_cost(self):
        result = super()._dw_recompute_actual_cost()
        self._dw_scan_alerts()
        return result


class DwOpeningAlerts(models.Model):
    _inherit = "dw.opening"

    alert_ids = fields.One2many("dw.alert", "opening_id", string="Alerts")
    alert_count = fields.Integer(compute="_compute_alert_count")

    def _compute_alert_count(self):
        data = self.env["dw.alert"]._read_group(
            [("opening_id", "in", self.ids), ("state", "=", "open")],
            ["opening_id"],
            ["__count"],
        )
        mapping = {item.id: count for item, count in data}
        for item in self:
            item.alert_count = mapping.get(item.id, 0)

    def action_view_alerts(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Alerts"),
            "res_model": "dw.alert",
            "view_mode": "list,form",
            "domain": [("opening_id", "=", self.id)],
        }

    def action_set_delivered(self):
        for item in self:
            if item.quality_state == "fail":
                self.env["dw.alert"]._raise_alert(
                    "rejected_delivery", item.company_id,
                    self.env._(
                        "Attempt to deliver rejected item %s.", item.name
                    ),
                    opening=item, project=item.project_id, family=item.family_id,
                )
        return super().action_set_delivered()
