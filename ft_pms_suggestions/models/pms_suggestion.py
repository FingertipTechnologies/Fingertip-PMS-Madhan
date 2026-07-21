# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import AccessError


class PmsSuggestion(models.Model):
    _name = "pms.suggestion"
    _description = "PMS Suggestion"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"
    _rec_name = "name"

    name = fields.Char(
        string="ID",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: "New",
        help="Auto-generated suggestion number.",
    )
    title = fields.Char(required=True, tracking=True)
    category_id = fields.Many2one(
        "pms.suggestion.category",
        string="Module / Area",
        required=True,
        tracking=True,
        help="Which PMS module/area this suggestion relates to.",
    )
    description = fields.Html(
        string="Description",
        sanitize_attributes=False,
        help="Rich text — you can paste images directly here. Use the "
        "chatter's paperclip icon below to attach files as well.",
    )

    state = fields.Selection(
        [
            ("new", "Suggestion"),
            ("approved", "Approved"),
            ("implemented", "Implemented"),
        ],
        default="new",
        required=True,
        tracking=True,
        copy=False,
    )

    suggested_by_id = fields.Many2one(
        "res.users",
        string="Suggested By",
        default=lambda self: self.env.user,
        readonly=True,
        tracking=True,
    )

    # Once state != 'new', the record is read-only for everyone. An Admin
    # can flip this to temporarily unlock it for editing.
    admin_unlocked = fields.Boolean(
        string="Unlocked for Editing",
        copy=False,
        help="Admins can toggle this to edit a suggestion that has already "
        "been approved/implemented.",
    )
    is_admin = fields.Boolean(
        compute="_compute_is_admin",
        help="Technical field used by the view to show/hide admin-only "
        "controls.",
    )

    @api.depends_context("uid")
    def _compute_is_admin(self):
        is_admin = self.env.user.has_group("base.group_system")
        for rec in self:
            rec.is_admin = is_admin

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "pms.suggestion"
                ) or "New"
        records = super().create(vals_list)
        records._notify_admins_new_suggestion()
        return records

    def write(self, vals):
        # Defense in depth: even if someone bypasses the view's readonly
        # attrs (e.g. via direct RPC/import), block edits to a
        # locked/approved suggestion for non-admins, unless it has been
        # explicitly unlocked.
        protected_fields = set(vals.keys()) - {"admin_unlocked", "message_follower_ids", "message_ids", "activity_ids"}
        if protected_fields and not self.env.user.has_group("base.group_system"):
            for rec in self:
                if rec.state != "new" and not rec.admin_unlocked:
                    raise AccessError(
                        "This suggestion has been Approved/Implemented and "
                        "is read-only. Ask an Admin to unlock it if it "
                        "needs changes."
                    )
        return super().write(vals)

    def _check_is_admin(self):
        if not self.env.user.has_group("base.group_system"):
            raise AccessError("Only Admins can perform this action.")

    def action_approve(self):
        self._check_is_admin()
        self.write({"state": "approved", "admin_unlocked": False})

    def action_implement(self):
        self._check_is_admin()
        self.write({"state": "implemented", "admin_unlocked": False})

    def action_reset_to_suggestion(self):
        self._check_is_admin()
        self.write({"state": "new", "admin_unlocked": False})

    def action_unlock(self):
        self._check_is_admin()
        self.admin_unlocked = True

    def action_lock(self):
        self._check_is_admin()
        self.admin_unlocked = False

    def _notify_admins_new_suggestion(self):
        """Email/notify Admin-access users and Ashitha specifically when a
        new suggestion comes in, as requested on the call."""
        admins = self.env["res.users"].sudo().search(
            [("groups_id", "=", self.env.ref("base.group_system").id)]
        )
        ashitha = self.env["res.users"].sudo().search(
            [("name", "ilike", "Ashitha")], limit=1
        )
        recipients = admins | ashitha
        partner_ids = recipients.mapped("partner_id").ids
        if not partner_ids:
            return
        for rec in self:
            rec.message_subscribe(partner_ids=partner_ids)
            rec.message_post(
                body=(
                    "<p>New PMS suggestion submitted: <b>%s</b></p>"
                    "<p>Module/Area: %s<br/>Suggested by: %s</p>"
                    % (
                        rec.title or rec.name,
                        rec.category_id.name or "-",
                        rec.suggested_by_id.name or "-",
                    )
                ),
                subject="New PMS Suggestion: %s" % (rec.title or rec.name),
                partner_ids=partner_ids,
                subtype_xmlid="mail.mt_comment",
            )
