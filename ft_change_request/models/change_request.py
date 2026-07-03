from odoo import api, fields, models


class ProjectChangeRequest(models.Model):
    _name = "project.change.request"
    _description = "Project Change Request"
    _order = "date desc, id desc"

    name = fields.Char(
        string="Request Number",
        required=True,
        copy=False,
        readonly=True,
        default="New",
        help="Auto-generated on creation.",
    )
    project_id = fields.Many2one(
        "project.project",
        string="Project",
        required=True,
        ondelete="cascade",
        index=True,
    )
    date = fields.Date(default=fields.Date.context_today)
    status = fields.Selection(
        [
            ("submitted", "Submitted"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("implemented", "Implemented"),
        ],
        default="submitted",
        required=True,
    )
    estimated_hours = fields.Float(string="Estimated Hours")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") in (False, "New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("project.change.request")
                    or "New"
                )
        return super().create(vals_list)
