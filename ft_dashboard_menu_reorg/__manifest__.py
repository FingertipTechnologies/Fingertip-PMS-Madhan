{
    'name': 'FT Dashboard Menu Reorganization',
    'version': '18.0.1.0.0',
    'category': 'Extra Tools',
    'summary': 'Moves each department dashboard menu from the standalone Dashboards app into its own module',
    'description': """
FT Dashboard Menu Reorganization
=================================
Reparents the existing department dashboard menu items — which by default
live under Odoo's standalone "Dashboards" app (spreadsheet_dashboard) — so
each one instead appears inside the app it belongs to:

* Project Dashboard  -> PMS (project.menu_main_pm)
* Sales Dashboard     -> CRM (crm.crm_menu_root)
* Marketing Dashboard -> Marketing (marketing_content.menu_marketing_root)
* HR Dashboard        -> General (general.menu_general_root)
* Finance Dashboard   -> Invoicing (account.menu_finance)

This module makes no changes to the original dashboard modules themselves;
it only overrides the `parent_id`, `name` and `sequence` of their existing
menu records, so it can be installed/uninstalled independently.
""",
    'author': 'Fingertip',
    'website': '',
    'depends': [
        'ft_project_dashboard',
        'ft_sales_dashboard',
        'ft_marketing_dashboard',
        'ft_hr_dashboard',
        'ft_finance_dashboard',
        'project',
        'crm',
        'marketing_content',
        'general',
        'account',
    ],
    'data': [
        'views/menu_reorganization.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
