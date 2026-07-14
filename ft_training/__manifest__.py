{
    'name': 'Training',
    'version': '18.0.1.0.0',
    'category': 'Human Resources',
    'summary': 'Track daily trainee learning and a central training curriculum',
    'description': """
Training
========
A standalone app to track trainee learning:
 * Learning Trails — central curriculum of Learning Topics (Title, Domain, Description),
   maintained by Admins.
 * Today's Learning — daily learning entries created by Trainees (Learning Topic +
   rich-text Description). Uses the system Created Date, no manual date entry.

Supports evaluating trainee progress from a centralized record.
""",
    'author': 'Fingertip',
    'website': '',
    'depends': ['base', 'web', 'hr'],
    'data': [
        'security/training_security.xml',
        'security/ir.model.access.csv',
        'views/learning_topic_views.xml',
        'views/today_learning_views.xml',
        'views/trainee_review_views.xml',
        'views/assignment_views.xml',
        'views/evaluation_views.xml',
        'views/training_menus.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
