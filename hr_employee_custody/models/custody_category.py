# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class EmployeeCustodyCategory(models.Model):
    """Logical grouping for custody types (e.g. IT equipment, Vehicles, Petty Cash)."""

    _name = "employee.custody.category"
    _description = "Employee Custody Category | تصنيف العهد"
    _order = "sequence, name"

    name = fields.Char(
        string="التصنيف",
        required=True,
        translate=True,
        index=True,
    )
    code = fields.Char(string="الرمز", index=True)
    sequence = fields.Integer(string="الترتيب", default=10)
    description = fields.Text(string="الوصف", translate=True)
    active = fields.Boolean(string="نشط", default=True)
    color = fields.Integer(string="اللون")
    parent_id = fields.Many2one(
        "employee.custody.category",
        string="التصنيف الأب",
        ondelete="restrict",
        index=True,
    )
    child_ids = fields.One2many(
        "employee.custody.category",
        "parent_id",
        string="التصنيفات الفرعية",
    )
    type_ids = fields.One2many(
        "employee.custody.type",
        "category_id",
        string="أنواع العهد",
    )
    type_count = fields.Integer(
        string="عدد الأنواع",
        compute="_compute_type_count",
    )
    company_id = fields.Many2one(
        "res.company",
        string="الشركة",
        default=lambda self: self.env.company,
        index=True,
    )

    # Odoo 19 declares SQL objects as model attributes; the legacy
    # ``_sql_constraints`` list is no longer read by the ORM.
    _code_company_uniq = models.Constraint(
        "unique(code, company_id)",
        "رمز التصنيف يجب أن يكون فريداً داخل الشركة.",
    )

    @api.depends("type_ids")
    def _compute_type_count(self):
        data = self.env["employee.custody.type"]._read_group(
            domain=[("category_id", "in", self.ids)],
            groupby=["category_id"],
            aggregates=["__count"],
        )
        mapping = {cat.id: count for cat, count in data}
        for rec in self:
            rec.type_count = mapping.get(rec.id, 0)

    @api.constrains("parent_id")
    def _check_parent_recursion(self):
        # Odoo 18 deprecated _check_recursion in favour of _has_cycle.
        if self._has_cycle():
            raise ValidationError(_("لا يمكن إنشاء تصنيفات متداخلة بشكل دائري."))

    # ``name_get`` was removed in Odoo 19: display names are produced by the
    # ``display_name`` computed field. Same output as the previous name_get.
    @api.depends("name", "code", "parent_id.name")
    def _compute_display_name(self):
        for rec in self:
            name = rec.name
            if rec.parent_id:
                name = f"{rec.parent_id.name} / {name}"
            if rec.code:
                name = f"[{rec.code}] {name}"
            rec.display_name = name
