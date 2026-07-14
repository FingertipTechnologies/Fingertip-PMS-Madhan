from odoo import models, fields, _


class Phase(models.Model):
    _name = 'ft.phase'
    _description = 'Training Phase'
    _order = 'sequence, id'

    name = fields.Char(string='Name', required=True)
    sequence = fields.Integer(string='Sequence', default=1)

    def name_get(self):
        result = []
        for rec in self:
            label = rec.name or _("Phase")
            result.append((rec.id, f"Phase {rec.sequence} - {label}"))
        return result
