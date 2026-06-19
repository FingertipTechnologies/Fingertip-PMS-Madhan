import re

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

# A website must be a bare domain (optionally with scheme / www.) and end at the
# TLD with NOTHING after it: no path, no trailing slash, no query string.
# e.g. https://www.acme.com  -> OK     https://www.acme.com/about -> rejected
WEBSITE_RE = re.compile(r'^(https?://)?(www\.)?([a-z0-9-]+\.)+[a-z]{2,}$', re.IGNORECASE)


class InheritResPartner(models.Model):
    _inherit = 'res.partner'

    account_status_id = fields.Many2one('res.partner.account.status', string="Account Status")

    rating = fields.Selection([
        ('hot', 'Hot'),
        ('cold', 'Cold'),
        ('warm', 'Warm'),

    ], string="Rating")


    #activity_count_custom = fields.Integer(string="Activity Count")
    activity_count_custom = fields.Integer(string="Activity Count",compute="_compute_activity_count_custom")

    connected_contacts = fields.Many2many(
        'res.partner',
        'res_partner_connected_rel',
        'partner_id',
        'connected_partner_id',
        string="Connected Contacts"
    )

    number_of_contacts = fields.Integer(
        string="Number of Contacts",
        compute="_compute_number_of_contacts"
    )

    @api.depends('connected_contacts')
    def _compute_number_of_contacts(self):
        for partner in self:
            partner.number_of_contacts = len(partner.connected_contacts)

   


    @api.depends('activity_ids')
    def _compute_activity_count_custom(self):
        Activity = self.env['mail.activity']

        for partner in self:
            domain = [
                    ('res_model', '=', partner._name),
                    ('res_id', 'in', partner.ids),
                    ('active', 'in', [True, False]),
                ]
            partner.activity_count_custom =  Activity.search_count(domain)
    # Legacy Annual Revenue (Integer, ~10 digits). Kept so existing data is not
    # lost, but hidden in the UI; superseded by annual_revenue_amount below.
    annual_revenue = fields.Integer(string="Annual Revenue (legacy)")
    # New Annual Revenue: Monetary, stored as double precision so it holds whole
    # numbers exactly up to ~9.0 quadrillion (16 digits).
    annual_revenue_currency_id = fields.Many2one(
        'res.currency', string="Currency",
        default=lambda self: self.env.company.currency_id)
    annual_revenue_amount = fields.Monetary(
        string="Annual Revenue", currency_field='annual_revenue_currency_id')
    annual_revenue_range = fields.Char(string="Annual Revenue Range")
    company_linkedin = fields.Char(string="Company LinkedIn")
    contact_date = fields.Date(string="Contact Date")
    # Dedicated rich-text Description, shown as its own notebook tab.
    description = fields.Html(string="Description")
    duplicate_check = fields.Boolean(string="Duplicate")
    company_eid = fields.Char(string="EID")
    employees = fields.Many2one('res.users',string="Employee")

    first_activity_datetime = fields.Datetime(
        compute='_compute_activity_dates',
        store=True,
        index=True
    )

    last_activity_datetime = fields.Datetime(
        compute='_compute_activity_dates',
        store=True,
        index=True
    )

    # ---------------------------------------------------------
    # Compute partner activity dates FROM mail.activity
    # ---------------------------------------------------------
    @api.depends(
        'activity_ids',  # fallback (chatter activities)
    )
    def _compute_activity_dates(self):
        Activity = self.env['mail.activity']

        for partner in self:
            if partner.is_company:
                domain = [
                    ('parent_partner_id', '=', partner.id),
                    ('active', 'in', [True, False]),
                ]
            else:
                domain = [
                    ('child_partner_id', '=', partner.id),
                    ('active', 'in', [True, False]),
                ]

            activities = Activity.search(domain, order='create_date asc')

            if activities:
                partner.first_activity_datetime = activities[0].create_date
                partner.last_activity_datetime = activities[-1].create_date
            else:
                partner.first_activity_datetime = False
                partner.last_activity_datetime = False

    pain_points = fields.Text(string="Pain Points")
    source_id = fields.Many2one('utm.source', string="Source")
    sub_vertical = fields.Char(string="Sub Vertical")
    working_date = fields.Date(string="Working Date")
    email_1 = fields.Char(string="Email 1")
    email_2 = fields.Char(string="Email 2")
    mobile_1 = fields.Char(string="Mobile 1")
    contact_eid = fields.Char(string="EID")
    contact_linkedin = fields.Char(string="LinkedIn")
    contact_account = fields.Char(string="Account")
    company_domain = fields.Char(string="Company Domain")
    # department = fields.Many2one('res.partner.industry',string="Department")
    department = fields.Char(string="Department")

    # ------------------------------------------------------------------
    # Salesperson sync: company's salesperson flows down to child contacts
    # ------------------------------------------------------------------
    @api.model
    def _normalize_website(self, website):
        """Normalise a website to its bare domain, used for matching and as the
        basis for the standard stored value. Strips scheme, 'www.', any
        path/query/fragment, credentials/port and trailing slash/dots, then
        lowercases. e.g. 'https://www.Google.com/search?q=x' -> 'google.com'.

        Pure string handling (no urlparse) so malformed values - brackets,
        stray colons, etc. - never raise (urlparse can throw 'Invalid IPv6 URL')
        and never break an import."""
        if not website:
            return ''
        value = str(website).strip().lower()
        if not value:
            return ''
        # Strip a leading scheme, tolerating malformed ones written without the
        # colon or with the wrong number of slashes: http://, https://, http//,
        # https//, http:/, https:, etc. Requires http/https followed by at least
        # one ':' or '/' so real domains like 'httpbin.org' are left intact.
        value = re.sub(r'^https?[:/]+', '', value)
        # Drop any remaining leading slashes (e.g. '//example.com').
        value = value.lstrip('/')
        # Cut off anything from the first path / query / fragment separator.
        for sep in ('/', '?', '#'):
            cut = value.find(sep)
            if cut != -1:
                value = value[:cut]
        # Drop 'user:pass@' credentials and any ':port' suffix.
        value = value.split('@')[-1].split(':')[0]
        # Strip a leading 'www.'.
        if value.startswith('www.'):
            value = value[4:]
        return value.strip().strip('.')

    @api.model
    def _standardize_website(self, website):
        """Return the website in the standard stored format
        'https://www.<domain>', or '' when there is no usable domain.
        This is the single value actually saved on the record so that every
        company's website is consistent regardless of how it was entered."""
        domain = self._normalize_website(website)
        return 'https://www.%s' % domain if domain else ''

    @api.model
    def _find_company_by_website(self, website):
        """Return an existing company (is_company=True) whose website matches
        the given one, ignoring scheme/www/trailing slash differences."""
        normalized = self._normalize_website(website)
        if not normalized:
            return self.browse()
        companies = self.search([
            ('is_company', '=', True),
            ('website', '!=', False),
        ])
        for company in companies:
            if self._normalize_website(company.website) == normalized:
                return company
        return self.browse()

    @api.model
    def _company_name_from_website(self, website):
        """Derive a readable company name from a website, used as a fallback
        when an imported contact has no company-name column. e.g.
        'https://www.acme-corp.com/about' -> 'Acme Corp'."""
        domain = self._normalize_website(website)
        if not domain:
            return ''
        label = domain.split('/')[0].split('.')[0]
        return label.replace('-', ' ').replace('_', ' ').title() or domain

    @api.constrains('website')
    def _check_website_format(self):
        """Website must end at the domain (e.g. www.example.com) with nothing
        after it - no path, trailing slash, or query string."""
        for partner in self:
            if partner.website and not WEBSITE_RE.match(partner.website.strip()):
                raise ValidationError(_(
                    "Invalid website '%s'. Enter a domain only, like "
                    "www.example.com, with nothing after it "
                    "(no '/', path, or extra characters).",
                    partner.website,
                ))

    @api.constrains('website', 'is_company')
    def _check_unique_company_website(self):
        """A company's website must be unique across companies. Matching
        ignores scheme/www/trailing-slash differences. Individuals and child
        contacts are not checked (they may share the company's website)."""
        for partner in self:
            if not partner.is_company:
                continue
            normalized = self._normalize_website(partner.website)
            if not normalized:
                continue
            others = self.search([
                ('id', '!=', partner.id),
                ('is_company', '=', True),
                ('website', '!=', False),
            ])
            for other in others:
                if self._normalize_website(other.website) == normalized:
                    raise ValidationError(_(
                        "The website '%s' is already used by company '%s'. "
                        "A company's website must be unique.",
                        partner.website, other.name,
                    ))

    @api.model
    def _vals_is_company(self, vals):
        """Decide whether the values describe a company. The web form sends
        ``company_type`` (the Individual/Company toggle), not ``is_company``
        directly, so we must honour both to avoid mis-classifying a company
        as a contact."""
        if 'is_company' in vals:
            return bool(vals['is_company'])
        if vals.get('company_type'):
            return vals['company_type'] == 'company'
        return False

    @api.model_create_multi
    def create(self, vals_list):
        # results keeps the original order; entries are either an already
        # existing company (reused) or are filled in after super().create().
        results = [self.browse()] * len(vals_list)
        to_create = []  # list of (original_index, vals)

        for index, vals in enumerate(vals_list):
            # Standardise the website to 'https://www.<domain>' before any
            # matching or saving, so imports / manual creates all store a
            # consistent value and de-duplication is reliable.
            if vals.get('website'):
                vals['website'] = self._standardize_website(vals['website'])
            is_company = self._vals_is_company(vals)

            # Identify a company by its website (NOT its name): if a company
            # with the same website already exists, reuse it instead of
            # creating a duplicate (e.g. during bulk import).
            if is_company and vals.get('website'):
                existing = self._find_company_by_website(vals['website'])
                if existing:
                    results[index] = existing
                    continue

            # A contact's company is determined by its WEBSITE only. Even if the
            # import row maps a company column (parent_id), it is overridden so
            # placement is based on the website alone. If no company owns that
            # website yet, auto-create it (named from the company-name column,
            # else from the website domain) so the contact is always grouped
            # under the website's company.
            if not is_company and vals.get('website'):
                company = self._find_company_by_website(vals['website'])
                if not company:
                    company = self.create({
                        'name': vals.get('company_name') or self._company_name_from_website(vals['website']),
                        'is_company': True,
                        'website': vals['website'],
                    })
                vals['parent_id'] = company.id

            if not vals.get('user_id') and vals.get('parent_id'):
                parent = self.browse(vals['parent_id'])
                if parent.user_id:
                    vals['user_id'] = parent.user_id.id

            to_create.append((index, vals))

        if to_create:
            created = super().create([vals for _index, vals in to_create])
            for (index, _vals), record in zip(to_create, created):
                results[index] = record

        # Return a recordset preserving the original order of vals_list.
        result = self.browse()
        for record in results:
            result += record
        return result

    def write(self, vals):
        # Keep the stored website in the standard 'https://www.<domain>' form
        # whenever it is edited.
        if vals.get('website'):
            vals['website'] = self._standardize_website(vals['website'])
        res = super().write(vals)
        if 'user_id' in vals:
            companies = self.filtered('is_company')
            if companies:
                children = companies.mapped('child_ids').filtered(
                    lambda c: not c.is_company
                )
                # Option B (default): always overwrite child's salesperson with company's.
                # For Option A (preserve manual overrides), add: .filtered(lambda c: not c.user_id)
                if children:
                    children.write({'user_id': vals['user_id']})
        return res

