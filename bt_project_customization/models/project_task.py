from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

# Minimum number of characters required in a task title.
TASK_TITLE_MIN_LEN = 20

# Job positions (hr.job) allowed to create tasks. Matched on the lower-cased
# job name, mirroring the classification used elsewhere in the PMS.
TASK_CREATE_JOBS = {
    'technical lead',
    'project manager',
    'project coordinator',
    'project cordinator',   # legacy typo present in source data
}


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

    @api.model_create_multi
    def create(self, vals_list):
        # Only a Technical Lead, Project Manager or Project Coordinator may
        # create tasks. Superuser and system administrators bypass the check so
        # data imports, automation and mail-to-task keep working.
        self._check_task_create_permission()
        return super().create(vals_list)

    def _check_task_create_permission(self):
        if self.env.su or self.env.user.has_group('base.group_system'):
            return
        employee = self.env.user.employee_id
        job_name = (employee.job_id.name or '').strip().lower() if employee else ''
        if job_name not in TASK_CREATE_JOBS:
            raise UserError(_(
                "You are not allowed to create tasks. Only a Technical Lead, "
                "Project Manager or Project Coordinator can create tasks."
            ))

    @api.constrains('name')
    def _check_task_title_length(self):
        # #2 - Task title must be at least TASK_TITLE_MIN_LEN characters.
        for task in self:
            if task.name and len(task.name.strip()) < TASK_TITLE_MIN_LEN:
                raise ValidationError(_(
                    "Task title must be at least %s characters long."
                ) % TASK_TITLE_MIN_LEN)
