import logging
from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


# Priority -> (human-readable response-time band, deadline offset in minutes).
# Deadline uses the upper bound of each band (lenient SLA semantics).
TARGET_TIME_BY_PRIORITY = {
    'p1': ('15-30 mins',     30),
    'p2': ('1-2 hours',     120),
    'p3': ('4-8 hours',     480),
    'p4': ('1 business day', 24 * 60),
}


APPROVAL_WORKFLOW_FIELDS = {
    'approval_state',
    'submitted_by_id', 'submitted_date',
    'approved_by_id', 'approved_date',
    'rejected_by_id', 'rejection_reason',
}


class QATicket(models.Model):
    _name = 'qa_testapp.ticket'
    _description = 'QA Bug Ticket'
    _order = 'id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'title'

    bug_id = fields.Char(string='Bug ID', readonly=True, copy=False, default='New', tracking=True)
    title = fields.Char(string='Title / Summary', required=True, tracking=True,
                        help="One-line specific summary, e.g., 'Login fails with 500 when password contains #'.")
    description = fields.Text(string='Description', help="What's wrong + what you expected.")
    steps_to_reproduce = fields.Text(string='Steps to Reproduce', help="Numbered steps.")
    expected_result = fields.Text(string='Expected Result')
    actual_result = fields.Text(string='Actual Result')

    # New Checkbox Fields
    is_client = fields.Boolean(string='Client', help="Check if this bug was raised by a client.")
    is_internal = fields.Boolean(string='Internal', help="Check if this bug was found internally.")

    # Modified reporter_id (removed default value so it starts blank when internal is clicked)
    reporter_id = fields.Many2one('res.users', string='Reporter', tracking=True)

    @api.onchange('is_client')
    def _onchange_is_client(self):
        """Automatically treats client-raised bugs with higher severity/priority"""
        if self.is_client:
            self.is_internal = False
            self.reporter_id = False  # Clear reporter if it's a client
            
            # Upgrade priority to P1 (Urgent) and severity to Critical automatically
            self.priority = 'p1'
            if self.severity not in ('blocker', 'critical'):
                self.severity = 'critical'

    @api.onchange('is_internal')
    def _onchange_is_internal(self):
        """Toggles off client selection when internal is chosen"""
        if self.is_internal:
            self.is_client = False
            # Default the reporter to the current logged-in user when internal is checked
            self.reporter_id = self.env.user
    environment = fields.Selection([
        ('sandbox', 'Sandbox'),
        ('qa', 'QA'),
        ('production', 'Production')
    ], string='Environment', default='sandbox', required=True)
    device = fields.Selection([
        ('mobile', 'Mobile'),
        ('desktop', 'Desktop'),
        ('tablet', 'Tablet')
    ], string='Device', default='desktop')
    severity = fields.Selection([
        ('blocker', 'Blocker'),
        ('critical', 'Critical'),
        ('major', 'Major'),
        ('minor', 'Minor'),
        ('trivial', 'Trivial')
    ], string='Severity', default='major', tracking=True)
    priority = fields.Selection([
        ('p1', 'P1 - Urgent'),
        ('p2', 'P2 - High'),
        ('p3', 'P3 - Medium'),
        ('p4', 'P4 - Low'),
        ('p5', 'P5 - Backlog')
    ], string='Priority', default='p3', tracking=True)
    target_response_time = fields.Char(
        string='Target Response Time',
        compute='_compute_target_response', store=True, readonly=True,
        help='Auto-set from priority. Informational only (not required).',
    )
    target_deadline = fields.Datetime(
        string='Target Deadline',
        compute='_compute_target_response', store=True, readonly=True,
        help='Reported date + the upper bound of the priority response band.',
    )
    status = fields.Selection([
        ('open', 'Open'),
        ('in_progress', 'In Progress'),
        ('fixed', 'Fixed'),
        ('closed', 'Closed'),
        ('reopened', 'Re-Opened')
    ], string='Status', default='open', tracking=True)
    reproducibility = fields.Selection([
        ('always', 'Always'),
        ('sometimes', 'Sometimes'),
        ('rare', 'Rare'),
        ('unable', 'Unable to Reproduce')
    ], string='Reproducibility', default='always')
    evidence_notes = fields.Text(string='Evidence Notes')
    evidence_attachment_ids = fields.Many2many(
        'ir.attachment', 'qa_testapp_ticket_attachment_rel',
        'ticket_id', 'attachment_id',
        string='Attachments',
    )
    reporter_id = fields.Many2one('res.users', string='Reporter', default=lambda self: self.env.user, tracking=True)
    reported_date = fields.Datetime(string='Reported Date', default=fields.Datetime.now)
    project_id = fields.Many2one('project.project', string='Project', required=True)
    module = fields.Char(string='Module (legacy)', tracking=True)
    module_id = fields.Many2one(
        'cus.module', string='Module', tracking=True,
        domain="[('id', 'in', available_module_ids)]",
    )
    available_module_ids = fields.Many2many(
        'cus.module', compute='_compute_available_modules',
    )
    test_case_id = fields.Many2one('qa_testapp.test_case', string='Related Test Case')
    assignee_id = fields.Many2one('res.users', string='Assignee', required=True, tracking=True)
    reopen_count = fields.Integer(
        string='Reopen Count', default=0,
        readonly=True, copy=False, tracking=True,
        help='Number of times this bug has been re-opened.',
    )
    escalation_level = fields.Selection([
        ('none', 'None'),
        ('qa_lead', 'QA Lead'),
        ('manager', 'Manager'),
    ], string='Escalation', default='none',
       readonly=True, copy=False, tracking=True)

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
    
    
    @api.depends('priority', 'reported_date')
    def _compute_target_response(self):
        for rec in self:
            mapping = TARGET_TIME_BY_PRIORITY.get(rec.priority)
            if not mapping:
                rec.target_response_time = False
                rec.target_deadline = False
                continue
            label, offset_minutes = mapping
            rec.target_response_time = label
            rec.target_deadline = (
                rec.reported_date + timedelta(minutes=offset_minutes)
                if rec.reported_date else False
            )

    def action_in_progress(self):
        self.write({'status': 'in_progress'})

    def action_fixed(self):
        self.write({'status': 'fixed'})

    def action_closed(self):
        self.write({'status': 'closed'})

    def action_reopen(self):
        for ticket in self:
            new_count = ticket.reopen_count + 1
            ticket.write({'status': 'reopened', 'reopen_count': new_count})
            ticket._escalate_on_reopen()

    def _escalate_on_reopen(self):
        """Hierarchy-based escalation driven by reopen_count.
        3rd reopen -> project.qa_lead_id (fallback: project.user_id), level='qa_lead'.
        4th+ reopen -> project.user_id (Project Manager), level='manager'.
        No-op for the 1st/2nd reopen. Manual assignee changes between reopens
        are preserved; re-escalation only fires on the next reopen click."""
        self.ensure_one()
        project = self.project_id
        if not project:
            return
        count = self.reopen_count
        if count < 3:
            return

        if count == 3:
            # QA Lead is derived from the project's customer's Support Team.
            # Mirrors the auto-assign pattern in ft_helpdesk_core/models/ticket.py:
            # try the commercial (parent company) partner's team first, then
            # the contact's own team.
            partner = project.partner_id
            customer_team = (
                partner.commercial_partner_id.helpdesk_team_id
                or partner.helpdesk_team_id
            ) if partner else self.env['ft.helpdesk.team']
            qa_lead = customer_team.leader_user_id
            target = qa_lead or project.user_id
            new_level = 'qa_lead'
            if qa_lead:
                target_role = 'QA Lead'
            elif not partner:
                target_role = 'Project Manager (no customer on project)'
            elif not customer_team:
                target_role = "Project Manager (customer has no Support Team)"
            else:
                target_role = 'Project Manager (customer Support Team has no leader)'
        else:
            target = project.user_id
            new_level = 'manager'
            target_role = 'Project Manager'

        if not target:
            _logger.warning(
                "Bug %s: cannot escalate to %s - no user configured on project '%s'",
                self.bug_id, new_level, project.name,
            )
            self.message_post(
                body=(
                    "<p>Reopen #%d reached but escalation skipped: no %s "
                    "configured on project <strong>%s</strong>.</p>"
                ) % (count, target_role, project.name),
                message_type='notification',
            )
            return

        self.write({'assignee_id': target.id, 'escalation_level': new_level})
        self.message_post(
            body=(
                "<p>Bug re-opened %d time(s). Escalated to <strong>%s</strong>: "
                "<strong>%s</strong>.</p>"
            ) % (count, target_role, target.name),
            message_type='notification',
        )
        self.activity_schedule(
            'mail.mail_activity_data_todo',
            user_id=target.id,
            summary='Escalated bug: %s (%d reopens)' % (self.bug_id, count),
            note='Bug %s - "%s" has been escalated to you after %d reopens.' % (
                self.bug_id, self.title, count,
            ),
        )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('bug_id', 'New') == 'New':
                vals['bug_id'] = self.env['ir.sequence'].next_by_code('qa_testapp.ticket') or 'New'
        records = super().create(vals_list)
        records._link_evidence_attachments()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'evidence_attachment_ids' in vals:
            self._link_evidence_attachments()
        return res

    def _link_evidence_attachments(self):
        # Attachments uploaded into the form before save end up with res_id=0,
        # which blocks non-creator users from reading them. Pin them to this record.
        for rec in self:
            atts = rec.sudo().evidence_attachment_ids
            orphans = atts.filtered(
                lambda a: a.res_model != 'qa_testapp.ticket' or a.res_id != rec.id
            )
            if orphans:
                orphans.write({'res_model': 'qa_testapp.ticket', 'res_id': rec.id})
    

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('bug_id', 'New') == 'New':
                vals['bug_id'] = self.env['ir.sequence'].next_by_code('qa_testapp.ticket') or 'New'
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
        records = super().create(vals_list)
        records._link_evidence_attachments()

        # Send explicit notification on creation
        for record in records:
            if record.assignee_id:
                record._notify_assignee()
        return records

    def write(self, vals):
        # Approved bugs are locked. Allow only writes that exclusively touch
        # the approval workflow fields (so action_reopen / action_approve etc.
        # can still operate).
        is_workflow_write = vals and set(vals.keys()).issubset(APPROVAL_WORKFLOW_FIELDS)
        if not is_workflow_write:
            for rec in self:
                if rec.approval_state == 'approved':
                    raise UserError(_(
                        "This bug is approved and locked. "
                        "Ask a Project Manager or Team Lead to re-open it before editing."
                    ))
        res = super().write(vals)
        if 'evidence_attachment_ids' in vals:
            self._link_evidence_attachments()

        # Send explicit notification on change
        if 'assignee_id' in vals:
            for rec in self:
                rec._notify_assignee()
        return res

    def _notify_assignee(self):
        """Finds the assignment email template and sends it to the assignee"""
        self.ensure_one()
        if self.assignee_id and self.assignee_id.email:
            # Locate the template record using its XML ID
            template = self.env.ref('qa_testapp.email_template_bug_assigned', raise_if_not_found=False)
            
            if template:
                # force_send=False queues it in Odoo mail queue; force_send=True sends it instantly
                template.sudo().send_mail(self.id, force_send=True)

    @api.onchange('is_client')
    def _onchange_is_client(self):
        """Automatically treats client-raised bugs with higher severity/priority"""
        if self.is_client:
            self.is_internal = False
            self.reporter_id = False  # Clear reporter if it's a client
            
            # Upgrade priority to P1 (Urgent) and severity to Critical automatically
            self.priority = 'p1'
            if self.severity not in ('blocker', 'critical'):
                self.severity = 'critical'

    @api.onchange('is_internal')
    def _onchange_is_internal(self):
        """Toggles off client selection when internal is chosen"""
        if self.is_internal:
            self.is_client = False
            # Default the reporter to the current logged-in user when internal is checked
            self.reporter_id = self.env.user
    
    # New computed field for clean list-view display
    reporter_display = fields.Char(string='Reporter', compute='_compute_reporter_display')

    @api.depends('is_client', 'is_internal', 'reporter_id')
    def _compute_reporter_display(self):
        for rec in self:
            if rec.is_client:
                rec.reporter_display = "Client"
            elif rec.is_internal and rec.reporter_id:
                rec.reporter_display = rec.reporter_id.name
            else:
                rec.reporter_display = ""

    # ------------------------------------------------------------------
    # Approval workflow
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
        Mirrors the lookup pattern used by _escalate_on_reopen below."""
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
        """True if THIS record's project has at least one PM or TL configured."""
        self.ensure_one()
        return bool(self._project_approver_users())

    @api.depends('project_id', 'project_id.user_id', 'project_id.partner_id')
    def _compute_can_user_approve(self):
        user = self.env.user
        for rec in self:
            rec.can_user_approve = rec._can_approve_record(user)

    def action_submit_for_approval(self):
        for rec in self:
            if rec.approval_state not in ('draft', 'rejected'):
                raise UserError(_("Only Draft or Rejected bugs can be submitted."))
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
                raise UserError(_("Only bugs pending approval can be approved."))
            if not rec._can_approve_record():
                raise UserError(_(
                    "You are not authorized to approve this bug. "
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
            raise UserError(_("Only bugs pending approval can be rejected."))
        if not self._can_approve_record():
            raise UserError(_(
                "You are not authorized to reject this bug. "
                "Only the Project Manager or Team Lead of its project can reject."
            ))
        return {
            'name': _('Reject Bug'),
            'type': 'ir.actions.act_window',
            'res_model': 'qa_testapp.approval.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': self._name,
                'default_res_id': self.id,
            },
        }

    def action_reopen_approval(self):
        """Re-open an approved bug so it can be edited again. Named with the
        `_approval` suffix to avoid colliding with `action_reopen` above
        (which re-opens a *fixed/closed* bug status)."""
        for rec in self:
            if rec.approval_state != 'approved':
                raise UserError(_("Only approved bugs can be re-opened."))
            if not rec._can_approve_record():
                raise UserError(_(
                    "You are not authorized to re-open this bug. "
                    "Only the Project Manager or Team Lead of its project can re-open."
                ))
            rec.write({'approval_state': 'draft'})
            rec.message_post(body=_("Re-opened for edits by %s.") % self.env.user.name)

    def action_bulk_approve(self):
        """Approve all *scoped* pending bugs the user is authorized for.
        Bugs belonging to projects the user doesn't lead are silently skipped
        — a notification reports how many were approved vs. skipped."""
        pending = self.filtered(lambda r: r.approval_state == 'pending')
        if not pending:
            raise UserError(_("No pending bugs selected."))
        user = self.env.user
        approvable = pending.filtered(lambda r: r._can_approve_record(user))
        skipped = pending - approvable
        if not approvable:
            raise UserError(_(
                "You are not authorized to approve any of the selected bugs. "
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