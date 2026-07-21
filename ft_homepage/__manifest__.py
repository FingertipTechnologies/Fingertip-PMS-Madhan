# -*- coding: utf-8 -*-
{
    "name": "FT Homepage – App Access, Landing Page & Announcements",
    "version": "18.0.1.1.0",
    "category": "Productivity",
    "summary": "Role-based app icon visibility, default Homepage landing page, "
                "and Quote of the Day / Announcement widget on the Homepage.",
    "description": """
FT Homepage
===========
Implements 3 requirements on top of the Homepage (web_responsive Apps Menu grid):

1. App Icon Visibility by Role
   Restricts which app icons show on the Homepage grid using ir.ui.menu
   security groups, per the access matrix (see data/menu_access_data.xml).

2. Default Landing Page after Login
   Adds a system-wide setting (Settings > General Settings) that makes the
   Homepage (Apps Menu grid) the default landing page after login for all
   users, instead of Discuss / Invoicing. Built on top of web_responsive's
   `is_redirect_home` field on res.users.

3. Quote of the Day / Announcement Widget
   Adds a "Quote / Announcement" model (text, image or video, with
   contributor name) that is rendered below the app icons on the Homepage,
   with a decorative quote style for text and a marquee scroll animation.
""",
    "author": "Fingertip",
    "website": "",
    "license": "LGPL-3",
    "depends": [
        "base",
        "web",
        "mail",
        "web_responsive",
        "general",
        "project",
        "hr",
       
        "crm",
        "sale",
        "mass_mailing",
        "account",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/menu_access_data.xml",
        "data/apply_landing_page.xml",
        "views/quote_announcement_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "ft_homepage/static/src/homepage/quote_widget.scss",
            "ft_homepage/static/src/homepage/quote_widget.js",
            "ft_homepage/static/src/homepage/quote_widget.xml",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
