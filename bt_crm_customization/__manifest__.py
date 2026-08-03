{
    'name': 'CRM Customization',
    'version': '18.0.1.1.0',
    'category': 'Contacts',
    'summary': 'Contact Customization',
    'author': 'Broadtech',
    'depends': ['base','crm','sale_crm'],
    'data': [
        'security/ir.model.access.csv',
        'views/crm_lead_views.xml',
        'views/features_views.xml',
        'views/technology_views.xml',
        'views/campaign_views.xml',
        'views/crm_menu_overrides.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
