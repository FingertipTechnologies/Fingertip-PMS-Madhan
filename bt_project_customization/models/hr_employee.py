from odoo import models, fields,api


from odoo import models, fields, api

class HREmployee(models.Model):
    _inherit = 'hr.employee'

    # Make the Job Position mandatory (used to classify task/project hours).
    job_id = fields.Many2one(required=True)

    @api.onchange('job_id')
    def _onchange_job_id(self):
        """
        When job_id is changed in hr.employee, update all related
        account.analytic.line records with the new jobposition_id
        """
        if self.job_id:
            analytic_lines = self.env['account.analytic.line'].search([
                ('employee_id', '=', self.id)
            ])
            for line in analytic_lines:
                line.jobposition_id = self.job_id