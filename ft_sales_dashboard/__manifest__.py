{
    'name': 'FT Sales Dashboard',
    'version': '18.0.1.0.0',
    'category': 'Sales/CRM',
    'summary': 'Executive Sales Dashboard — KPI cards & Chart.js analytics (OWL)',
    'description': """
FT Sales Dashboard
==================
A modern, executive-level Sales/CRM dashboard for management:
 * KPI cards (opportunities, pipeline value, conversion ratio, closed sales).
 * Analytical charts (pipeline by stage, sales funnel, trends).
 * Built with OWL components + Chart.js, drill-down to records.

Extracted from bt_crm_customization into its own standalone module.
""",
    'author': 'Fingertip',
    'website': '',
    'depends': [
        'crm',
        'spreadsheet_dashboard',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/sales_dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ft_sales_dashboard/static/src/scss/sales_dashboard.scss',
            'ft_sales_dashboard/static/src/js/kpi_card.js',
            'ft_sales_dashboard/static/src/js/chart_card.js',
            'ft_sales_dashboard/static/src/js/sales_dashboard.js',
            'ft_sales_dashboard/static/src/xml/sales_dashboard_templates.xml',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
