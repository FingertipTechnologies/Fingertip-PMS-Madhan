from odoo import models, fields, api


class ProjectProject(models.Model):
    _inherit = 'project.project'

    ft_has_exceeded_tasks = fields.Boolean(
        string='Has Tasks Exceeding Time Limit',
        compute='_compute_ft_has_exceeded_tasks',
        store=True,
        help='True when at least one task in this project exceeds the global time limit.',
    )
    ft_dev_hours = fields.Float(
        string='Dev Hours',
        compute='_compute_ft_department_hours',
        store=True,
        readonly=True,
        help='Total hours logged on this project by Development-department employees.',
    )
    ft_qa_hours = fields.Float(
        string='QA Hours',
        compute='_compute_ft_department_hours',
        store=True,
        readonly=True,
        help='Total hours logged on this project by QA / Testing-department employees.',
    )
    ft_pm_hours = fields.Float(
        string='PM Hours',
        compute='_compute_ft_department_hours',
        store=True,
        readonly=True,
        help='Total hours logged on this project by Project Management-department employees.',
    )

    @api.depends('task_ids.ft_hours_exceeded')
    def _compute_ft_has_exceeded_tasks(self):
        for project in self:
            project.ft_has_exceeded_tasks = any(project.task_ids.mapped('ft_hours_exceeded'))

    @api.depends('timesheet_ids.unit_amount', 'timesheet_ids.department_id')
    def _compute_ft_department_hours(self):
        # Aggregate the project's timesheets into Dev / QA / PM buckets using the
        # same department classification as the task form. Unlike tasks, the
        # per-bucket time limit is NOT applied at project level.
        ProjectTask = self.env['project.task']
        for project in self:
            dev = qa = pm = 0.0
            for line in project.timesheet_ids:
                bucket = ProjectTask._ft_department_bucket(line.department_id)
                if bucket == 'dev':
                    dev += line.unit_amount
                elif bucket == 'qa':
                    qa += line.unit_amount
                elif bucket == 'pm':
                    pm += line.unit_amount
            project.ft_dev_hours = dev
            project.ft_qa_hours = qa
            project.ft_pm_hours = pm
