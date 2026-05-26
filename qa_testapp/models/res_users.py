from odoo import models, fields


class ResUsers(models.Model):
    _inherit = 'res.users'

    qa_requires_approval = fields.Boolean(
        string='Requires QA Approval',
        default=True,
        help="When ticked, this user's QA test cases and bug tickets must be "
             "approved by a Project Manager or Team Lead before being considered "
             "final. Uncheck once the user is past training.",
    )
