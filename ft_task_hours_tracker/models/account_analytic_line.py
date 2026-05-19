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
            task_id = vals.get('task_id')
            unit_amount = vals.get('unit_amount', 0.0)
            if task_id and unit_amount > 0:
                task = self.env['project.task'].browse(task_id)
                new_total = task.effective_hours + unit_amount
                self._check_task_time_limit(task, new_total)
        return super().create(vals_list)

    def write(self, vals):
        if 'unit_amount' in vals or 'task_id' in vals:
            for line in self:
                task = self.env['project.task'].browse(vals['task_id']) if 'task_id' in vals else line.task_id
                if not task:
                    continue
                new_amount = vals.get('unit_amount', line.unit_amount)
                old_amount = line.unit_amount if line.task_id == task else 0.0
                new_total = task.effective_hours - old_amount + new_amount
                self._check_task_time_limit(task, new_total)
        return super().write(vals)
