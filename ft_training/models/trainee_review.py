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

# Review Period: Day 1 … Day 150.
#
# The keys are zero-padded on purpose. Odoo stores a Selection as varchar and
# sorts/groups on the STORED value, so plain '1','2',…,'150' would order as
# 1, 10, 100, 101, …, 2, 20 in the list view and in Group By. '001' … '150'
# sorts and groups in numeric order while the user only ever sees "Day 1".
REVIEW_PERIOD = [('%03d' % day, 'Day %d' % day) for day in range(1, 151)]


class TraineeReview(models.Model):
    _name = 'ft.trainee.review'
    _description = 'Trainee Review'
    _order = 'create_date desc'
    _rec_name = 'trainee_id'

    trainee_id = fields.Many2one(
        'hr.employee', string='Trainee', required=True, ondelete='restrict',
    )
    # Who created the review, and thereafter whoever last updated it (see
    # write() below). Indexed because it is a reporting/filtering field.
    reviewer_id = fields.Many2one(
        'res.users', string='Reviewer', ondelete='restrict', index=True,
        default=lambda self: self.env.user,
        help='User who created the review, or who last updated it.',
    )
    review_period = fields.Selection(
        REVIEW_PERIOD, string='Review Period', index=True,
        help='Review timeline for this record, from Day 1 to Day 150.',
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

    def write(self, vals):
        """Keep Reviewer pointing at whoever last touched the review.

        The field is set to the creator on create (via its default) and moves
        to the editor on every subsequent save, which is what "created or last
        updated" asks for. An explicit reviewer_id in the same write wins, so
        the field can still be corrected by hand.
        """
        if 'reviewer_id' not in vals:
            vals = dict(vals, reviewer_id=self.env.user.id)
        return super().write(vals)

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
