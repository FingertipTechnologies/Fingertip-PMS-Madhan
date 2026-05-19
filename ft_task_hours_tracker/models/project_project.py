from odoo import models, fields, api


class ProjectProject(models.Model):
    _inherit = 'project.project'

    ft_has_exceeded_tasks = fields.Boolean(
        string='Has Tasks Exceeding Time Limit',
        compute='_compute_ft_has_exceeded_tasks',
        store=True,
        help='True when at least one task in this project exceeds the global time limit.',
    )

    @api.depends('task_ids.ft_hours_exceeded')
    def _compute_ft_has_exceeded_tasks(self):
        for project in self:
            project.ft_has_exceeded_tasks = any(project.task_ids.mapped('ft_hours_exceeded'))
