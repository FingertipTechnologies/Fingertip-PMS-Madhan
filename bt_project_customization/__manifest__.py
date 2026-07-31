{
    'name': 'Project Customization',
    # Bumped for the 18.0.1.0.3 migration, which backfills ft_completion_date
    # for stages that are final by NAME rather than by the Kanban fold flag.
    # Changing a stored compute's body does not make Odoo recompute it, so
    # without this bump the migration never runs and every delivery figure stays
    # at zero on databases that already have the module installed.
    'version': '18.0.1.0.3',
    'description': 'Project Customization.',
    'category': 'Project',
    'author': 'Broadtech',
    'depends': ['project','hr_timesheet','sale_timesheet'],
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
