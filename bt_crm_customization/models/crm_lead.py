from odoo import models, fields


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
