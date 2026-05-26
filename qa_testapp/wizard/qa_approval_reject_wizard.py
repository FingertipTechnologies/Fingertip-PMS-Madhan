from odoo import models, fields, _
from odoo.exceptions import UserError


class QAApprovalRejectWizard(models.TransientModel):
    _name = 'qa_testapp.approval.reject.wizard'
    _description = 'QA Approval Rejection Wizard'

    res_model = fields.Char(required=True)
    res_id = fields.Integer(required=True)
    reason = fields.Text(string='Rejection Reason', required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        if self.res_model not in ('qa_testapp.test_case', 'qa_testapp.ticket'):
            raise UserError(_("Unsupported record type for QA rejection."))
        record = self.env[self.res_model].browse(self.res_id)
        if not record.exists():
            raise UserError(_("Record not found."))
        if not record._user_is_qa_approver():
            raise UserError(_("Only a Project Manager or Team Lead can reject."))
        if record.approval_state != 'pending':
            raise UserError(_("Only records pending approval can be rejected."))
        record.write({
            'approval_state': 'rejected',
            'rejected_by_id': self.env.user.id,
            'rejection_reason': self.reason,
        })
        record.message_post(body=_(
            "Rejected by %s. Reason: %s"
        ) % (self.env.user.name, self.reason))
        return {'type': 'ir.actions.act_window_close'}
