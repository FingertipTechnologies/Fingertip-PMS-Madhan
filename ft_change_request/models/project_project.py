from odoo import fields, models


class ProjectProject(models.Model):
    _inherit = "project.project"

    change_request_ids = fields.One2many(
        "project.change.request", "project_id", string="Change Requests"
    )
    change_request_attachment_ids = fields.Many2many(
        "ir.attachment",
        "project_change_request_attachment_rel",
        "project_id",
        "attachment_id",
        string="Change Request Attachments",
    )
