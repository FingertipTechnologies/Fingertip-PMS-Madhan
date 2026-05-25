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

    def _check_task_time_limit(self, task, new_total):
        time_limit = self._get_task_time_limit()
        if task and time_limit > 0 and new_total > time_limit:
            raise UserError(_(
                'Task time limit reached!\n\n'
                'Task: %s\n'
                'Time Limit: %.2f hours\n'
                'Hours Already Logged: %.2f hours\n\n'
                'You cannot log more hours as it would exceed the task time limit. '
                'Please create a new task to continue the work.'
            ) % (task.name, time_limit, task.effective_hours))

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
                self._check_task_time_limit(task, task.effective_hours + unit_amount)
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
            # Recalculate task total when hours or task changes
            if 'unit_amount' in vals or 'task_id' in vals:
                unit_amount = vals.get('unit_amount', line.unit_amount) or 0.0
                task = self.env['project.task'].browse(vals['task_id']) if 'task_id' in vals else line.task_id
                if task:
                    old_amount = line.unit_amount if line.task_id == task else 0.0
                    self._check_task_time_limit(task, task.effective_hours - old_amount + unit_amount)
        return super().write(vals)
