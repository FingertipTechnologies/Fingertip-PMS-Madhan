from odoo import models, fields, api
from odoo.exceptions import ValidationError


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
    revenue = fields.Monetary(string='Revenue', currency_field='company_currency')
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

    # True when the opportunity sits in the "Cold" stage. Used by the form view
    # to relax the mandatory fields for cold opportunities only.
    is_cold_stage = fields.Boolean(
        string="Is Cold Stage", compute='_compute_is_cold_stage',
    )

    @api.depends('stage_id', 'stage_id.name')
    def _compute_is_cold_stage(self):
        for lead in self:
            lead.is_cold_stage = (lead.stage_id.name or '').strip().lower() == 'cold'

    @api.constrains('expected_revenue', 'stage_id', 'type')
    def _check_expected_revenue_required(self):
        """Expected Revenue is a monetary field, so a value of 0 is treated as
        'filled' by the form's `required` modifier. Enforce a real, non-zero
        amount for opportunities once they leave the Cold stage."""
        for lead in self:
            if (lead.type == 'opportunity'
                    and not lead.is_cold_stage
                    and not lead.expected_revenue):
                raise ValidationError(
                    "Expected Revenue is required (and must be greater than 0) "
                    "for opportunities from the Discussion stage onward."
                )
