# -*- coding: utf-8 -*-
"""Lightweight quality management.

Odoo Community has no Quality application, so the module ships its own minimal
but complete implementation: templates per product family, checks at every
stage, numeric / selection / boolean results, corrective actions, rework costs
and a hard block on closing a manufacturing order with a failed mandatory check.
"""

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

STAGE_SELECTION = [
    ("receipt", "Material Receipt"),
    ("in_process", "In Process"),
    ("post_operation", "After Operation"),
    ("final", "Final Product"),
    ("pre_delivery", "Before Delivery / Installation"),
]

MEASURE_SELECTION = [
    ("numeric", "Numeric Measurement"),
    ("boolean", "Yes / No"),
    ("selection", "Choice"),
    ("text", "Free Text"),
]


class DwQualityTemplate(models.Model):
    _name = "dw.quality.template"
    _description = "Quality Inspection Template"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    family_id = fields.Many2one("dw.product.family", string="Product Family", index=True)
    stage = fields.Selection(STAGE_SELECTION, required=True, default="final")
    operation_type_id = fields.Many2one(
        "dw.operation.type",
        string="Operation",
        help="Only used for in-process and after-operation templates.",
    )
    is_mandatory = fields.Boolean(
        default=True,
        help="A mandatory template blocks the manufacturing order until it passes.",
    )
    line_ids = fields.One2many(
        "dw.quality.template.line", "template_id", string="Tests", copy=True
    )
    note = fields.Text(translate=True)

    @api.constrains("line_ids")
    def _check_lines(self):
        for template in self:
            if template.active and not template.line_ids:
                raise ValidationError(
                    self.env._("Quality template %s has no test line.", template.name)
                )


class DwQualityTemplateLine(models.Model):
    _name = "dw.quality.template.line"
    _description = "Quality Template Test"
    _order = "sequence, id"

    template_id = fields.Many2one(
        "dw.quality.template", required=True, ondelete="cascade", index=True
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(string="Test", required=True, translate=True)
    measure_type = fields.Selection(MEASURE_SELECTION, default="numeric", required=True)
    uom_label = fields.Char(string="Unit", translate=True)
    target_value = fields.Float(string="Target Value", digits=(16, 4))
    min_value = fields.Float(string="Minimum Value", digits=(16, 4))
    max_value = fields.Float(string="Maximum Value", digits=(16, 4))
    tolerance = fields.Float(string="Tolerance", digits=(16, 4), help="Applied around the target when no range is set.")
    expected_boolean = fields.Boolean(string="Expected Answer", default=True)
    allowed_values = fields.Char(
        string="Allowed Choices", help="Comma separated list of acceptable answers."
    )
    is_mandatory = fields.Boolean(string="Mandatory", default=True)
    is_blocking = fields.Boolean(
        string="Blocking", default=True,
        help="Failing this test blocks the release of the product."
    )
    instruction = fields.Text(translate=True)

    @api.constrains("min_value", "max_value")
    def _check_range(self):
        for line in self:
            if line.max_value and line.min_value and line.min_value > line.max_value:
                raise ValidationError(
                    self.env._("The minimum value cannot be greater than the maximum value.")
                )

    def _effective_range(self):
        self.ensure_one()
        if self.min_value or self.max_value:
            return self.min_value, self.max_value
        if self.tolerance:
            return self.target_value - self.tolerance, self.target_value + self.tolerance
        return None, None


class DwQualityCheck(models.Model):
    _name = "dw.quality.check"
    _description = "Quality Check"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(required=True, copy=False, default=lambda self: self.env._("New"))
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    template_id = fields.Many2one("dw.quality.template", string="Template", index=True)
    stage = fields.Selection(STAGE_SELECTION, required=True, default="final", tracking=True)
    opening_id = fields.Many2one(
        "dw.opening", string="Manufacturing Item", index=True, ondelete="cascade"
    )
    production_id = fields.Many2one(
        "mrp.production", string="Manufacturing Order", index=True, ondelete="cascade"
    )
    workorder_id = fields.Many2one("mrp.workorder", string="Work Order", index="btree_not_null")
    picking_id = fields.Many2one("stock.picking", string="Transfer", index="btree_not_null")
    project_id = fields.Many2one("project.project", string="Project", index="btree_not_null")
    product_id = fields.Many2one("product.product", string="Product")
    partner_id = fields.Many2one("res.partner", string="Customer")
    is_mandatory = fields.Boolean(default=True, tracking=True)
    state = fields.Selection(
        [("todo", "To Do"), ("done", "Done"), ("cancel", "Cancelled")],
        default="todo",
        required=True,
        tracking=True,
    )
    result = fields.Selection(
        [
            ("pending", "Pending"),
            ("pass", "Passed"),
            ("rework", "Needs Rework"),
            ("fail", "Rejected"),
        ],
        default="pending",
        required=True,
        tracking=True,
    )
    line_ids = fields.One2many("dw.quality.check.line", "check_id", string="Tests")
    inspector_id = fields.Many2one("res.users", string="Inspector", default=lambda self: self.env.user)
    inspection_date = fields.Datetime(default=fields.Datetime.now)
    release_decision = fields.Selection(
        [
            ("hold", "On Hold"),
            ("release", "Released"),
            ("conditional", "Conditional Release"),
            ("reject", "Rejected"),
        ],
        default="hold",
        tracking=True,
    )
    corrective_action = fields.Text(translate=True)
    responsible_id = fields.Many2one("res.users", string="Action Owner")
    rework_cost = fields.Monetary(string="Rework Cost")
    issue_ids = fields.One2many("dw.quality.issue", "check_id", string="Issues")
    note = fields.Text(translate=True)
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "dw_quality_check_attachment_rel",
        "check_id",
        "attachment_id",
        string="Photos and Files",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", self.env._("New")) == self.env._("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "dw.quality.check"
                ) or self.env._("New")
        return super().create(vals_list)

    @api.onchange("template_id")
    def _onchange_template_id(self):
        if not self.template_id:
            return
        self.stage = self.template_id.stage
        self.is_mandatory = self.template_id.is_mandatory
        self.line_ids = [(5, 0, 0)] + [
            (0, 0, self._prepare_line_values(line)) for line in self.template_id.line_ids
        ]

    @api.model
    def _prepare_line_values(self, template_line):
        return {
            "template_line_id": template_line.id,
            "sequence": template_line.sequence,
            "name": template_line.name,
            "measure_type": template_line.measure_type,
            "uom_label": template_line.uom_label,
            "target_value": template_line.target_value,
            "min_value": template_line.min_value,
            "max_value": template_line.max_value,
            "tolerance": template_line.tolerance,
            "expected_boolean": template_line.expected_boolean,
            "allowed_values": template_line.allowed_values,
            "is_mandatory": template_line.is_mandatory,
            "is_blocking": template_line.is_blocking,
            "instruction": template_line.instruction,
        }

    def action_load_template(self):
        for check in self:
            if not check.template_id:
                raise UserError(self.env._("Select a quality template first."))
            check.line_ids.unlink()
            check.write({
                "line_ids": [
                    (0, 0, check._prepare_line_values(line))
                    for line in check.template_id.line_ids
                ]
            })
        return True

    def action_validate(self):
        for check in self:
            if not check.line_ids:
                raise UserError(self.env._("The quality check has no test line."))
            pending = check.line_ids.filtered(
                lambda line: line.is_mandatory and not line.is_answered
            )
            if pending:
                raise UserError(
                    self.env._(
                        "Answer every mandatory test first: %s",
                        ", ".join(pending.mapped("name")),
                    )
                )
            failed_blocking = check.line_ids.filtered(
                lambda line: line.result == "fail" and line.is_blocking
            )
            failed_soft = check.line_ids.filtered(
                lambda line: line.result == "fail" and not line.is_blocking
            )
            if failed_blocking:
                check.result = "fail"
                check.release_decision = "reject"
            elif failed_soft:
                check.result = "rework"
                check.release_decision = "hold"
            else:
                check.result = "pass"
                check.release_decision = "release"
            check.state = "done"
            check.inspection_date = fields.Datetime.now()
            if check.result in ("fail", "rework"):
                check._create_issue()
        return True

    def _create_issue(self):
        self.ensure_one()
        failed = self.line_ids.filtered(lambda line: line.result == "fail")
        self.env["dw.quality.issue"].create({
            "check_id": self.id,
            "opening_id": self.opening_id.id,
            "production_id": self.production_id.id,
            "project_id": self.project_id.id,
            "company_id": self.company_id.id,
            "name": self.env._("Failure on %s", self.display_name),
            "description": "\n".join(
                "%s: %s" % (line.name, line.value_display) for line in failed
            ),
            "severity": "major" if self.result == "fail" else "minor",
        })

    def action_reset(self):
        self.write({"state": "todo", "result": "pending", "release_decision": "hold"})
        return True

    def unlink(self):
        if any(check.state == "done" for check in self):
            raise UserError(self.env._("Validated quality checks cannot be deleted."))
        return super().unlink()


class DwQualityCheckLine(models.Model):
    _name = "dw.quality.check.line"
    _description = "Quality Check Test"
    _order = "sequence, id"

    check_id = fields.Many2one(
        "dw.quality.check", required=True, ondelete="cascade", index=True
    )
    template_line_id = fields.Many2one("dw.quality.template.line", ondelete="set null")
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True, translate=True)
    measure_type = fields.Selection(MEASURE_SELECTION, default="numeric", required=True)
    uom_label = fields.Char(string="Unit", translate=True)
    target_value = fields.Float(string="Target Value", digits=(16, 4))
    min_value = fields.Float(string="Minimum Value", digits=(16, 4))
    max_value = fields.Float(string="Maximum Value", digits=(16, 4))
    tolerance = fields.Float(string="Tolerance", digits=(16, 4))
    expected_boolean = fields.Boolean(string="Expected Answer", default=True)
    allowed_values = fields.Char(string="Allowed Choices")
    is_mandatory = fields.Boolean(string="Mandatory", default=True)
    is_blocking = fields.Boolean(string="Blocking", default=True)
    instruction = fields.Text(translate=True)

    measured_value = fields.Float(string="Measured Value", digits=(16, 4))
    boolean_value = fields.Selection(
        [("yes", "Yes"), ("no", "No")], string="Answer"
    )
    text_value = fields.Char(string="Text Answer")
    is_answered = fields.Boolean(string="Answered", compute="_compute_result", store=True)
    deviation = fields.Float(string="Deviation", compute="_compute_result", store=True, digits=(16, 4))
    value_display = fields.Char(string="Recorded Value", compute="_compute_result", store=True)
    result = fields.Selection(
        [("pending", "Pending"), ("pass", "Passed"), ("fail", "Failed")],
        compute="_compute_result",
        store=True,
        default="pending",
    )
    note = fields.Char(translate=True)

    @api.depends("measure_type", "measured_value", "boolean_value", "text_value",
                 "target_value", "min_value", "max_value", "tolerance",
                 "expected_boolean", "allowed_values")
    def _compute_result(self):
        for line in self:
            answered = False
            result = "pending"
            deviation = 0.0
            display = ""
            if line.measure_type == "numeric":
                answered = bool(line.measured_value) or line.text_value == "0"
                answered = answered or line.measured_value != 0.0
                display = "%s %s" % (line.measured_value, line.uom_label or "")
                low, high = line._effective_range()
                deviation = line.measured_value - line.target_value
                if answered:
                    if low is None and high is None:
                        result = "pass"
                    else:
                        ok = True
                        if low is not None and low and line.measured_value < low:
                            ok = False
                        if high is not None and high and line.measured_value > high:
                            ok = False
                        result = "pass" if ok else "fail"
            elif line.measure_type == "boolean":
                answered = bool(line.boolean_value)
                display = dict(line._fields["boolean_value"].selection).get(
                    line.boolean_value, ""
                )
                if answered:
                    given = line.boolean_value == "yes"
                    result = "pass" if given == line.expected_boolean else "fail"
            elif line.measure_type == "selection":
                answered = bool(line.text_value)
                display = line.text_value or ""
                if answered:
                    allowed = [
                        value.strip().lower()
                        for value in (line.allowed_values or "").split(",")
                        if value.strip()
                    ]
                    result = "pass" if (not allowed or (line.text_value or "").strip().lower() in allowed) else "fail"
            else:
                answered = bool(line.text_value)
                display = line.text_value or ""
                if answered:
                    result = "pass"
            line.is_answered = answered
            line.result = result
            line.deviation = deviation
            line.value_display = display

    def _effective_range(self):
        self.ensure_one()
        if self.min_value or self.max_value:
            return self.min_value, self.max_value
        if self.tolerance:
            return self.target_value - self.tolerance, self.target_value + self.tolerance
        return None, None


class DwQualityIssue(models.Model):
    _name = "dw.quality.issue"
    _description = "Quality Issue"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(required=True, translate=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    check_id = fields.Many2one("dw.quality.check", string="Quality Check", ondelete="cascade")
    opening_id = fields.Many2one("dw.opening", string="Manufacturing Item", index=True)
    production_id = fields.Many2one("mrp.production", string="Manufacturing Order", index=True)
    project_id = fields.Many2one("project.project", string="Project", index="btree_not_null")
    description = fields.Text(translate=True)
    severity = fields.Selection(
        [("minor", "Minor"), ("major", "Major"), ("critical", "Critical")],
        default="minor",
        required=True,
        tracking=True,
    )
    state = fields.Selection(
        [
            ("new", "New"),
            ("analysis", "Under Analysis"),
            ("action", "Corrective Action"),
            ("done", "Closed"),
            ("cancel", "Cancelled"),
        ],
        default="new",
        required=True,
        tracking=True,
    )
    root_cause = fields.Text(translate=True)
    corrective_action = fields.Text(translate=True)
    responsible_id = fields.Many2one("res.users", string="Responsible")
    deadline = fields.Date(string="Deadline")
    rework_required = fields.Boolean(string="Rework Required")
    rework_cost = fields.Monetary(string="Rework Cost")
    closed_date = fields.Datetime(string="Closed On", readonly=True)

    def action_close(self):
        self.write({"state": "done", "closed_date": fields.Datetime.now()})
        return True
