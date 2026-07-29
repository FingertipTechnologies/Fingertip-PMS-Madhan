from odoo import models, api, _
from odoo.exceptions import UserError


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    def _ft_check_task_not_completed(self, task):
        """Refuse time entry on a task sitting in a Completed (folded) stage.

        Time logged after delivery is what makes rework invisible: the hours
        land on a task that already counts as finished, so the extra effort
        never shows up as a reopen and the Rework Rate stays flattering. Making
        the person move the task back to Working first is what turns that
        second round of work into a counted reopen.

        Keyed off ``stage_id.fold`` rather than ``state``, for the same reason
        the delivery metrics are: stages in this database do not set state, so
        checking state would let almost everything through.

        Superuser is exempt so imports, migrations and scheduled jobs are not
        blocked; a plain administrator is NOT, because admins log time too and
        exempting them would leave the rule unenforced for the people most
        likely to bypass it.
        """
        if self.env.su or not task or not task.stage_id.fold:
            return
        raise UserError(_(
            'This task is completed — timesheets cannot be logged on it.\n\n'
            'Task: %s\n'
            'Stage: %s\n\n'
            'If more work is needed, move the task back to Working first. '
            'Reopening it that way is recorded as rework and counts towards '
            "the project's Rework Rate."
        ) % (task.name, task.stage_id.name))

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
            # Runs before the billable-project guard below: a completed task
            # takes no more time whether or not its project is billable.
            if vals.get('task_id'):
                self._ft_check_task_not_completed(
                    self.env['project.task'].browse(vals['task_id']))
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
            # Editing the hours on a completed task, or moving a line onto one,
            # would get round the create-time guard.
            if 'unit_amount' in vals or 'task_id' in vals:
                self._ft_check_task_not_completed(
                    self.env['project.task'].browse(vals['task_id'])
                    if 'task_id' in vals else line.task_id)
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
