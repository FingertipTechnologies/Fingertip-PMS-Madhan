from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

# Minimum number of characters required in a task title.
TASK_TITLE_MIN_LEN = 20


class ProjectTask(models.Model):
    _inherit = 'project.task'

    estimated = fields.Float(string='Estimated')
    actual = fields.Float(string='Actual')
    module_id = fields.Many2one('cus.module',string="Module",required=True)
    wc_id = fields.Char(string='Wc Id')
    task_type = fields.Selection([
        ('user_story', 'User Story'),
        ('internal_call', 'Internal Call'),
        ('external_call', 'External Call'),
    ], string='Task Type', default='user_story', required=True)

    @api.constrains('name')
    def _check_task_title_length(self):
        # #2 - Task title must be at least TASK_TITLE_MIN_LEN characters.
        for task in self:
            if task.name and len(task.name.strip()) < TASK_TITLE_MIN_LEN:
                raise ValidationError(_(
                    "Task title must be at least %s characters long."
                ) % TASK_TITLE_MIN_LEN)
