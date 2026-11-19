# -*- coding: utf-8 -*-
"""Scrap classification and reusable off-cut (remnant) stock.

Stock is always moved with the standard ``stock.move`` machinery; the module
never writes into ``stock.quant``.
"""

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class DwScrapReason(models.Model):
    _name = "dw.scrap.reason"
    _description = "Scrap Reason"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    scrap_type = fields.Selection(
        [
            ("cutting_loss", "Cutting Loss"),
            ("offcut", "Reusable Off-cut"),
            ("defect", "Manufacturing Defect"),
            ("material_defect", "Material Defect"),
            ("design_change", "Design Change"),
            ("handling", "Handling Damage"),
            ("rework", "Rework Loss"),
            ("other", "Other"),
        ],
        default="other",
        required=True,
    )
    is_planned = fields.Boolean(
        string="Planned Scrap",
        help="Planned scrap is expected by the estimate and does not raise an alert.",
    )
    is_reusable = fields.Boolean(string="Produces Reusable Off-cut")
    responsible_id = fields.Many2one("res.users", string="Default Responsible")
    requires_approval = fields.Boolean(default=False)
    note = fields.Text(translate=True)

    _code_uniq = models.Constraint(
        "unique(code, company_id)", "The scrap reason code must be unique per company."
    )


class StockScrap(models.Model):
    _inherit = "stock.scrap"

    dw_reason_id = fields.Many2one(
        "dw.scrap.reason", string="Fabrication Scrap Reason", index="btree_not_null"
    )
    dw_scrap_type = fields.Selection(related="dw_reason_id.scrap_type", store=True)
    dw_is_planned = fields.Boolean(
        string="Planned", compute="_compute_dw_planned", store=True, readonly=False
    )
    dw_is_reusable = fields.Boolean(
        string="Reusable", compute="_compute_dw_planned", store=True, readonly=False
    )
    dw_operation_type_id = fields.Many2one("dw.operation.type", string="Operation")
    dw_workcenter_id = fields.Many2one("mrp.workcenter", string="Work Center")
    dw_responsible_id = fields.Many2one("res.users", string="Responsible")
    dw_opening_id = fields.Many2one(
        "dw.opening", string="Manufacturing Item", index="btree_not_null"
    )
    dw_project_id = fields.Many2one("project.project", string="Project", index="btree_not_null")
    dw_value = fields.Monetary(
        string="Scrap Value", compute="_compute_dw_value", store=True,
        currency_field="dw_currency_id",
    )
    dw_currency_id = fields.Many2one(
        related="company_id.currency_id", string="Scrap Currency"
    )
    dw_weight_kg = fields.Float(
        string="Scrap Weight (kg)", compute="_compute_dw_value", store=True, digits=(16, 3)
    )
    dw_approval_note = fields.Text(string="Approval Note")
    dw_approved = fields.Boolean(string="Approved", copy=False)
    dw_approved_by = fields.Many2one(
        "res.users", string="Scrap Approved By", readonly=True, copy=False
    )
    dw_offcut_ids = fields.One2many("dw.material.offcut", "scrap_id", string="Off-cuts")

    @api.depends("dw_reason_id")
    def _compute_dw_planned(self):
        for scrap in self:
            if scrap.dw_reason_id:
                scrap.dw_is_planned = scrap.dw_reason_id.is_planned
                scrap.dw_is_reusable = scrap.dw_reason_id.is_reusable

    @api.depends("product_id", "scrap_qty", "product_uom_id", "move_ids.value",
                 "product_id.standard_price", "product_id.dw_weight_per_uom")
    def _compute_dw_value(self):
        for scrap in self:
            moves = scrap.move_ids.filtered(lambda move: move.state == "done")
            if moves:
                scrap.dw_value = sum(abs(move.value) for move in moves)
            else:
                scrap.dw_value = scrap.product_id.standard_price * scrap.scrap_qty
            scrap.dw_weight_kg = (scrap.product_id.dw_weight_per_uom or 0.0) * scrap.scrap_qty

    @api.onchange("production_id")
    def _onchange_dw_production_id(self):
        if self.production_id:
            self.dw_opening_id = self.production_id.dw_opening_id
            self.dw_project_id = self.production_id.dw_project_id

    def action_dw_approve(self):
        self.write({"dw_approved": True, "dw_approved_by": self.env.user.id})
        return True

    def action_validate(self):
        for scrap in self:
            if scrap.dw_reason_id.requires_approval and not scrap.dw_approved:
                raise UserError(
                    self.env._(
                        "Scrap reason '%s' requires an approval before validation.",
                        scrap.dw_reason_id.display_name,
                    )
                )
        result = super().action_validate()
        for scrap in self.filtered(lambda record: record.state == "done"):
            if scrap.production_id and not scrap.dw_opening_id:
                scrap.dw_opening_id = scrap.production_id.dw_opening_id
                scrap.dw_project_id = scrap.production_id.dw_project_id
            if scrap.production_id:
                scrap.production_id._dw_recompute_actual_cost()
        return result

    def action_create_offcut(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Register Off-cut"),
            "res_model": "dw.material.offcut",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_scrap_id": self.id,
                "default_product_id": self.product_id.id,
                "default_company_id": self.company_id.id,
                "default_production_id": self.production_id.id,
                "default_opening_id": self.dw_opening_id.id,
                "default_project_id": self.dw_project_id.id,
                "default_quantity": self.scrap_qty,
                "default_uom_id": self.product_uom_id.id,
            },
        }


class DwMaterialOffcut(models.Model):
    _name = "dw.material.offcut"
    _description = "Reusable Material Off-cut"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char(required=True, copy=False, default=lambda self: self.env._("New"))
    active = fields.Boolean(string="Active", default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    product_id = fields.Many2one(
        "product.product", string="Material", required=True,
        domain="[('type', '=', 'consu')]", index=True,
    )
    uom_id = fields.Many2one(
        "uom.uom", string="UoM", compute="_compute_uom_id", store=True, readonly=False
    )
    warehouse_id = fields.Many2one("stock.warehouse", string="Warehouse")
    location_id = fields.Many2one(
        "stock.location", string="Storage Location",
        domain="[('usage', '=', 'internal')]",
    )
    length_mm = fields.Float(string="Length (mm)")
    width_mm = fields.Float(string="Width (mm)")
    thickness_mm = fields.Float(string="Thickness (mm)")
    diameter_mm = fields.Float(string="Diameter (mm)")
    weight_kg = fields.Float(
        string="Weight (kg)", compute="_compute_weight", store=True, readonly=False, digits=(16, 3)
    )
    quantity = fields.Float(string="Quantity", default=1.0, required=True, digits="Product Unit")
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("available", "Available"),
            ("reserved", "Reserved"),
            ("used", "Used"),
            ("scrapped", "Scrapped"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )
    scrap_id = fields.Many2one("stock.scrap", string="Source Scrap", index="btree_not_null")
    production_id = fields.Many2one(
        "mrp.production", string="Source Manufacturing Order", index="btree_not_null"
    )
    opening_id = fields.Many2one("dw.opening", string="Source Item", index="btree_not_null")
    project_id = fields.Many2one("project.project", string="Source Project", index="btree_not_null")
    used_in_production_id = fields.Many2one(
        "mrp.production", string="Used In", index="btree_not_null"
    )
    cost_value = fields.Monetary(string="Off-cut Value")
    create_date_only = fields.Date(
        string="Created On", default=fields.Date.context_today, readonly=True
    )
    last_use_date = fields.Date(readonly=True)
    barcode = fields.Char(string="Barcode", copy=False, index="btree_not_null")
    move_ids = fields.One2many("stock.move", "dw_offcut_id", string="Stock Moves")
    note = fields.Text(translate=True)

    _barcode_uniq = models.Constraint(
        "unique(barcode)", "The off-cut barcode must be unique."
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", self.env._("New")) == self.env._("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "dw.material.offcut"
                ) or self.env._("New")
            if not vals.get("barcode"):
                vals["barcode"] = vals["name"]
        return super().create(vals_list)

    @api.depends("product_id")
    def _compute_uom_id(self):
        for offcut in self:
            if not offcut.uom_id:
                offcut.uom_id = offcut.product_id.uom_id

    @api.depends("product_id", "quantity", "product_id.dw_weight_per_uom")
    def _compute_weight(self):
        for offcut in self:
            offcut.weight_kg = (offcut.product_id.dw_weight_per_uom or 0.0) * offcut.quantity

    @api.constrains("quantity")
    def _check_quantity(self):
        for offcut in self:
            if offcut.quantity <= 0:
                raise ValidationError(self.env._("The off-cut quantity must be positive."))

    def _production_location(self):
        """Virtual production location of the company.

        Odoo 19 creates these per company instead of shipping a fixed XML id,
        so they are looked up by usage exactly like mrp does.
        """
        self.ensure_one()
        if self.production_id:
            return self.production_id.production_location_id
        return self.env["stock.location"].search(
            [("usage", "=", "production"),
             ("company_id", "in", [False, self.company_id.id])],
            limit=1,
        )

    def _default_stock_location(self):
        self.ensure_one()
        if self.location_id:
            return self.location_id
        warehouse = self.warehouse_id or self.env["stock.warehouse"].search(
            [("company_id", "=", self.company_id.id)], limit=1
        )
        return warehouse.lot_stock_id

    def action_return_to_stock(self):
        """Move the off-cut back into stock with a standard stock move."""
        for offcut in self:
            if offcut.state != "draft":
                raise UserError(self.env._("Only draft off-cuts can be returned to stock."))
            destination = offcut._default_stock_location()
            source = offcut._production_location()
            if not destination or not source:
                raise UserError(
                    self.env._("Configure a stock location and a production location first.")
                )
            move = self.env["stock.move"].create({
                "product_id": offcut.product_id.id,
                "product_uom_qty": offcut.quantity,
                "product_uom": offcut.uom_id.id,
                "location_id": source.id,
                "location_dest_id": destination.id,
                "company_id": offcut.company_id.id,
                "origin": offcut.name,
                "dw_offcut_id": offcut.id,
            })
            move._action_confirm()
            move._action_assign()
            move.picked = True
            move.quantity = offcut.quantity
            move._action_done()
            offcut.write({"state": "available", "location_id": destination.id})
        return True

    def action_reserve(self):
        self.filtered(lambda offcut: offcut.state == "available").write({"state": "reserved"})
        return True

    def action_mark_used(self):
        for offcut in self:
            if offcut.state not in ("available", "reserved"):
                raise UserError(self.env._("Only available off-cuts can be consumed."))
            offcut.write({"state": "used", "last_use_date": fields.Date.context_today(offcut)})
        return True

    def action_back_to_available(self):
        self.filtered(lambda offcut: offcut.state == "reserved").write({"state": "available"})
        return True


class StockMove(models.Model):
    _inherit = "stock.move"

    dw_offcut_id = fields.Many2one(
        "dw.material.offcut", string="Off-cut", index="btree_not_null", copy=False
    )
