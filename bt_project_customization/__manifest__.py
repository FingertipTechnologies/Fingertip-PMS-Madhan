{
    'name': 'Project Customization',
    'version': '18.0.1.0.2',
    'description': 'Project Customization.',
    'category': 'Project',
    'author': 'Broadtech',
    'depends': ['project','hr_timesheet','sale_timesheet', 'ft_task_hours_tracker'],
    'data': [
        'security/ir.model.access.csv',
        'security/project_timesheet_group.xml',
        'views/project_project_views.xml',
        'views/project_milestone_views.xml',
        'views/project_task_views.xml',
        'views/module_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'bt_project_customization/static/src/js/task_stage_confirm.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
