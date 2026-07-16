"""Analysis purposes — data, not code.

Each record is one selectable "purpose" with its own editable prompt. Adding a
new analysis type is a matter of creating a record (UI or data file); no Python
change is required, satisfying the "add purposes without changing business
logic" requirement.
"""
from odoo import fields, models


class FtAiInsightsPurpose(models.Model):
    _name = "ft.ai.insights.purpose"
    _description = "AI Sales Insights Purpose"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        required=True,
        help="Stable technical key (unique). Used by integrations/automation.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    icon = fields.Char(default="fa-line-chart", help="FontAwesome class.")
    description = fields.Char(translate=True)
    prompt = fields.Text(
        required=True,
        translate=True,
        help="Purpose-specific instructions appended to the master prompt.",
    )

    _sql_constraints = [
        ("code_uniq", "unique(code)", "The purpose code must be unique."),
    ]
