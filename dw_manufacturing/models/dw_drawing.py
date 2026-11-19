# -*- coding: utf-8 -*-
"""Light engineering drawing and revision control.

Every revision keeps its own attachment: superseding a revision never replaces
or deletes the previous file, so the revision history stays auditable.
"""

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class DwDrawing(models.Model):
    _name = "dw.drawing"
    _description = "Engineering Drawing"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "name"

    name = fields.Char(string="Drawing Number", required=True, copy=False, tracking=True)
    title = fields.Char(translate=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    family_id = fields.Many2one("dw.product.family", string="Product Family")
    project_id = fields.Many2one("project.project", string="Project", index="btree_not_null")
    partner_id = fields.Many2one("res.partner", string="Customer")
    revision_ids = fields.One2many("dw.drawing.revision", "drawing_id", string="Revisions")
    revision_count = fields.Integer(compute="_compute_current_revision", store=True)
    current_revision_id = fields.Many2one(
        "dw.drawing.revision", compute="_compute_current_revision", store=True
    )
    current_revision = fields.Char(
        related="current_revision_id.revision", store=True, string="Current Revision Code"
    )
    state = fields.Selection(
        [("draft", "Draft"), ("released", "Released"), ("obsolete", "Obsolete")],
        compute="_compute_current_revision",
        store=True,
        default="draft",
    )
    note = fields.Text(translate=True)

    _name_uniq = models.Constraint(
        "unique(name, company_id)", "The drawing number must be unique per company."
    )

    @api.depends("revision_ids.state", "revision_ids.revision_date", "revision_ids.sequence")
    def _compute_current_revision(self):
        for drawing in self:
            drawing.revision_count = len(drawing.revision_ids)
            released = drawing.revision_ids.filtered(lambda rev: rev.state == "released")
            current = released.sorted(key=lambda rev: (rev.sequence, rev.id))[-1:] \
                if released else drawing.revision_ids.sorted(key=lambda rev: (rev.sequence, rev.id))[-1:]
            drawing.current_revision_id = current
            drawing.state = current.state if current else "draft"

    def action_view_revisions(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Revisions"),
            "res_model": "dw.drawing.revision",
            "view_mode": "list,form",
            "domain": [("drawing_id", "=", self.id)],
            "context": {"default_drawing_id": self.id},
        }


class DwDrawingRevision(models.Model):
    _name = "dw.drawing.revision"
    _description = "Drawing Revision"
    _inherit = ["mail.thread"]
    _order = "drawing_id, sequence, id"

    drawing_id = fields.Many2one(
        "dw.drawing", required=True, ondelete="cascade", index=True
    )
    company_id = fields.Many2one(related="drawing_id.company_id", store=True)
    revision = fields.Char(required=True, tracking=True)
    sequence = fields.Integer(default=10)
    revision_date = fields.Date(default=fields.Date.context_today, tracking=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("review", "Under Review"),
            ("released", "Released"),
            ("superseded", "Superseded"),
            ("obsolete", "Obsolete"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )
    prepared_by = fields.Many2one("res.users", string="Prepared By", tracking=True)
    approved_by = fields.Many2one("res.users", string="Approved By", readonly=True, tracking=True)
    approval_date = fields.Datetime(readonly=True)
    change_reason = fields.Text(translate=True, tracking=True)
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "dw_drawing_revision_attachment_rel",
        "revision_id",
        "attachment_id",
        string="Files",
    )
    note = fields.Text(translate=True)

    _revision_uniq = models.Constraint(
        "unique(drawing_id, revision)", "The revision code must be unique per drawing."
    )

    @api.depends("drawing_id.name", "revision")
    def _compute_display_name(self):
        for record in self:
            record.display_name = "%s - %s" % (record.drawing_id.name or "", record.revision or "")

    def action_release(self):
        for revision in self:
            if not revision.attachment_ids:
                raise UserError(
                    self.env._("Attach the drawing file before releasing revision %s.", revision.revision)
                )
            previous = revision.drawing_id.revision_ids.filtered(
                lambda rev: rev.state == "released" and rev.id != revision.id
            )
            previous.write({"state": "superseded"})
            revision.write({
                "state": "released",
                "approved_by": self.env.user.id,
                "approval_date": fields.Datetime.now(),
            })
        return True

    def action_set_review(self):
        self.write({"state": "review"})
        return True

    def action_obsolete(self):
        self.write({"state": "obsolete"})
        return True

    def unlink(self):
        if any(revision.state in ("released", "superseded") for revision in self):
            raise UserError(
                self.env._("Released or superseded drawing revisions cannot be deleted.")
            )
        return super().unlink()

    @api.constrains("state")
    def _check_single_released(self):
        for revision in self:
            if revision.state != "released":
                continue
            others = revision.drawing_id.revision_ids.filtered(
                lambda rev: rev.state == "released" and rev.id != revision.id
            )
            if others:
                raise ValidationError(
                    self.env._("Only one revision of a drawing can be released at a time.")
                )
