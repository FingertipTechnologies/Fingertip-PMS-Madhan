from odoo import models, api, _
from odoo.exceptions import UserError


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    def _get_task_time_limit(self):
        return float(
            self.env['ir.config_parameter'].sudo().get_param(
                'ft_task_hours_tracker.default_time_limit', default=0.0
            )
        )

    def _is_billable_project(self, project):
        return bool(project and project.allow_billable)

    def _check_single_entry_hours(self, unit_amount):
        time_limit = self._get_task_time_limit()
        if time_limit > 0 and unit_amount > time_limit:
            raise UserError(_(
                'A single timesheet entry cannot exceed %.2f hours.\n'
                'Please split your time into multiple entries.'
            ) % time_limit)

    # Job-position buckets shown on the task form (Dev / QA / PM / BA / Trainee).
    # The time limit applies to EACH bucket separately, mirroring the per-field
    # warning.
    _FT_BUCKET_LABELS = {
        'dev': 'Development',
        'qa': 'QA',
        'pm': 'Project Management',
        'ba': 'Business Analysis',
        'trainee': 'Trainee',
    }

    def _ft_line_bucket(self, employee):
        """Return the dev/qa/pm/ba/trainee bucket for a line's employee, or False."""
        return self.env['project.task']._ft_job_bucket(employee.job_id)

    def _ft_existing_bucket_hours(self, task, bucket, exclude_line=None):
        """Sum the hours already logged on `task` for the given job-position
        bucket, optionally excluding one line (the one being edited)."""
        total = 0.0
        ProjectTask = self.env['project.task']
        for line in task.timesheet_ids:
            if exclude_line and line.id and line.id == exclude_line.id:
                continue
            # Classify by the employee's current job position, consistent with
            # the task/project hour computes.
            if ProjectTask._ft_job_bucket(line.employee_id.job_id) == bucket:
                total += line.unit_amount
        return total

    def _check_department_time_limit(self, task, bucket, new_bucket_total):
        time_limit = self._get_task_time_limit()
        if task and bucket and time_limit > 0 and new_bucket_total > time_limit:
            label = self._FT_BUCKET_LABELS.get(bucket, bucket)
            raise UserError(_(
                '%s time limit reached!\n\n'
                'Task: %s\n'
                'Time Limit: %.2f hours\n\n'
                'You cannot log more %s hours as it would exceed the time limit. '
                'Please create a new task to continue the work.'
            ) % (label, task.name, time_limit, label))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            project_id = vals.get('project_id')
            if not project_id:
                continue
            project = self.env['project.project'].browse(project_id)
            if not self._is_billable_project(project):
                continue
            if not (vals.get('name') or '').strip():
                raise UserError(_('Description is required. Please enter a description for the timesheet entry.'))
            unit_amount = vals.get('unit_amount') or 0.0
            if unit_amount <= 0:
                raise UserError(_('Time Spent is required. Please enter the hours spent for the timesheet entry.'))
            self._check_single_entry_hours(unit_amount)
            task_id = vals.get('task_id')
            if task_id:
                task = self.env['project.task'].browse(task_id)
                employee_id = vals.get('employee_id')
                employee = (
                    self.env['hr.employee'].browse(employee_id)
                    if employee_id else self.env.user.employee_id
                )
                bucket = self._ft_line_bucket(employee)
                if bucket:
                    existing = self._ft_existing_bucket_hours(task, bucket)
                    self._check_department_time_limit(task, bucket, existing + unit_amount)
        return super().create(vals_list)

    def write(self, vals):
        for line in self:
            project = (
                self.env['project.project'].browse(vals['project_id'])
                if 'project_id' in vals
                else line.project_id
            )
            if not self._is_billable_project(project):
                continue
            # Validate description only when it is being explicitly changed
            if 'name' in vals and not (vals.get('name') or '').strip():
                raise UserError(_('Description is required. Please enter a description for the timesheet entry.'))
            # Validate time only when it is being explicitly changed
            if 'unit_amount' in vals:
                unit_amount = vals.get('unit_amount') or 0.0
                if unit_amount <= 0:
                    raise UserError(_('Time Spent is required. Please enter the hours spent for the timesheet entry.'))
                self._check_single_entry_hours(unit_amount)
            # Re-check the department bucket limit when hours, task or employee change
            if 'unit_amount' in vals or 'task_id' in vals or 'employee_id' in vals:
                unit_amount = vals.get('unit_amount', line.unit_amount) or 0.0
                task = self.env['project.task'].browse(vals['task_id']) if 'task_id' in vals else line.task_id
                employee = (
                    self.env['hr.employee'].browse(vals['employee_id'])
                    if 'employee_id' in vals else line.employee_id
                )
                bucket = self._ft_line_bucket(employee)
                if task and bucket:
                    existing = self._ft_existing_bucket_hours(task, bucket, exclude_line=line)
                    self._check_department_time_limit(task, bucket, existing + unit_amount)
        return super().write(vals)
