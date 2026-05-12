from odoo import models, fields, api


class QATestCase(models.Model):
    _name = 'qa_testapp.test_case'
    _description = 'QA Test Case'
    _order = 'id desc'
    _rec_name = 'test_case_id'

    test_case_id = fields.Char(string='Test Case ID', readonly=True, copy=False, default='New')
    test_case_title = fields.Char(string='Test Case Title', required=True)
    project_id = fields.Many2one('project.project', string='Project', required=True)
    module_id = fields.Many2one(
        'cus.module', string='Module', required=True,
        domain="[('id', 'in', available_module_ids)]",
    )
    available_module_ids = fields.Many2many(
        'cus.module', compute='_compute_available_modules',
    )
    test_objective = fields.Text(string='Test Details')
    pre_conditions = fields.Text(string='Pre Conditions')
    test_data = fields.Text(string='Test Data')
    test_steps = fields.Text(string='Test Steps')
    expected_result = fields.Text(string='Expected Result')
    actual_result = fields.Text(string='Actual Result')
    status = fields.Selection([
        ('pass', 'Pass'),
        ('fail', 'Fail'),
        ('blocked', 'Blocked'),
        ('not_executed', 'Not Executed')
    ], string='Status', default='not_executed')
    severity = fields.Selection([
        ('critical', 'Critical'),
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low')
    ], string='Severity', default='medium')
    environment = fields.Selection([
        ('sandbox', 'Sandbox'),
        ('qa', 'QA'),
        ('production', 'Production')
    ], string='Environment', default='sandbox')
    executed_date = fields.Date(string='Executed Date')
    executed_by = fields.Many2one('res.users', string='Executed By')
    test_type = fields.Selection([
        ('smoke', 'Smoke'),
        ('functional', 'Functional'),
        ('uat', 'UAT'),
        ('regression', 'Regression')
    ], string='Test Type', default='smoke')

    @api.depends('project_id')
    def _compute_available_modules(self):
        for rec in self:
            if rec.project_id:
                tasks = self.env['project.task'].sudo().search([
                    ('project_id', '=', rec.project_id.id),
                    ('module_id', '!=', False),
                ])
                rec.available_module_ids = tasks.mapped('module_id')
            else:
                rec.available_module_ids = self.env['cus.module'].sudo().search([])

    @api.onchange('project_id')
    def _onchange_project_id(self):
        self.module_id = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('test_case_id', 'New') == 'New':
                vals['test_case_id'] = self.env['ir.sequence'].next_by_code('qa_testapp.test_case') or 'New'
        return super().create(vals_list)
