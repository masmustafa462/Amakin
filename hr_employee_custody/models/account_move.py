# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    custody_id = fields.Many2one(
        "employee.custody",
        string="العهدة المرتبطة",
        index=True,
        copy=False,
        help="العهدة التي تم إنشاء هذا القيد لها.",
    )

    def button_draft(self):
        # Prevent accidental reset of moves that were posted through a settlement.
        for move in self:
            if move.custody_id and move.state == "posted":
                settlement = self.env["employee.custody.settlement"].search([
                    ("move_id", "=", move.id),
                    ("state", "=", "posted"),
                ], limit=1)
                if settlement:
                    raise UserError(_(
                        "لا يمكن إعادة القيد إلى المسودة مباشرة. "
                        "قم بإلغاء التسوية %s أولاً."
                    ) % settlement.name)
        return super().button_draft()
