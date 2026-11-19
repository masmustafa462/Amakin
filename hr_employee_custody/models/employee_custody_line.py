# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class EmployeeCustodyLine(models.Model):
    """Optional breakdown lines for a custody master.

    Useful when a single custody contains multiple assets, or when a
    financial custody has several expected expense buckets that should
    each post to a dedicated analytic account.
    """

    _name = "employee.custody.line"
    _inherit = ["analytic.mixin"]
    _description = "Employee Custody Line | تفاصيل العهدة"
    _order = "custody_id, sequence, id"

    custody_id = fields.Many2one(
        "employee.custody",
        string="العهدة",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(string="الترتيب", default=10)

    name = fields.Char(string="البيان", required=True)
    product_id = fields.Many2one("product.product", string="المنتج")
    asset_description = fields.Char(string="الوصف")
    serial_number = fields.Char(string="الرقم التسلسلي")

    quantity = fields.Float(string="الكمية", default=1.0, digits="Product Unit")
    uom_id = fields.Many2one(
        "uom.uom",
        string="وحدة القياس",
        related="product_id.uom_id",
        readonly=False,
    )
    unit_price = fields.Monetary(string="سعر الوحدة", currency_field="currency_id")
    subtotal = fields.Monetary(
        string="الإجمالي",
        compute="_compute_subtotal",
        store=True,
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="custody_id.currency_id",
        store=True,
    )
    # analytic_distribution is provided by the analytic.mixin inherited above.
    notes = fields.Char(string="ملاحظات")

    company_id = fields.Many2one(
        "res.company",
        related="custody_id.company_id",
        store=True,
        index=True,
    )

    @api.depends("quantity", "unit_price")
    def _compute_subtotal(self):
        for rec in self:
            rec.subtotal = (rec.quantity or 0.0) * (rec.unit_price or 0.0)

    @api.constrains("quantity")
    def _check_quantity(self):
        for rec in self:
            if rec.quantity <= 0:
                raise ValidationError(_("كمية السطر يجب أن تكون أكبر من صفر."))

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.name = self.product_id.display_name
            self.asset_description = self.product_id.display_name
            self.unit_price = self.product_id.standard_price
