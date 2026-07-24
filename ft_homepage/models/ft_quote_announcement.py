# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class FtQuoteAnnouncement(models.Model):
    _name = "ft.quote.announcement"
    _description = "Quote of the Day / Announcement"
    _order = "sequence, date_from desc, id desc"
    _rec_name = "title"

    title = fields.Char(
        string="Title",
        required=True,
        help="Internal label, e.g. 'Quote of the Day - 20 Jul' or "
        "'Org Announcement - Holiday List'.",
    )
    sequence = fields.Integer(default=10)
    # Entries start INACTIVE: anyone may add one, but it only appears on the
    # Homepage once HR / an Admin activates it (see create/write below).
    active = fields.Boolean(default=False)

    content_type = fields.Selection(
        [
            ("text", "Text"),
            ("image", "Image"),
            ("video", "Video"),
        ],
        string="Content Type",
        required=True,
        default="text",
    )

    # Text content — rendered with decorative quotation-mark styling.
    text_content = fields.Text(string="Quote / Announcement Text")

    # Image content
    image = fields.Image(string="Image", max_width=1920, max_height=1080)

    # Video content — either an uploaded file or an external URL
    # (e.g. YouTube / Vimeo / an internal .mp4 link).
    video_url = fields.Char(
        string="Video URL",
        help="Link to a video (YouTube, Vimeo, or a direct .mp4 URL).",
    )
    video_file = fields.Binary(
        string="Upload Video",
        attachment=True,
        help="Upload a video file (.mp4/.webm) directly instead of "
        "providing a URL. If both are set, the uploaded file is used.",
    )
    video_filename = fields.Char(string="Video Filename")

    contributor_id = fields.Many2one(
        "res.users",
        string="Contributed By",
        help="Shown alongside the quote/announcement on the Homepage.",
    )
    contributor_name = fields.Char(
        string="Contributor Name (override)",
        help="Use this to show a name that isn't an Odoo user "
        "(e.g. a client or a founder). Overrides 'Contributed By' if set.",
    )

    date_from = fields.Date(string="Show From", default=fields.Date.context_today)
    date_to = fields.Date(string="Show Until")

    kind = fields.Selection(
        [
            ("quote", "Quote of the Day"),
            ("announcement", "Announcement"),
            ("update", "Org-wide Update"),
        ],
        default="quote",
        required=True,
    )

    @api.constrains("content_type", "text_content", "image", "video_url", "video_file")
    def _check_content_matches_type(self):
        for rec in self:
            if rec.content_type == "text" and not rec.text_content:
                raise ValidationError("Please add the quote/announcement text.")
            if rec.content_type == "image" and not rec.image:
                raise ValidationError("Please upload an image.")
            if rec.content_type == "video" and not (rec.video_url or rec.video_file):
                raise ValidationError(
                    "Please upload a video file or provide a video URL."
                )

    def _ft_user_can_activate(self):
        """Only HR users, Admins (and system/sudo calls) may publish
        (activate/deactivate) a quote or announcement."""
        return (
            self.env.su
            or self.env.user.has_group("hr.group_hr_user")
            or self.env.user.has_group("base.group_system")
        )

    @api.model_create_multi
    def create(self, vals_list):
        # Anyone can add an entry, but non-HR/Admin users cannot create it
        # already-active — it must be activated by HR/Admin afterwards.
        if not self._ft_user_can_activate():
            for vals in vals_list:
                vals["active"] = False
        return super().create(vals_list)

    def write(self, vals):
        if "active" in vals and not self._ft_user_can_activate():
            raise AccessError(
                _(
                    "Only HR or an Administrator can activate or deactivate a "
                    "quote / announcement."
                )
            )
        return super().write(vals)

    @api.model
    def get_homepage_content(self):
        """Return ALL active quotes/announcements to show on the Homepage
        right now (respecting the optional Show From / Show Until window),
        ordered by priority. E.g. a text Quote of the Day AND a video
        announcement that are both active are BOTH returned and displayed.
        """
        # sudo(): the homepage widget must work for EVERY logged-in user,
        # regardless of their access rights on this backend model.
        records = self.sudo()
        today = fields.Date.context_today(self)
        domain = [
            "|",
            ("date_from", "=", False),
            ("date_from", "<=", today),
        ]
        domain += [
            "|",
            ("date_to", "=", False),
            ("date_to", ">=", today),
        ]
        items = []
        for record in records.search(domain):
            contributor = record.contributor_name or record.contributor_id.name or ""
            items.append({
                "id": record.id,
                "title": record.title,
                "kind": record.kind,
                "content_type": record.content_type,
                "text_content": record.text_content,
                # Inline base64 data URI instead of a /web/image URL, so
                # the image displays for every user without needing read
                # access to the model at the HTTP image route.
                "image_url": (
                    "data:image/png;base64,%s" % record.image.decode()
                    if record.content_type == "image" and record.image
                    else False
                ),
                # Uploaded video file wins over the URL; it is streamed
                # through our own sudo'd controller so every user can
                # play it.
                "video_src": (
                    "/ft_homepage/video/%s" % record.id
                    if record.content_type == "video" and record.video_file
                    else False
                ),
                "video_url": (
                    record.video_url if record.content_type == "video" else False
                ),
                "contributor": contributor,
            })
        return items
