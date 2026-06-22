from odoo import models, fields, api

# Map a job-position name (lower-cased, stripped) to an hours bucket.
# Any position whose name starts with "trainee" is classified as 'trainee'.
FT_JOB_BUCKET_MAP = {
    'software developer': 'dev',
    'technical lead': 'dev',
    'software tester': 'qa',
    'testing lead': 'qa',
    'project manager': 'pm',
    'project cordinator': 'pm',
    'project coordinator': 'pm',
    'business analyst': 'ba',
}
FT_BUCKETS = ('dev', 'qa', 'pm', 'ba', 'trainee')


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
    # store=False (computed live, like the project-level fields) so historical
    # tasks always reflect the employee's CURRENT job position. Stored values
    # would freeze at whatever was first computed and never refresh.
    ft_dev_hours = fields.Float(
        string='Dev Hours',
        compute='_compute_ft_job_hours',
        store=False,
        readonly=True,
        help='Hours logged on this task by Software Developer / Technical Lead employees.',
    )
    ft_qa_hours = fields.Float(
        string='QA Hours',
        compute='_compute_ft_job_hours',
        store=False,
        readonly=True,
        help='Hours logged on this task by Software Tester / Testing Lead employees.',
    )
    ft_pm_hours = fields.Float(
        string='PM Hours',
        compute='_compute_ft_job_hours',
        store=False,
        readonly=True,
        help='Hours logged on this task by Project Manager / Project Coordinator employees.',
    )
    ft_ba_hours = fields.Float(
        string='BA Hours',
        compute='_compute_ft_job_hours',
        store=False,
        readonly=True,
        help='Hours logged on this task by Business Analyst employees.',
    )
    ft_trainee_hours = fields.Float(
        string='Trainee Hours',
        compute='_compute_ft_job_hours',
        store=False,
        readonly=True,
        help='Hours logged on this task by any Trainee job position.',
    )
    ft_dev_hours_exceeded = fields.Boolean(
        string='Dev Hours Exceeded',
        compute='_compute_ft_job_hours',
        store=False,
        help='True when Dev Hours exceeds the task time limit.',
    )
    ft_qa_hours_exceeded = fields.Boolean(
        string='QA Hours Exceeded',
        compute='_compute_ft_job_hours',
        store=False,
        help='True when QA Hours exceeds the task time limit.',
    )
    ft_pm_hours_exceeded = fields.Boolean(
        string='PM Hours Exceeded',
        compute='_compute_ft_job_hours',
        store=False,
        help='True when PM Hours exceeds the task time limit.',
    )
    ft_ba_hours_exceeded = fields.Boolean(
        string='BA Hours Exceeded',
        compute='_compute_ft_job_hours',
        store=False,
        help='True when BA Hours exceeds the task time limit.',
    )
    ft_trainee_hours_exceeded = fields.Boolean(
        string='Trainee Hours Exceeded',
        compute='_compute_ft_job_hours',
        store=False,
        help='True when Trainee Hours exceeds the task time limit.',
    )

    @api.model
    def _ft_job_bucket(self, job):
        """Classify a job position into one of dev/qa/pm/ba/trainee by its name.
        Returns False for any other (or empty) job position.

        Read the job name with sudo: hr.job is restricted to HR officers, but
        regular project users still need their timesheet hours bucketed."""
        if not job:
            return False
        name = (job.sudo().name or '').strip().lower()
        if not name:
            return False
        if name.startswith('trainee'):
            return 'trainee'
        return FT_JOB_BUCKET_MAP.get(name, False)

    @api.depends('timesheet_ids.unit_amount', 'timesheet_ids.employee_id.job_id')
    def _compute_ft_job_hours(self):
        # Classify by the EMPLOYEE's current job position rather than a stored
        # value, so historical lines map correctly and recompute when the
        # employee's job position changes. Mirrors the project-level compute.
        time_limit = float(
            self.env['ir.config_parameter'].sudo().get_param(
                'ft_task_hours_tracker.default_time_limit', default=0.0
            )
        )
        for task in self:
            totals = dict.fromkeys(FT_BUCKETS, 0.0)
            for line in task.timesheet_ids:
                bucket = self._ft_job_bucket(line.employee_id.job_id)
                if bucket:
                    totals[bucket] += line.unit_amount
            task.ft_dev_hours = totals['dev']
            task.ft_qa_hours = totals['qa']
            task.ft_pm_hours = totals['pm']
            task.ft_ba_hours = totals['ba']
            task.ft_trainee_hours = totals['trainee']
            task.ft_dev_hours_exceeded = time_limit > 0 and totals['dev'] > time_limit
            task.ft_qa_hours_exceeded = time_limit > 0 and totals['qa'] > time_limit
            task.ft_pm_hours_exceeded = time_limit > 0 and totals['pm'] > time_limit
            task.ft_ba_hours_exceeded = time_limit > 0 and totals['ba'] > time_limit
            task.ft_trainee_hours_exceeded = time_limit > 0 and totals['trainee'] > time_limit

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
