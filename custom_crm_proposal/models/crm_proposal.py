from odoo import models, fields, api
from odoo.exceptions import ValidationError

class CrmProposal(models.Model):
    _name = 'crm.proposal'
    _description = 'Opportunity Proposal'

    name = fields.Char(string='Proposal Reference', required=True, copy=False, 
                       readonly=True, default='New')
    opportunity_id = fields.Many2one('crm.lead', string='Opportunity', ondelete='cascade')
    date_proposal = fields.Date(string='Proposal Date', default=fields.Date.context_today)
    description = fields.Text(string='Details')

    # Rich Text / HTML Sections
    project_overview = fields.Html(string='Project Overview - RTT', sanitize=True, strip_style=False)
    exclusions = fields.Html(string='Exclusions', sanitize=True, strip_style=False)
    project_deliverables = fields.Html(string='Project Deliverables - RTT', sanitize=True, strip_style=False)
    dependencies_client = fields.Html(string='Dependencies from Client', sanitize=True, strip_style=False)
    project_timeline_production = fields.Html(string='Project Timeline Production', sanitize=True, strip_style=False)
    approval_block = fields.Html(string='Approval & Sign-off', sanitize=True, strip_style=False)
     # Scope of Work with Rich Text support
    scope_of_work = fields.Html(
        string='Scope of Work',
        sanitize=True,
        strip_style=False,  # Important to keep colors/font sizes for PDF
        translate=False
    )

    cost_timeline_ids = fields.One2many(
        'crm.proposal.line', 
        'proposal_id', 
        string='Cost and Timeline'
    )
    gst_note = fields.Char(
        string='Note', 
        default='Note: The above costs are excluding GST',
        readonly=True
    )
    milestone_ids = fields.One2many(
        'crm.proposal.milestone', 
        'proposal_id', 
        string='Payment Milestones'
    )
    def _get_default_terms(self):
        return """
            1. Validity: This proposal is valid for 30 days.
            2. Payment: 50% advance, 50% upon completion.
            3. Taxes: All prices are exclusive of GST.
            4. Support: 3 months of post-launch support included.
        """

    terms_conditions = fields.Html(
        string='Terms & Conditions',
        default=_get_default_terms,
        sanitize=True,
        strip_style=False
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('crm.proposal') or 'New'
        return super(CrmProposal, self).create(vals_list)
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed')
    ], string='Status', default='draft', readonly=True, copy=False)

    def action_confirm(self):
        for record in self:
            # Generate the FTP sequence number upon confirmation if still 'New'
            if record.name == 'New':
                record.name = self.env['ir.sequence'].next_by_code('crm.proposal') or 'New'
            record.state = 'confirmed'

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'crm.proposal',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
        }

    def action_open_proposal(self):
        self.ensure_one()
        return {
            'name': self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'crm.proposal',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current', # This forces it into a new page, NOT a popup
        }
    def copy(self, default=None):
        default = dict(default or {})
        default.update({
            'state': 'draft',
            'name': 'New',
        })
        return super(CrmProposal, self).copy(default)

    def action_copy_proposal(self):
        self.ensure_one()
        new_record = self.copy()
        return {
            'name': 'New Proposal (Copy)',
            'type': 'ir.actions.act_window',
            'res_model': 'crm.proposal',
            'view_mode': 'form',
            'res_id': new_record.id,
            'target': 'current', # Opens in full page as requested
        }
    
    def _get_default_scope_of_work(self):
        return """
            <p>This section defines the complete and exhaustive list of features included in this project. Only features explicitly listed below are part of the agreed scope. Any feature not listed here, regardless of whether it was discussed during pre-sales conversations, is not part of this engagement. </p>
            """
    scope_of_work = fields.Html(
        string='Scope of Work',
        default=_get_default_scope_of_work,
        sanitize=True,
        strip_style=False
    )

    executive_summary = fields.Html(
        string='Executive Summary',
        sanitize=True,
        strip_style=False
    )

    @api.model
    def default_get(self, fields_list):
        res = super(CrmProposal, self).default_get(fields_list)
        
        # Fetch the active opportunity name dynamically
        active_id = self.env.context.get('default_opportunity_id') or self.env.context.get('active_id')
        opp_name = "The Client"
        
        if active_id:
            opportunity = self.env['crm.lead'].browse(active_id)
            if opportunity.exists():
                opp_name = opportunity.name

        # Construct the complete Executive Summary HTML content
        res['executive_summary'] = f"""
            <p><strong>{opp_name}</strong> seeks to implement a Salesforce-based CRM system to digitize and streamline their field sales operations, distributor management, and SAP integration — replacing the existing Field Assist platform. Fingertip Plus Technologies ("Fingertip") is pleased to submit this implementation proposal.</p>
            
            <h2 style="color: #005580;" >1.1 About Fingertip Plus Technologies</h2>
            <p>Fingertip Plus Technologies Pvt. Ltd. is a Salesforce consulting and implementation partner based in Bangalore, India. With 10+ years of Salesforce experience, we specialize in FMCG, distribution, and field sales automation solutions. Our consultative approach ensures that every implementation is tailored to the client's specific business processes.</p>
            
            <h2 style="color: #005580; " >1.2 Terminology</h2>
            <ul>
                <li><strong>Implementation partner:</strong> Fingertip Plus Technologies Pvt. Ltd. </li>
                <li><strong>Client :</strong> {opp_name}</li>
                <li><strong>SOW (Scope of Work):</strong> The set of features explicitly documented in this proposal.</li>
                <li><strong>BRD (Business Requirement Document):</strong> The detailed requirements document, signed off by both parties, that governs development.</li>
                <li><strong>UAT (User Acceptance Testing):</strong> Testing performed by Client's team to validate that deliverables match the signed BRD.</li>
                <li><strong>Change Request (CR):</strong> Any modification to the agreed scope, requiring separate estimation and written approval.</li>
                <li><strong>Figma:</strong> UI/UX design mockups shared for Client approval before development.</li>
                <li><strong>Hypercare:</strong> Post go-live support period for bug fixes and user guidance.</li>
            </ul>
        """

        # Prefill Project Overview
        # Construct the complete Project Overview HTML with the Table & Sub-sections
        res['project_overview'] = """
            <table class="table table-bordered m-0" style="width: 100%; border-collapse: collapse; border: 1px solid #dee2e6;">
                <thead>
                    <tr style="background-color: #005580; color: #ffffff;">
                        <th style="padding: 8px; width: 25%; border: 1px solid #dee2e6; color: #ffffff;">Parameter</th>
                        <th style="padding: 8px; width: 75%; border: 1px solid #dee2e6; color: #ffffff;">Details</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">SFA Users</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">900 (300 on-roll + 600 off-roll) — Single React Native Mobile App</td>
                    </tr>
                    <tr style="background-color: #f9f9f9;">
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">DMS Users</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">~300 Distributors (SS/DB/DB-M) — Salesforce Experience Cloud Portal</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Technology</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">Salesforce (Backend) + React Native with Salesforce Mobile SDK (App) + Experience Cloud (DMS)</td>
                    </tr>
                    <tr style="background-color: #f9f9f9;">
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Integrations</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">SAP (bi-directional), WhatsApp Business API, SMS Gateway (OTP), Google Maps API</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Project Type</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">Fixed Scope | Fixed Budget | Fixed Timeline</td>
                    </tr>
                    <tr style="background-color: #f9f9f9;">
                        <td style="padding: 14px 8px; font-weight: bold; border: 1px solid #dee2e6;">Budget</td>
                        <td style="padding: 14px 8px; border: 1px solid #dee2e6;">₹27,00,000 + GST (Twenty-Seven Lakhs Only) — All-Inclusive</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Timeline</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">SFA + DMS: 3 months post BRD sign-off | SAP Integration: post SFA/DMS | Overall: ~5 months</td>
                    </tr>
                </tbody>
            </table>
            
            <br/>
            <h2 style="color: #005580; margin-top: 7px;">2.1 System Architecture</h2>
            <ul style="list-style-type: square; padding-left: 20px; line-height: 1.6;">
                <li style="margin-bottom: 8px;">
                    <strong>A. Salesforce Backend &amp; Web App:</strong> All data, business logic, objects, workflows, dashboards, reports, approvals, SAP integration. Accessed by Admin/Back-Office/Management via web browser.
                </li>
                <li style="margin-bottom: 8px;">
                    <strong>B. React Native SFA Mobile App (Salesforce Mobile SDK):</strong> Field sales app for ALL 900 users. SmartStore (offline), SmartSync (auto-sync), GPS, camera, push notifications.
                </li>
                <li style="margin-bottom: 8px;">
                    <strong>C. DMS Portal (Experience Cloud):</strong> Web portal for ~300 distributors. Orders, GRN, invoicing, ledger, claims, analytics.
                </li>
            </ul>
        """

        # Prefill Exclusions
        res['exclusions'] = """
            <ul>
                <li>Data cleaning and records remediation of legacy systems.</li>
                <li>Any third-party software licensing fees outside Salesforce standard licenses.</li>
                <li>Custom mobile application development not specified in the functional scope.</li>
            </ul>
        """

        # Prefill Project Deliverables
        res['project_deliverables'] = """
            <table class="table table-bordered m-0" style="width: 100%; border-collapse: collapse; border: 1px solid #dee2e6; font-size: 13px;">
                <thead>
                    <tr style="background-color: #005580; color: #ffffff;">
                        <th style="padding: 8px; width: 8%; text-align: center; border: 1px solid #dee2e6; color: #ffffff;">#</th>
                        <th style="padding: 8px; width: 32%; border: 1px solid #dee2e6; color: #ffffff;">Deliverable</th>
                        <th style="padding: 8px; width: 60%; border: 1px solid #dee2e6; color: #ffffff;">Details</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td style="padding: 8px; text-align: center; border: 1px solid #dee2e6;">1</td>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Business Requirement Document (BRD)</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">Module-wise detailed requirements with process flows. Signed off by both parties.</td>
                    </tr>
                    <tr style="background-color: #f9f9f9;">
                        <td style="padding: 8px; text-align: center; border: 1px solid #dee2e6;">2</td>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Figma UI/UX Designs</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">All possible screen mockups for mobile app and web. Client sign-off required before development.</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; text-align: center; border: 1px solid #dee2e6;">3</td>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Salesforce Backend + Web App</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">Fully configured Salesforce org with all objects, workflows, approvals, dashboards as per BRD.</td>
                    </tr>
                    <tr style="background-color: #f9f9f9;">
                        <td style="padding: 8px; text-align: center; border: 1px solid #dee2e6;">4</td>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">React Native Mobile App</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">Android + iOS app published on Play Store and App Store.</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; text-align: center; border: 1px solid #dee2e6;">5</td>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">DMS Portal</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">Salesforce Experience Cloud portal for distributors.</td>
                    </tr>
                    <tr style="background-color: #f9f9f9;">
                        <td style="padding: 8px; text-align: center; border: 1px solid #dee2e6;">6</td>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">SAP Integration</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">Bi-directional API integration with all data flows as per scope.</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; text-align: center; border: 1px solid #dee2e6;">7</td>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">User Guide</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">End-user documentation(pdf) covering all modules for field executives, managers, and admin.</td>
                    </tr>
                    <tr style="background-color: #f9f9f9;">
                        <td style="padding: 8px; text-align: center; border: 1px solid #dee2e6;">8</td>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Technical Document</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">System architecture, data model, integration flows, API documentation for future reference.</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; text-align: center; border: 1px solid #dee2e6;">9</td>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Training</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">4 user training sessions (in-person) + 2 admin training sessions (virtual).</td>
                    </tr>
                    <tr style="background-color: #f9f9f9;">
                        <td style="padding: 8px; text-align: center; border: 1px solid #dee2e6;">10</td>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Source Code</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">Salesforce web + mobile app codebase shared with client after go-live and receipt of all payments.</td>
                    </tr>
                </tbody>
            </table>
        """

        # Injecting the styled Project Timeline table layout matching your reference image
        res['project_timeline_production'] = """
            <table class="table table-bordered m-0" style="width: 100%; border-collapse: collapse; border: 1px solid #dee2e6; font-size: 13px;">
                <thead>
                    <tr style="background-color: #005580; color: #ffffff;">
                        <th style="padding: 8px; width: 15%; border: 1px solid #dee2e6; color: #ffffff;">Period</th>
                        <th style="padding: 8px; width: 25%; border: 1px solid #dee2e6; color: #ffffff;">Phase</th>
                        <th style="padding: 8px; width: 60%; border: 1px solid #dee2e6; color: #ffffff;">Activities</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td style="padding: 8px; border: 1px solid #dee2e6;"></td>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Discovery &amp; BRD</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">Requirements gathering, process mapping, BRD preparation, Figma UI/UX design. BRD + Figma sign-off required from Mayora.</td>
                    </tr>
                    <tr style="background-color: #f9f9f9;">
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Week 1-8</td>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">SFA + DMS Development</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">Salesforce backend, React Native mobile app, DMS portal, MAP module, In-App Ticketing. All development in parallel.</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Week 7-9</td>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">SFA + DMS Testing</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">Fingertip QA team will do system testing and give sign-off.</td>
                    </tr>
                    <tr style="background-color: #f9f9f9;">
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Week 10</td>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">SFA + DMS UAT</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">SIT, UAT with Mayora team, bug fixes, regression. UAT sign-off required.</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Week 11</td>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Deployment</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">Production deployment</td>
                    </tr>
                    <tr style="background-color: #f9f9f9;">
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Week 12-14</td>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Go-Live + Training</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">Historical data upload, 4 user trainings (in-person), 2 admin trainings (virtual), phased rollout.</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Post Go-Live</td>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Hypercare</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">8 weeks hypercare support per release (see Section 9.7).</td>
                    </tr>
                    <tr style="background-color: #f9f9f9;">
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Week 14-17</td>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">SAP Integration</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">All SAP integration flows development, testing (APIs must be available from project start).</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Week 17-19</td>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Integration Testing</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">End-to-end testing, data migration, performance testing, UAT for integrations.</td>
                    </tr>
                    <tr style="background-color: #f9f9f9;">
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Week 20</td>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Integration-Live</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">SAP integration Production deployment</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Post Go-Live</td>
                        <td style="padding: 8px; font-weight: bold; border: 1px solid #dee2e6;">Hypercare</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">12 weeks hypercare support for SAP integration. (see Section 9.7)</td>
                    </tr>
                </tbody>
            </table>
            <br/>
            <p><strong>Note: SFA, DMS timeline of 3 months starts from BRD sign-off date, not from project kick-off.</strong></p>
        """

        # Prefill Dependencies
        res['dependencies_client'] = """
            <ul>
                <li>Timely provision of API sandboxes and documentation for the SAP instance.</li>
                <li>Availability of business stakeholders for core requirement validation workshops within 48 hours of notice.</li>
            </ul>
        """

        # Injecting the complete 15-part Terms & Conditions text structure
        res['terms_conditions'] = """
            <div class="content-block-wrapper",style="font-size: 13px; line-height: 1.6; text-align: justify;">
                <p><strong class="sub-clause"> Scope Definition &amp; Governance :</strong>
                This is a fixed-scope, fixed-budget project. Only features explicitly documented in Section 3 (Scope of Work) of this proposal are included. Development will commence only after Client sign-off on the Business Requirement Document (BRD) and Figma designs. The BRD, once signed, becomes the governing document for all development work. Any feature, functionality, or requirement not explicitly written in the BRD — regardless of whether it was discussed during pre-sales conversations, demonstrations, or meetings — is not part of this project scope. Each technology platform has its own capabilities and limitations. Features available in the previous system may work differently in Salesforce. The implementation will leverage Salesforce platform capabilities as per industry best practices. Any customization beyond standard platform capability will be evaluated and may require additional effort. During pre-sales discussions, various features and possibilities were explored to understand platform feasibility. Those discussions served as discovery — they do not constitute scope commitments. This signed proposal and BRD are the only documents that define the agreed scope.</p>

                <p><strong class="sub-clause"> Change Request Process :</strong>
                Any modification to the agreed scope — whether an addition, removal, or alteration of any feature — must be submitted as a formal Change Request (CR) in writing. Fingertip will evaluate the CR and provide an estimate of additional effort, cost, and timeline impact within 5 business days. No CR work will commence until both parties agree in writing on the revised scope, cost, and timeline. CRs during development or after go-live will be estimated separately at prevailing rates. Fingertip will continue performing work as per the original agreed scope during CR evaluation.</p>

                <p><strong class="sub-clause"> BRD &amp; Figma Sign-off :</strong>
                Fingertip will prepare a detailed BRD covering all modules with process flows, data models, and business rules. Fingertip will share all possible Figma UI/UX designs (mobile app + web) along with the BRD. Client must review and sign-off on both BRD and Figma within 5 business days of submission. If Client does not communicate acceptance or rejection within 5 business days, the BRD/Figma shall be deemed accepted. Any changes requested after BRD/Figma sign-off will be treated as Change Requests. Fingertip requires full support from Mayora's business teams during BRD discussions to ensure completeness and clarity.</p>

                <p><strong class="sub-clause"> UAT Process :</strong>
                UAT is to verify that deliverables match the signed BRD. It is not a phase for new requirements or design changes. During UAT, only bug fixes and cosmetic adjustments will be made. Changes affecting architecture or design require a CR. Client must provide a proper UAT team (minimum 3-5 members) with structured test execution. UAT feedback must be documented and submitted in the provided format. Verbal feedback will not be actioned. Client must complete UAT and provide sign-off within 10 business days of UAT environment handover. If UAT sign-off is not received within 10 business days and no documented rejection is provided, the deliverables shall be deemed accepted.</p>

                <p><strong class="sub-clause"> Data Migration :</strong>
                Data extraction and cleaning from the existing system is the responsibility of the Client. Fingertip will provide Salesforce-specific CSV/Excel templates. Client must populate data in the provided format. Fingertip will upload the data and perform validation. Any data quality issues will be reported for Client resolution. 2-year historical data migration is included. Older data is excluded.</p>

                <p><strong class="sub-clause"> Training :</strong>
                4 user training sessions (in-person) covering SFA, DMS, and mobile app for field executives and managers. 2 admin training sessions (virtual) covering system administration, configuration, and reports. Client will identify training audience and provide training infrastructure (venue, projector, devices). Additional training sessions beyond the above 6 sessions will be charged separately.</p>

                <p><strong class="sub-clause"> Hypercare Support :</strong>
                12 weeks of hypercare support from go-live date of each module/release. If the project has multiple releases, each release will have its own 12-week hypercare period. Hypercare includes: bug fixes for agreed BRD scope, user guidance, and addressing any items missed in the agreed BRD. Hypercare does NOT include: new features, enhancements, changes to existing functionality, or items outside the BRD. Support is available during business hours (10 AM – 7 PM IST, Monday to Friday). Critical production issues will be addressed on priority. Hypercare period can be extended at additional cost if required by Client.</p>

                <p><strong class="sub-clause"> Warranty :</strong>
                1-year warranty from the date of final project sign-off. Warranty covers: errors/bugs in the existing delivered system as per the signed BRD. If any functionality documented in the BRD stops working due to a defect in Fingertip's implementation, it will be fixed at no additional cost. Warranty does NOT cover: new features, enhancements, Salesforce platform changes/upgrades that affect functionality, third-party API changes, or any scope not documented in the BRD. To ensure warranty coverage, Client must ensure all desired features are explicitly documented in the BRD. Features not written in the BRD cannot be covered under warranty.</p>

                <p><strong class="sub-clause"> Integration Dependencies :</strong>
                All third-party APIs (SAP, WhatsApp, SMS, Google Maps) must be provided before project start, as the system architecture depends on these APIs. Any API provided by a third party will be validated using Postman. If an API works in Postman, it is considered a working API. If any third-party API fails, changes, or becomes unavailable, Fingertip is not responsible for the resulting system impact. SAP integration development will begin after SFA and DMS are completed, but API documentation and sandbox access must be available from Day 1.</p>

                <p><strong class="sub-clause"> Source Code &amp; IP :</strong>
                Salesforce web application and mobile app codebase will be shared with Client after go-live and receipt of all payments. Fingertip retains the right to use generic components, frameworks, and methodologies developed during this project in other engagements.</p>

                <p><strong class="sub-clause"> Communication :</strong>
                All official communication must be via email. Phone calls and meetings are for convenience only. In case of any dispute, only written email communication will be considered as the official record. Weekly status meetings (1 hour) will be conducted throughout the project.</p>

                <p><strong class="sub-clause"> Payment Terms :</strong>
                Upon receipt of an invoice, the Client must provide written email confirmation within 24 hours, acknowledging receipt and confirming that payment will be processed within the 7-day window. Payments must be made within 7 days of invoice receipt. Delayed payments beyond 7 days may result in a project pause. Timeline extensions due to payment delays are not Fingertip's responsibility. The project schedule starts only after agreement signing and advance payment receipt.</p>

                <p><strong class="sub-clause"> Project Schedule Commitment :</strong>
                Any delay attributed to the Client (late BRD sign-off, delayed API access, delayed UAT, delayed payments, delayed data, delayed responses) will extend the project timeline proportionally. Any delay due to third-party vendor services (SAP, WhatsApp, SMS, Google Maps) is not Fingertip's responsibility. Fingertip will provide weekly status updates on progress, risks, and dependencies.</p>

                <p><strong class="sub-clause"> General :</strong>
                Working hours: 10:00 AM to 7:00 PM IST, Monday to Friday. Non-hire/non-poach: Client agrees not to hire any Fingertip employee during the project and for 12 months after completion. Conflict resolution: Any disputes will be addressed under Bangalore jurisdiction. This proposal is valid for 30 days from the date of submission.</p>

                <p><strong class="sub-clause"> Tenure and Termination :</strong>
                This Agreement shall be effective for a tenure of 12 months starting from the Effective Date, unless terminated by clauses mentioned in this agreement. Mayora India may terminate this agreement for a justified reason which shall include service failure, data security incidents, regulatory non-compliance etc., on 30 days’ notice to Fingertip. Fingertip may terminate this agreement by delivering 30 days written notice of the termination to Mayora India on failure to pay undisputed invoices beyond 15 days on three occasions.</p>
            </div>
        """

        # Get dynamic client company name from opportunity context
        active_id = self.env.context.get('default_opportunity_id') or self.env.context.get('active_id')
        opp_name = "Mayora India Pvt. Ltd."
        if active_id:
            opportunity = self.env['crm.lead'].browse(active_id)
            if opportunity.exists():
                opp_name = opportunity.name

        # Construct the signature tables matching your image layout
        res['approval_block'] = f"""
            <p>Signature and return of this section indicates approval to proceed. This signed document serves as the Purchase Order.</p>
            <br/>
            
            <table class="table table-bordered" style="width: 100%; border-collapse: collapse; border: 1px solid #dee2e6; font-size: 13px; margin-bottom: 20px;">
                <thead>
                    <tr style="background-color: #005580; color: #ffffff;">
                        <th style="padding: 8px; width: 50%; border: 1px solid #dee2e6; color: #ffffff;">For Fingertip Plus Technologies</th>
                        <th style="padding: 8px; width: 50%; border: 1px solid #dee2e6; color: #ffffff;">For {opp_name}</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td style="padding: 8px; border: 1px solid #dee2e6;"><strong>Name:</strong> Shebin Mathew</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;"><strong>Name:</strong> </td>
                    </tr>
                    <tr style="background-color: #f9f9f9;">
                        <td style="padding: 8px; border: 1px solid #dee2e6;"><strong>Designation:</strong> Director</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;"><strong>Designation:</strong> </td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; border: 1px solid #dee2e6;"><strong>Date:</strong> </td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;"><strong>Date:</strong> </td>
                    </tr>
                </tbody>
                <tbody>
                    <tr>
                        <td style="width: 50%; padding: 40px 15px 15px 15px; border: 1px solid #dee2e6; vertical-align: bottom; background-color: #fafafa; color: #777; border-style: dashed;">
                            <strong>Signature &amp; Company Seal:</strong>
                        </td>
                        <td style="width: 50%; padding: 40px 15px 15px 15px; border: 1px solid #dee2e6; vertical-align: bottom; color: #777; border-style: dashed;">
                            <strong>Signature:</strong>
                        </td>
                    </tr>
                </tbody>
            </table>
        """
        return res

class CrmProposalLine(models.Model):
    _name = 'crm.proposal.line'
    _description = 'Proposal Cost Line'

    proposal_id = fields.Many2one('crm.proposal', ondelete='cascade')
    release = fields.Char(string='Release', required=True)
    duration = fields.Char(string='Duration')
    cost = fields.Float(string='Cost')

class CrmProposalMilestone(models.Model):
    _name = 'crm.proposal.milestone'
    _description = 'Proposal Payment Milestone'

    proposal_id = fields.Many2one('crm.proposal', ondelete='cascade')
    milestone_text = fields.Char(string='Milestone', required=True)
    percentage = fields.Integer(string='Percentage (%)')
    amount = fields.Float(string='Amount', currency_field='currency_id')
    # amount = fields.Monetary(string='Amount', currency_field='currency_id')

    @api.constrains('percentage')
    def _check_percentage(self):
        for record in self:
            if record.percentage <= 0 or record.percentage > 99:
                raise ValidationError("Percentage must be a 1 or 2-digit number (1-99).")