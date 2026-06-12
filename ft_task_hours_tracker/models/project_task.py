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
    ft_dev_hours = fields.Float(
        string='Dev Hours',
        compute='_compute_ft_department_hours',
        store=True,
        readonly=True,
        help='Hours logged on this task by Development-department employees.',
    )
    ft_qa_hours = fields.Float(
        string='QA Hours',
        compute='_compute_ft_department_hours',
        store=True,
        readonly=True,
        help='Hours logged on this task by QA / Testing-department employees.',
    )
    ft_pm_hours = fields.Float(
        string='PM Hours',
        compute='_compute_ft_department_hours',
        store=True,
        readonly=True,
        help='Hours logged on this task by Project Management-department employees.',
    )
    ft_dev_hours_exceeded = fields.Boolean(
        string='Dev Hours Exceeded',
        compute='_compute_ft_department_hours',
        store=True,
        help='True when Dev Hours exceeds the task time limit.',
    )
    ft_qa_hours_exceeded = fields.Boolean(
        string='QA Hours Exceeded',
        compute='_compute_ft_department_hours',
        store=True,
        help='True when QA Hours exceeds the task time limit.',
    )
    ft_pm_hours_exceeded = fields.Boolean(
        string='PM Hours Exceeded',
        compute='_compute_ft_department_hours',
        store=True,
        help='True when PM Hours exceeds the task time limit.',
    )

    @staticmethod
    def _ft_department_bucket(department):
        """Classify a department into 'dev', 'qa' or 'pm' by its name.
        Returns False for any other department."""
        name = (department.name or '').strip().lower()
        if 'development' in name:
            return 'dev'
        if 'testing' in name or name == 'qa':
            return 'qa'
        if 'project management' in name or name == 'pm':
            return 'pm'
        return False

    @api.depends('timesheet_ids.unit_amount', 'timesheet_ids.department_id')
    def _compute_ft_department_hours(self):
        time_limit = float(
            self.env['ir.config_parameter'].sudo().get_param(
                'ft_task_hours_tracker.default_time_limit', default=0.0
            )
        )
        for task in self:
            dev = qa = pm = 0.0
            for line in task.timesheet_ids:
                bucket = self._ft_department_bucket(line.department_id)
                if bucket == 'dev':
                    dev += line.unit_amount
                elif bucket == 'qa':
                    qa += line.unit_amount
                elif bucket == 'pm':
                    pm += line.unit_amount
            task.ft_dev_hours = dev
            task.ft_qa_hours = qa
            task.ft_pm_hours = pm
            task.ft_dev_hours_exceeded = time_limit > 0 and dev > time_limit
            task.ft_qa_hours_exceeded = time_limit > 0 and qa > time_limit
            task.ft_pm_hours_exceeded = time_limit > 0 and pm > time_limit

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
