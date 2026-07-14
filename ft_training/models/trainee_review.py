from odoo import models, fields, api
from odoo.exceptions import ValidationError

# The six scored competencies, each rated 0..10.
SCORE_FIELDS = (
    'attitude',
    'communication',
    'understanding',
    'technical',
    'problem_solving',
    'self_dependency',
)


class TraineeReview(models.Model):
    _name = 'ft.trainee.review'
    _description = 'Trainee Review'
    _order = 'create_date desc'
    _rec_name = 'trainee_id'

    trainee_id = fields.Many2one(
        'hr.employee', string='Trainee', required=True, ondelete='restrict',
    )
    description = fields.Text(
        string='Description',
        help='Overall review notes for the trainee.',
    )
    attitude = fields.Integer(string='Attitude', help='Rated 0 to 10.')
    communication = fields.Integer(string='Communication', help='Rated 0 to 10.')
    understanding = fields.Integer(string='Understanding', help='Rated 0 to 10.')
    technical = fields.Integer(string='Technical', help='Rated 0 to 10.')
    problem_solving = fields.Integer(string='Problem Solving', help='Rated 0 to 10.')
    self_dependency = fields.Integer(string='Self Dependency', help='Rated 0 to 10.')

    @api.constrains(*SCORE_FIELDS)
    def _check_scores(self):
        labels = {
            fname: self._fields[fname].string for fname in SCORE_FIELDS
        }
        for rec in self:
            for fname in SCORE_FIELDS:
                value = rec[fname]
                if value < 0 or value > 10:
                    raise ValidationError(
                        f"{labels[fname]} must be between 0 and 10."
                    )
