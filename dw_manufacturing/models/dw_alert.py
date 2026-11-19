# -*- coding: utf-8 -*-
"""In-system alerts.

Thresholds are configurable per company and can be overridden per product
family. Alerts are plain records shown in a dedicated list plus a chatter
message on the related document, so nothing depends on Enterprise features.
"""

from odoo import api, fields, models

ALERT_TYPES = [
    ("cost_overrun", "Actual cost above estimate"),
    ("scrap_overrun", "Scrap above allowed percentage"),
    ("quality_failure", "Mandatory quality check failed"),
    ("rework", "Rework recorded"),
    ("unreleased_drawing", "Unreleased drawing used"),
    ("no_project", "Manufacturing order without project"),
    ("cost_without_source", "Cost line without source document"),
    ("low_margin", "Margin below threshold"),
    ("late_production", "Planned manufacturing time exceeded"),
    ("missing_final_check", "Final inspection not performed"),
    ("rejected_delivery", "Attempt to deliver a rejected product"),
]


class DwAlertRule(models.Model):
    _name = "dw.alert.rule"
    _description = "Alert Threshold"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    family_id = fields.Many2one("dw.product.family", string="Product Family")
    alert_type = fields.Selection(ALERT_TYPES, required=True, default="cost_overrun")
    threshold = fields.Float(
        string="Threshold",
        help="Cost overrun and scrap thresholds are percentages; margin is a minimum percentage.",
    )
    severity = fields.Selection(
        [("info", "Information"), ("warning", "Warning"), ("critical", "Critical")],
        default="warning",
        required=True,
    )
    notify_user_ids = fields.Many2many("res.users", string="Notify")
    note = fields.Text(translate=True)

    @api.model
    def _get_rule(self, company, alert_type, family=None):
        domain = [
            ("active", "=", True),
            ("company_id", "=", company.id),
            ("alert_type", "=", alert_type),
        ]
        if family:
            rule = self.search(domain + [("family_id", "=", family.id)], limit=1)
            if rule:
                return rule
        return self.search(domain + [("family_id", "=", False)], limit=1)


class DwAlert(models.Model):
    _name = "dw.alert"
    _description = "Manufacturing Alert"
    _order = "id desc"

    name = fields.Char(required=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    date = fields.Datetime(default=fields.Datetime.now, index=True)
    alert_type = fields.Selection(ALERT_TYPES, required=True, index=True)
    severity = fields.Selection(
        [("info", "Information"), ("warning", "Warning"), ("critical", "Critical")],
        default="warning",
        required=True,
        index=True,
    )
    rule_id = fields.Many2one("dw.alert.rule", string="Rule")
    opening_id = fields.Many2one("dw.opening", string="Manufacturing Item", index="btree_not_null")
    production_id = fields.Many2one(
        "mrp.production", string="Manufacturing Order", index="btree_not_null"
    )
    project_id = fields.Many2one("project.project", string="Project", index="btree_not_null")
    value = fields.Float()
    threshold = fields.Float()
    description = fields.Text()
    state = fields.Selection(
        [("open", "Open"), ("acknowledged", "Acknowledged"), ("closed", "Closed")],
        default="open",
        required=True,
        index=True,
    )
    user_id = fields.Many2one("res.users", string="Owner")

    _alert_uniq = models.UniqueIndex(
        "(company_id, alert_type, production_id, opening_id) WHERE state = 'open'"
    )

    def action_acknowledge(self):
        self.write({"state": "acknowledged", "user_id": self.env.user.id})
        return True

    def action_close(self):
        self.write({"state": "closed"})
        return True

    @api.model
    def _raise_alert(self, alert_type, company, description, value=0.0,
                     opening=None, production=None, project=None, family=None):
        rule = self.env["dw.alert.rule"]._get_rule(company, alert_type, family)
        severity = rule.severity if rule else "warning"
        existing = self.search([
            ("company_id", "=", company.id),
            ("alert_type", "=", alert_type),
            ("production_id", "=", production.id if production else False),
            ("opening_id", "=", opening.id if opening else False),
            ("state", "=", "open"),
        ], limit=1)
        values = {
            "name": dict(ALERT_TYPES).get(alert_type, alert_type),
            "company_id": company.id,
            "alert_type": alert_type,
            "severity": severity,
            "rule_id": rule.id if rule else False,
            "opening_id": opening.id if opening else False,
            "production_id": production.id if production else False,
            "project_id": project.id if project else False,
            "value": value,
            "threshold": rule.threshold if rule else 0.0,
            "description": description,
        }
        if existing:
            existing.write(values)
            return existing
        return self.create(values)

    @api.model
    def _cron_scan_alerts(self):
        """Scan open manufacturing orders and raise the configured alerts."""
        Production = self.env["mrp.production"]
        productions = Production.search([
            ("dw_opening_id", "!=", False),
            ("state", "not in", ("cancel",)),
        ])
        for production in productions:
            production._dw_scan_alerts()
        return True
