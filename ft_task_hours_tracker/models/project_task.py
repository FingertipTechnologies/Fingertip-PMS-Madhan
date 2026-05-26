from odoo import models, fields, api


class ProjectTask(models.Model):
    _inherit = 'project.task'

    ft_total_hours_taken = fields.Float(
        string='Total Hours Taken',
        compute='_compute_ft_total_hours_taken',
        store=True,
        readonly=True,
        help='Mirrors the standard Hours Spent (effective_hours) for this task.',
    )
    ft_hours_exceeded = fields.Boolean(
        string='Exceeds Time Limit',
        compute='_compute_ft_total_hours_taken',
        store=True,
        help='True when Total Hours Taken exceeds the global task time limit.',
    )
    ft_allow_billable = fields.Boolean(
        related='project_id.allow_billable',
        string='Is Billable Project',
        store=False,
    )

    @api.depends('effective_hours')
    def _compute_ft_total_hours_taken(self):
        time_limit = float(
            self.env['ir.config_parameter'].sudo().get_param(
                'ft_task_hours_tracker.default_time_limit', default=0.0
            )
        )
        for task in self:
            total = task.effective_hours
            task.ft_total_hours_taken = total
            task.ft_hours_exceeded = time_limit > 0 and total > time_limit
