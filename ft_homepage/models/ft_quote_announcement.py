# -*- coding: utf-8 -*-
import re
from urllib.parse import quote, urlparse

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

# Matches the src="..." of a pasted <iframe> embed snippet (e.g. LinkedIn's
# own "Embed this post" code). Falls back to treating the whole input as a
# plain URL when no <iframe> is found.
_IFRAME_SRC_RE = re.compile(r'<iframe[^>]*\bsrc=["\']([^"\']+)["\']', re.IGNORECASE)

# Exact-match allowlist of hosts we'll render as an iframe. Exact match
# (not endswith/substring) so "linkedin.com.evil.example" can't sneak in.
_SOCIAL_EMBED_HOSTS = {
    "linkedin": {"www.linkedin.com", "linkedin.com"},
    "facebook": {"www.facebook.com", "facebook.com"},
}


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
            ("social", "Social Media Post (LinkedIn / Facebook)"),
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

    # Social media content — accepts EITHER a plain public post URL, OR the
    # full <iframe> embed code copied from the platform's own "Embed this
    # post" feature (recommended — see _ft_resolve_social_embed). Text, not
    # Char: a pasted embed snippet can be long.
    social_url = fields.Text(
        string="Post URL or Embed Code",
        help="For a reliable embed, use the platform's own \"Embed\" / "
        "\"Embed this post\" option (on the post's ••• menu) and paste the "
        "WHOLE <iframe> code here, e.g.:\n"
        '<iframe src="https://www.linkedin.com/embed/feed/update/'
        'urn:li:share:XXXXXXXXXXXX" height="600" width="504"></iframe>\n\n'
        "A plain post URL also works but is less reliable to auto-embed.",
    )

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

    def _ft_resolve_social_embed(self):
        """Turn whatever was pasted into `social_url` — a plain post URL, or
        a full <iframe> embed snippet copied from the platform's own "Embed"
        feature — into a validated iframe `src` safe to render on the
        Homepage for every user.

        Returns (src, platform) on success, e.g.
        ("https://www.linkedin.com/embed/feed/update/urn:li:share:123",
         "linkedin"), or (False, False) if nothing usable/safe was found.

        Security: the resolved src's host must be an EXACT match against
        `_SOCIAL_EMBED_HOSTS` (not endswith/substring — that would let e.g.
        "linkedin.com.evil.example" slip through) and scheme must be https.
        This is what actually gates what can render as an iframe on the
        Homepage — content_type='social' entries always go through this
        before display, however they were entered.
        """
        self.ensure_one()
        raw = (self.social_url or "").strip()
        if not raw:
            return False, False

        match = _IFRAME_SRC_RE.search(raw)
        src = match.group(1) if match else raw

        parsed = urlparse(src)
        if parsed.scheme != "https":
            return False, False
        host = parsed.netloc.lower()

        if host in _SOCIAL_EMBED_HOSTS["linkedin"]:
            return src, "linkedin"

        if host in _SOCIAL_EMBED_HOSTS["facebook"]:
            # Facebook's Post Plugin needs the ORIGINAL post URL wrapped in
            # a plugins/post.php iframe; if the user already pasted that
            # plugin URL directly (host is still facebook.com), use it as-is.
            if "/plugins/post.php" in parsed.path:
                return src, "facebook"
            return (
                "https://www.facebook.com/plugins/post.php?href=%s&show_text=true&width=500"
                % quote(src, safe=""),
                "facebook",
            )

        return False, False

    @api.constrains(
        "content_type", "text_content", "image", "video_url", "video_file",
        "social_url",
    )
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
            if rec.content_type == "social":
                if not rec.social_url:
                    raise ValidationError(
                        "Please paste a LinkedIn or Facebook post URL or embed code."
                    )
                src, _platform = rec._ft_resolve_social_embed()
                if not src:
                    raise ValidationError(
                        "That doesn't look like a public LinkedIn or Facebook "
                        "link/embed code. Use the post's ••• menu → \"Embed\" "
                        "/ \"Embed this post\" and paste the whole <iframe> "
                        "code, or a plain https://linkedin.com or "
                        "https://facebook.com post link."
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
            social_src, social_platform = (
                record._ft_resolve_social_embed()
                if record.content_type == "social"
                else (False, False)
            )
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
                "social_embed_src": social_src,
                "social_platform": social_platform,
                "contributor": contributor,
            })
        return items
