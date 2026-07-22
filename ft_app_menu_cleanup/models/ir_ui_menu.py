from odoo import api, models


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    # Root (top-level / App Switcher) menu names that must be hidden for
    # EVERY user on this instance, regardless of group. Matched by name
    # instead of external ID, since the exact XML ID for these stock
    # Odoo apps can differ between versions/editions, and a name search
    # simply finds nothing (no error) if the app isn't installed at all.
    _FT_APPS_TO_REMOVE = [
        'Discuss',
        'Calendar',
        'Sales',
        'Website',
        'eLearning',
        'Email Marketing',
        'Helpdesk',
        'Timesheets',
        'Employees',
        'Link Tracker',
    ]

    @api.model
    def ft_cleanup_unwanted_apps(self):
        """Hide app icons that are not part of the approved app list.

        Safe to run repeatedly (idempotent) - called on every install/
        update of ft_app_menu_cleanup via a <function> data call.
        """
        root_menus = self.search([
            ('parent_id', '=', False),
            ('name', 'in', self._FT_APPS_TO_REMOVE),
        ])
        if root_menus:
            root_menus.write({'active': False})
        return True
