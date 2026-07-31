{
    'name': 'FT Task Hours Tracker',
    # Bumped off 18.0.0.0.0, where it had sat since the module was first added,
    # through every commit that introduced a new stored field. Odoo compares the
    # installed version against this one, so an unchanged version means a
    # database that already has the module never gains the new columns:
    # ft_project_stage_id (added in d7a9431 and referenced by the task list view)
    # has no column on any database that was not manually updated, and selecting
    # it raises UndefinedColumn. Bump this whenever a stored field is added here.
    'version': '18.0.0.0.1',
    'summary': 'project hours tracking',
    'category': 'Project',
    'author': 'Fingertip',
    'website': '',
    'depends': [
        'project',
        'hr_timesheet',
        'bt_project_customization',
        'qa_testapp',
        'ft_sprint_management',
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
