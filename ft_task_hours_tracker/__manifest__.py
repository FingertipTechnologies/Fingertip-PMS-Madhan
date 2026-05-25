{
    'name': 'FT Task Hours Tracker',
    'version': '18.0.0.0.0',
    'summary': 'project hours tracking',
    'category': 'Project',
    'author': 'Fingertip',
    'website': '',
    'depends': [
        'project',
        'hr_timesheet',
        'bt_project_customization',
        'qa_testapp',
    ],
    'data': [
        'views/project_task_views.xml',
        'views/project_project_views.xml',
        'views/res_config_settings_views.xml',
    ],
'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
