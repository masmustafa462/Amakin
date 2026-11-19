# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CustodyReturnWizard(models.TransientModel):
    """Quick return wizard for material custodies."""

    _name = "custody.return.wizard"
    _description = "Material Custody Return Wizard"

    custody_id = fields.Many2one(
        "employee.custody",
        string="العهدة",
        required=True,
        domain=[("custody_kind", "=", "material"),
                ("state", "in", ("issued", "partial"))],
    )
    return_date = fields.Date(
        string="تاريخ الإرجاع",
        required=True,
        default=fields.Date.context_today,
    )
    returned_quantity = fields.Float(
        string="الكمية المرتجعة",
        required=True,
        digits="Product Unit",
    )
    return_condition = fields.Selection(
        [
            ("good", "سليمة"),
            ("fair", "مستعملة"),
            ("damaged", "تالفة"),
            ("lost", "مفقودة"),
        ],
        string="الحالة",
        default="good",
        required=True,
    )
    remaining_quantity = fields.Float(
        string="المتبقي",
        related="custody_id.remaining_quantity",
    )
    notes = fields.Text(string="ملاحظات")

    @api.onchange("custody_id")
    def _onchange_custody_id(self):
        if self.custody_id:
            self.returned_quantity = self.custody_id.remaining_quantity

    def action_confirm(self):
        self.ensure_one()
        if self.returned_quantity <= 0:
            raise UserError(_("الكمية المرتجعة يجب أن تكون أكبر من صفر."))
        if self.returned_quantity > self.custody_id.remaining_quantity:
            raise UserError(_("الكمية المرتجعة تتجاوز الكمية المتبقية."))

        settlement = self.env["employee.custody.settlement"].create({
            "custody_id": self.custody_id.id,
            "settlement_kind": "return",
            "settlement_date": self.return_date,
            "returned_quantity": self.returned_quantity,
            "return_condition": self.return_condition,
            "description": self.notes or _("إرجاع عهدة عينية"),
        })
        settlement.action_post()
        return {"type": "ir.actions.act_window_close"}
