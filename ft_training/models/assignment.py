from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

DOMAIN_SELECTION = [
    ('salesforce', 'Salesforce'),
    ('odoo', 'Odoo'),
    ('python', 'Python'),
    ('react', 'React'),
    ('flutter', 'flutter'),
    ('react_native', 'ReactNative'),
]


class Assignment(models.Model):
    _name = 'ft.assignment'
    _description = 'Assignment'
    _order = 'deadline desc, id desc'
    _rec_name = 'domain'

    description = fields.Text(string='Description')
    deadline = fields.Date(string='Deadline')
    marks = fields.Integer(string='Marks', help='Maximum marks, rated 0 to 100.')
    domain = fields.Selection(
        DOMAIN_SELECTION, string='Domain',
    )
    phase_id = fields.Many2one('ft.phase', string='Phase', ondelete='restrict')

    @api.constrains('marks')
    def _check_marks(self):
        for rec in self:
            if rec.marks < 0 or rec.marks > 100:
                raise ValidationError(_("Marks must be between 0 and 100."))

    def name_get(self):
        result = []
        for rec in self:
            domain = dict(DOMAIN_SELECTION).get(rec.domain) or _("Assignment")
            day = fields.Date.to_string(rec.deadline) if rec.deadline else ''
            result.append((rec.id, f"{domain} ({day})" if day else domain))
        return result
