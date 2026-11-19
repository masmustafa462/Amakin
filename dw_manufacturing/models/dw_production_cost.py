# -*- coding: utf-8 -*-
"""Actual production cost ledger.

Every actual cost of a manufacturing order lands in ``dw.production.cost.line``.
The recomputation is **idempotent**: each line carries a deterministic
``source_key`` (for example ``move:1234``) protected by a unique index, so
running the engine again updates the existing row instead of adding a duplicate.

Approved lines are never silently overwritten: a change produces a
``dw.production.cost.revision`` audit row and, unless the user explicitly allows
it, the approved amount is preserved. Historical approved lines are never
deleted.
"""

from odoo import api, fields, models
from odoo.exceptions import UserError

COST_TYPES = [
    ("material", "Raw Material"),
    ("scrap", "Non Recoverable Scrap"),
    ("labor", "Labour"),
    ("machine", "Machine"),
    ("outsourcing", "Outsourcing"),
    ("contractor", "Contractor"),
    ("transport", "Transport"),
    ("installation", "Installation"),
    ("direct", "Direct Expense"),
    ("overhead", "Indirect Expense / Overhead"),
    ("rework", "Rework"),
    ("adjustment", "Cost Adjustment"),
]


class DwProductionCostLine(models.Model):
    _name = "dw.production.cost.line"
    _description = "Actual Production Cost Line"
    _order = "date desc, id desc"

    name = fields.Char(string="Label", compute="_compute_name", store=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    currency_id = fields.Many2one(
        "res.currency", required=True,
        default=lambda self: self.env.company.currency_id,
    )
    date = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    cost_type = fields.Selection(COST_TYPES, required=True, default="material", index=True)
    product_id = fields.Many2one("product.product", string="Product", index="btree_not_null")
    description = fields.Char(translate=True)
    quantity = fields.Float(string="Quantity", digits="Product Unit")
    uom_id = fields.Many2one("uom.uom", string="UoM")
    unit_price = fields.Monetary(string="Unit Price")
    amount = fields.Monetary(string="Value", required=True, default=0.0)
    weight_kg = fields.Float(string="Weight (kg)", digits=(16, 3))

    opening_id = fields.Many2one(
        "dw.opening", string="Manufacturing Item", index=True, ondelete="set null"
    )
    production_id = fields.Many2one(
        "mrp.production", string="Manufacturing Order", index=True, ondelete="set null"
    )
    workorder_id = fields.Many2one("mrp.workorder", string="Work Order", index="btree_not_null")
    sale_order_id = fields.Many2one("sale.order", string="Sales Order", index="btree_not_null")
    project_id = fields.Many2one("project.project", string="Project", index="btree_not_null")
    family_id = fields.Many2one(
        "dw.product.family", string="Product Family", index="btree_not_null"
    )
    partner_id = fields.Many2one("res.partner", string="Customer", index="btree_not_null")

    stock_move_id = fields.Many2one("stock.move", string="Stock Move", index="btree_not_null")
    product_value_id = fields.Many2one(
        "product.value", string="Valuation Correction", index="btree_not_null",
        help="Odoo 19 stores inventory valuation on the stock move; manual corrections "
             "are recorded as product.value entries.",
    )
    account_move_id = fields.Many2one("account.move", string="Journal Entry", index="btree_not_null")
    account_move_line_id = fields.Many2one("account.move.line", string="Journal Item")
    analytic_account_id = fields.Many2one("account.analytic.account", string="Analytic Account")

    is_automatic = fields.Boolean(
        string="Automatic", default=False, index=True,
        help="Automatic lines are produced by the costing engine and refreshed on every run.",
    )
    source_key = fields.Char(
        index=True, copy=False,
        help="Deterministic key used to make the costing engine repeatable.",
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("approved", "Approved"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        required=True,
        index=True,
    )
    approved_by = fields.Many2one("res.users", string="Approved By", readonly=True)
    approval_date = fields.Datetime(string="Approval Date", readonly=True)
    revision_ids = fields.One2many(
        "dw.production.cost.revision", "cost_line_id", string="Revisions"
    )
    note = fields.Text(translate=True)

    _automatic_source_uniq = models.UniqueIndex(
        "(company_id, source_key) WHERE source_key IS NOT NULL AND is_automatic IS TRUE"
    )

    @api.depends("cost_type", "product_id", "description")
    def _compute_name(self):
        types = dict(COST_TYPES)
        for line in self:
            label = line.description or line.product_id.display_name or ""
            line.name = "%s - %s" % (types.get(line.cost_type, ""), label) if label \
                else types.get(line.cost_type, "")

    def action_confirm(self):
        self.filtered(lambda line: line.state == "draft").write({"state": "confirmed"})
        return True

    def action_approve(self):
        self.write({
            "state": "approved",
            "approved_by": self.env.user.id,
            "approval_date": fields.Datetime.now(),
        })
        return True

    def action_reset_to_draft(self):
        for line in self:
            if line.state == "approved":
                self.env["dw.production.cost.revision"].create({
                    "cost_line_id": line.id,
                    "company_id": line.company_id.id,
                    "old_amount": line.amount,
                    "new_amount": line.amount,
                    "reason": self.env._("Approved cost line reopened."),
                })
        self.write({"state": "draft", "approved_by": False, "approval_date": False})
        return True

    def unlink(self):
        protected = self.filtered(lambda line: line.state == "approved")
        if protected and not self.env.context.get("dw_force_unlink"):
            raise UserError(
                self.env._("Approved cost lines are part of the audit trail and cannot be deleted.")
            )
        return super().unlink()

    def _record_revision(self, new_amount, reason):
        self.ensure_one()
        if self.currency_id.compare_amounts(self.amount, new_amount) == 0:
            return False
        self.env["dw.production.cost.revision"].create({
            "cost_line_id": self.id,
            "company_id": self.company_id.id,
            "old_amount": self.amount,
            "new_amount": new_amount,
            "reason": reason,
        })
        return True


class DwProductionCostRevision(models.Model):
    _name = "dw.production.cost.revision"
    _description = "Cost Line Revision Log"
    _order = "id desc"

    cost_line_id = fields.Many2one(
        "dw.production.cost.line", required=True, ondelete="cascade", index=True
    )
    company_id = fields.Many2one("res.company", required=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    date = fields.Datetime(string="Date", default=fields.Datetime.now, readonly=True)
    user_id = fields.Many2one(
        "res.users", string="User", default=lambda self: self.env.user, readonly=True
    )
    old_amount = fields.Monetary(string="Previous Value", readonly=True)
    new_amount = fields.Monetary(string="New Value", readonly=True)
    difference = fields.Monetary(string="Difference", compute="_compute_difference", store=True)
    reason = fields.Char(string="Reason", readonly=True)

    @api.depends("old_amount", "new_amount")
    def _compute_difference(self):
        for revision in self:
            revision.difference = revision.new_amount - revision.old_amount

    def unlink(self):
        raise UserError(self.env._("The cost revision log cannot be deleted."))


class DwProjectCostEntry(models.Model):
    """Site expenses, transport, installation and contractor invoices."""

    _name = "dw.project.cost.entry"
    _description = "Project Cost Entry"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char(required=True, copy=False, default=lambda self: self.env._("New"))
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    currency_id = fields.Many2one(
        "res.currency", required=True,
        default=lambda self: self.env.company.currency_id,
    )
    date = fields.Date(required=True, default=fields.Date.context_today, index=True)
    project_id = fields.Many2one("project.project", string="Project", index=True)
    sale_order_id = fields.Many2one("sale.order", string="Sales Order", index="btree_not_null")
    production_id = fields.Many2one(
        "mrp.production", string="Manufacturing Order", index="btree_not_null"
    )
    opening_id = fields.Many2one("dw.opening", string="Manufacturing Item", index="btree_not_null")
    cost_type = fields.Selection(
        [
            ("transport", "Transport"),
            ("installation", "Installation"),
            ("contractor", "Contractor"),
            ("site", "Site Expense"),
            ("rental", "Rental"),
            ("outsourcing", "External Service"),
            ("direct", "Direct Expense"),
            ("other", "Other Expense"),
        ],
        required=True,
        default="other",
        index=True,
    )
    partner_id = fields.Many2one("res.partner", string="Vendor")
    product_id = fields.Many2one("product.product", string="Product / Service")
    quantity = fields.Float(string="Quantity", default=1.0, digits="Product Unit")
    uom_id = fields.Many2one("uom.uom", string="UoM")
    unit_price = fields.Monetary(string="Unit Price")
    amount = fields.Monetary(string="Amount", compute="_compute_amount", store=True, readonly=False)
    reference = fields.Char(string="Reference Document")
    analytic_account_id = fields.Many2one("account.analytic.account", string="Analytic Account")
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "dw_project_cost_attachment_rel",
        "entry_id",
        "attachment_id",
        string="Attachments",
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("approved", "Approved"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )
    approved_by = fields.Many2one("res.users", string="Approved By", readonly=True)
    note = fields.Text(translate=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", self.env._("New")) == self.env._("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "dw.project.cost.entry"
                ) or self.env._("New")
        return super().create(vals_list)

    @api.depends("quantity", "unit_price")
    def _compute_amount(self):
        for entry in self:
            entry.amount = entry.quantity * entry.unit_price

    @api.onchange("production_id")
    def _onchange_production_id(self):
        if self.production_id:
            self.opening_id = self.production_id.dw_opening_id
            self.project_id = self.production_id.dw_project_id
            self.sale_order_id = self.production_id.dw_sale_order_id

    def action_submit(self):
        self.filtered(lambda entry: entry.state == "draft").write({"state": "submitted"})
        return True

    def action_approve(self):
        self.write({"state": "approved", "approved_by": self.env.user.id})
        productions = self.mapped("production_id")
        if productions:
            productions._dw_recompute_actual_cost()
        return True

    def action_cancel(self):
        self.write({"state": "cancel"})
        productions = self.mapped("production_id")
        if productions:
            productions._dw_recompute_actual_cost()
        return True
