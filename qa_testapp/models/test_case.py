from odoo import models, fields, api, _
from odoo.exceptions import UserError


APPROVAL_WORKFLOW_FIELDS = {
    'approval_state',
    'submitted_by_id', 'submitted_date',
    'approved_by_id', 'approved_date',
    'rejected_by_id', 'rejection_reason',
}


class QATestCase(models.Model):
    _name = 'qa_testapp.test_case'
    _description = 'QA Test Case'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'test_case_id'

    test_case_id = fields.Char(string='Test Case ID', readonly=True, copy=False, default='New')
    test_case_title = fields.Char(string='Test Case Title', required=True, tracking=True)
    project_id = fields.Many2one('project.project', string='Project', required=True, tracking=True)
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
    ], string='Status', default='not_executed', tracking=True)
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

    # ------------------------------------------------------------------
    # Approval workflow
    # ------------------------------------------------------------------
    approval_state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Approval', default='draft', tracking=True, copy=False, required=True)
    submitted_by_id = fields.Many2one('res.users', string='Submitted By', readonly=True, copy=False)
    submitted_date = fields.Datetime(string='Submitted On', readonly=True, copy=False)
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    approved_date = fields.Datetime(string='Approved On', readonly=True, copy=False)
    rejected_by_id = fields.Many2one('res.users', string='Rejected By', readonly=True, copy=False)
    rejection_reason = fields.Text(string='Rejection Reason', readonly=True, copy=False)

    # Per-record approval permission for the current user. Drives button
    # visibility — non-stored so it re-evaluates per session.
    can_user_approve = fields.Boolean(
        compute='_compute_can_user_approve',
        help="True if the current user can approve THIS record "
             "(PM of its project, or TL of the helpdesk team linked to its customer).",
    )

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

    # ------------------------------------------------------------------
    # Approval helpers
    # ------------------------------------------------------------------
    @api.model
    def _user_is_qa_approver(self, user=None):
        """Global approver check — used only by `create()` to decide if a
        record should auto-approve (PM/TL are trusted globally for their
        OWN records). Per-record approval of OTHERS' records uses
        `_can_approve_record` instead."""
        user = user or self.env.user
        if user.has_group('project.group_project_manager'):
            return True
        if self.env['ft.helpdesk.team'].sudo().search_count(
            [('leader_user_id', '=', user.id)]
        ):
            return True
        return False

    def _project_approver_users(self):
        """Return the set of users authorized to approve THIS record:
          - project.user_id (Project Manager of the record's project)
          - leader of the helpdesk team linked to the project's customer
        Mirrors the lookup pattern used by _escalate_on_reopen in ticket.py."""
        self.ensure_one()
        approvers = self.env['res.users']
        project = self.project_id
        if not project:
            return approvers
        if project.user_id:
            approvers |= project.user_id
        partner = project.partner_id
        if partner:
            customer_team = (
                partner.commercial_partner_id.helpdesk_team_id
                or partner.helpdesk_team_id
            )
            if customer_team and customer_team.leader_user_id:
                approvers |= customer_team.leader_user_id
        return approvers

    def _can_approve_record(self, user=None):
        """Per-record check: is `user` an authorized approver of THIS record?"""
        self.ensure_one()
        user = user or self.env.user
        return user in self._project_approver_users()

    def _project_has_approver(self):
        """True if THIS record's project has at least one PM or TL configured.
        Used to fail submit loudly when no one can approve the record."""
        self.ensure_one()
        return bool(self._project_approver_users())

    @api.depends('project_id', 'project_id.user_id', 'project_id.partner_id')
    def _compute_can_user_approve(self):
        user = self.env.user
        for rec in self:
            rec.can_user_approve = rec._can_approve_record(user)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('test_case_id', 'New') == 'New':
                vals['test_case_id'] = self.env['ir.sequence'].next_by_code(
                    'qa_testapp.test_case'
                ) or 'New'
            # Decide whether this record needs approval based on the creator.
            # Approvers and trusted users skip the approval gate entirely.
            if 'approval_state' not in vals:
                creator = self.env.user
                skip = (
                    self._user_is_qa_approver(creator)
                    or not creator.qa_requires_approval
                )
                if skip:
                    vals['approval_state'] = 'approved'
                    vals.setdefault('approved_by_id', creator.id)
                    vals.setdefault('approved_date', fields.Datetime.now())
                else:
                    vals['approval_state'] = 'draft'
        return super().create(vals_list)

    def write(self, vals):
        # Approved records are locked. Only writes that exclusively touch the
        # approval workflow fields (i.e. coming from action_reopen / action_*)
        # are allowed through.
        is_workflow_write = vals and set(vals.keys()).issubset(APPROVAL_WORKFLOW_FIELDS)
        if not is_workflow_write:
            for rec in self:
                if rec.approval_state == 'approved':
                    raise UserError(_(
                        "This test case is approved and locked. "
                        "Ask a Project Manager or Team Lead to re-open it before editing."
                    ))
        return super().write(vals)

    # ------------------------------------------------------------------
    # Workflow actions
    # ------------------------------------------------------------------
    def action_submit_for_approval(self):
        for rec in self:
            if rec.approval_state not in ('draft', 'rejected'):
                raise UserError(_("Only Draft or Rejected test cases can be submitted."))
            if not rec._project_has_approver():
                raise UserError(_(
                    "No approver is configured for project '%s'. "
                    "Ask Admin to set a Project Manager on the project, "
                    "or assign a Helpdesk Team Leader to the project's customer."
                ) % (rec.project_id.name or '?'))
            rec.write({
                'approval_state': 'pending',
                'submitted_by_id': self.env.user.id,
                'submitted_date': fields.Datetime.now(),
            })
            rec.message_post(body=_("Submitted for approval by %s.") % self.env.user.name)

    def action_approve(self):
        for rec in self:
            if rec.approval_state != 'pending':
                raise UserError(_("Only test cases pending approval can be approved."))
            if not rec._can_approve_record():
                raise UserError(_(
                    "You are not authorized to approve this test case. "
                    "Only the Project Manager of project '%s' or the Team Lead "
                    "of its customer's Helpdesk Team can approve."
                ) % (rec.project_id.name or '?'))
            rec.write({
                'approval_state': 'approved',
                'approved_by_id': self.env.user.id,
                'approved_date': fields.Datetime.now(),
                'rejection_reason': False,
            })
            rec.message_post(body=_("Approved by %s.") % self.env.user.name)

    def action_reject_open_wizard(self):
        self.ensure_one()
        if self.approval_state != 'pending':
            raise UserError(_("Only test cases pending approval can be rejected."))
        if not self._can_approve_record():
            raise UserError(_(
                "You are not authorized to reject this test case. "
                "Only the Project Manager or Team Lead of its project can reject."
            ))
        return {
            'name': _('Reject Test Case'),
            'type': 'ir.actions.act_window',
            'res_model': 'qa_testapp.approval.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': self._name,
                'default_res_id': self.id,
            },
        }

    def action_reopen(self):
        for rec in self:
            if rec.approval_state != 'approved':
                raise UserError(_("Only approved test cases can be re-opened."))
            if not rec._can_approve_record():
                raise UserError(_(
                    "You are not authorized to re-open this test case. "
                    "Only the Project Manager or Team Lead of its project can re-open."
                ))
            rec.write({'approval_state': 'draft'})
            rec.message_post(body=_("Re-opened for edits by %s.") % self.env.user.name)

    def action_bulk_approve(self):
        """Approve all *scoped* pending records the user is authorized for.
        Records belonging to projects the user doesn't lead are silently
        skipped — a notification reports how many were approved vs. skipped."""
        pending = self.filtered(lambda r: r.approval_state == 'pending')
        if not pending:
            raise UserError(_("No pending test cases selected."))
        user = self.env.user
        approvable = pending.filtered(lambda r: r._can_approve_record(user))
        skipped = pending - approvable
        if not approvable:
            raise UserError(_(
                "You are not authorized to approve any of the selected test cases. "
                "Only the PM or Team Lead of each record's project can approve."
            ))
        approvable.write({
            'approval_state': 'approved',
            'approved_by_id': user.id,
            'approved_date': fields.Datetime.now(),
            'rejection_reason': False,
        })
        for rec in approvable:
            rec.message_post(body=_("Approved (bulk) by %s.") % user.name)
        if skipped:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Bulk Approve"),
                    'message': _("%(ok)d approved. %(skipped)d skipped (not your project/team).") % {
                        'ok': len(approvable), 'skipped': len(skipped),
                    },
                    'type': 'success',
                    'sticky': False,
                },
            }
