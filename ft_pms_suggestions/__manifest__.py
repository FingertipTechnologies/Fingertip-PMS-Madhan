# -*- coding: utf-8 -*-
{
    "name": "PMS Suggestions / Feedback",
    "version": "18.0.1.0.0",
    "category": "Productivity",
    "summary": "Employee suggestion box for PMS improvements, with approval "
                "workflow, lock-after-approval, and admin notifications.",
    "description": """

- Employees submit a PMS improvement suggestion with an auto-generated ID,
  a title, the module/area it relates to, and a rich-text description
  (supports pasted images) plus a normal attachment button (via chatter).
- "Suggested By" is auto-filled from the logged-in user.
- Status flow: Suggestion -> Approved -> Implemented.
- Once Approved, the suggestion becomes read-only for everyone. Admins get
  an "Unlock for Editing" button to override this when genuinely needed.
- On submission, an email/notification is sent to all Admin-access users
  .
""",
    "author": "Fingertip",
    "license": "LGPL-3",
    "depends": ["base", "mail", "general"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "views/pms_suggestion_category_views.xml",
        "views/pms_suggestion_views.xml",
    ],
    "installable": True,
    "application": False,
}
