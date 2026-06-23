from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError

# Stage names (case-insensitive) used to drive the mandatory-field rules.
COLD_STAGE = 'cold'
# Business Challenge / Expected Revenue / Expected Closing / Technology become
# mandatory from the Qualified stage onward.
QUALIFIED_PLUS_STAGES = {
    'qualified', 'estimation', 'proposition', 'negotiation', 'won', 'lost',
}
WON_STAGE = 'won'
NEXT_ACTION_MIN_LEN = 20


class InheritCrmLead(models.Model):
    _inherit = 'crm.lead'

    account_id = fields.Many2one('res.partner', string='Account')
    features_id = fields.Many2one('cus.features', string='Features')

    lead_source = fields.Selection([
        ('web', 'Web'),
        ('linkedin', 'Linkedin'),
        ('call', 'Call'),
        ('salesforce', 'Salesforce'),
        ('bni', 'BNI'),
        ('events', 'Events'),
    ], string='Lead Source')

    owner_id = fields.Many2one('res.users', string='Owner')
    technology_id = fields.Many2one('cus.technology', string='Technology')
    profit = fields.Monetary(string='Profit', currency_field='company_currency')
    amount = fields.Monetary(string='Amount', currency_field='company_currency')
    rating = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ], string='Rating')
    revenue = fields.Monetary(string='Closed Amount', currency_field='company_currency')
    source_amount = fields.Monetary(string='Source Amount', currency_field='company_currency')
    cus_type = fields.Selection([
        ('New', 'New'),
        ('Exisitng', 'Exisitng'),
    ], string='Type')

    use_case = fields.Text(string='Use Case')

    # Helper currency field
    company_currency = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id.id
    )


    business_challenge = fields.Text(string="Business Challenge")

    decision_maker = fields.Text(string="Decision Maker")

    number_of_users = fields.Integer(string="Number of Users")

    next_action = fields.Text(string="Next Action")

    description_text = fields.Text(string="Description")

    linkedin_url = fields.Char(string="LinkedIn URL")

    # Snapshot of `next_action` as it was at the last stage change. Used to make
    # sure the user actually updates Next Action between two stage changes.
    last_stage_next_action = fields.Text(
        string="Next Action (last stage change)", copy=False,
    )

    # Stage helper flags, used by the form view to drive the mandatory fields.
    is_cold_stage = fields.Boolean(
        string="Is Cold Stage", compute='_compute_stage_flags',
    )
    require_qualified_fields = fields.Boolean(
        string="Require Qualified Fields", compute='_compute_stage_flags',
        help="True from the Qualified stage onward.",
    )
    is_won_stage = fields.Boolean(
        string="Is Won Stage", compute='_compute_stage_flags',
    )

    @api.depends('stage_id', 'stage_id.name')
    def _compute_stage_flags(self):
        for lead in self:
            name = (lead.stage_id.name or '').strip().lower()
            lead.is_cold_stage = name == COLD_STAGE
            lead.require_qualified_fields = name in QUALIFIED_PLUS_STAGES
            lead.is_won_stage = name == WON_STAGE

    @api.constrains('next_action', 'stage_id', 'type')
    def _check_next_action(self):
        """Next Action is mandatory (min 20 chars) in every stage except Cold."""
        for lead in self:
            if lead.type != 'opportunity' or lead.is_cold_stage:
                continue
            text = (lead.next_action or '').strip()
            if not text:
                raise ValidationError(
                    "Next Action is required for opportunities in every stage except Cold."
                )
            if len(text) < NEXT_ACTION_MIN_LEN:
                raise ValidationError(
                    "Next Action must be at least %d characters long." % NEXT_ACTION_MIN_LEN
                )

    @api.constrains('expected_revenue', 'date_deadline', 'business_challenge',
                    'technology_id', 'stage_id', 'type')
    def _check_qualified_fields(self):
        """Business Challenge, Expected Revenue, Expected Closing and Technology
        are mandatory from the Qualified stage onward (Expected Revenue must be
        non-zero, as 0 counts as 'filled' for a monetary field)."""
        for lead in self:
            if lead.type != 'opportunity' or not lead.require_qualified_fields:
                continue
            missing = []
            if not lead.expected_revenue:
                missing.append('Expected Revenue')
            if not lead.date_deadline:
                missing.append('Expected Closing')
            if not lead.business_challenge:
                missing.append('Business Challenge')
            if not lead.technology_id:
                missing.append('Technology')
            if missing:
                raise ValidationError(
                    "The following fields are required from the Qualified stage "
                    "onward: %s." % ', '.join(missing)
                )

    @api.constrains('revenue', 'stage_id', 'type')
    def _check_closed_amount(self):
        """Closed Amount is mandatory (non-zero) on the Won stage."""
        for lead in self:
            if lead.type == 'opportunity' and lead.is_won_stage and not lead.revenue:
                raise ValidationError(
                    "Closed Amount is required (and must be greater than 0) on the Won stage."
                )

    def write(self, vals):
        """Force the user to update 'Next Action' before any stage change.

        The check compares the effective Next Action (the value being written,
        or the current one) against the snapshot stored at the last stage
        change. This works both for a form save (Next Action + stage in one
        write) and for a Kanban drag (only stage_id is written) as long as
        Next Action was updated since the previous stage change.
        """
        stage_changing = self.browse()
        if 'stage_id' in vals:
            new_stage = vals.get('stage_id')
            for lead in self:
                if lead.type != 'opportunity' or lead.stage_id.id == new_stage:
                    continue
                effective_next = (
                    vals['next_action'] if 'next_action' in vals else lead.next_action
                ) or ''
                if effective_next.strip() == (lead.last_stage_next_action or '').strip():
                    raise UserError(
                        "Please update the 'Next Action' before changing the stage"
                        " of '%s'." % (lead.name or '')
                    )
                stage_changing |= lead
        res = super().write(vals)
        # Snapshot the new Next Action for the records whose stage just changed.
        for lead in stage_changing:
            super(InheritCrmLead, lead).write(
                {'last_stage_next_action': lead.next_action or ''}
            )
        # Closed Amount must be filled (non-zero) whenever an opportunity is
        # saved on the Won stage, even if Closed Amount itself wasn't edited.
        self._check_closed_amount()
        return res
