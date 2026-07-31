"""Two data repairs the Sales dashboard depends on: Closed Date, and Lost stage.

LOST STAGE
==========
Odoo records a loss by archiving the opportunity and leaves ``stage_id`` alone,
so a lost deal keeps whichever stage it died in. The dashboard reads every
archived record as Lost, but a list view, an export or a pivot shows the raw
stage — which is why a dead deal appears under Discussion, Demo or Negotiation
and why those reports could not be reconciled with the dashboard by eye.

``write()`` below moves an opportunity into the Lost stage as it is archived,
and ``_ft_sync_lost_stage()`` repairs the ones archived before that existed.
Note this required relaxing two rules in bt_crm_customization (Lost left
QUALIFIED_PLUS_STAGES, and Next Action is no longer demanded on Lost): a deal
that has already ended cannot be asked for forward-looking qualification data,
and the constraints would otherwise have blocked the move outright.

CLOSED DATE
===========
Closed Date repair for opportunities that never got one.

Sales Closed and Opportunities Lost are dated by ``date_closed`` — the only
field that says when a deal actually ended (see models/sales_dashboard.py).
Odoo stamps it in ``crm.lead.write()`` when probability reaches 100 or when the
record is archived, so anything won or lost through the UI carries it.

Two populations do not:

* records imported straight into a Won stage — the import writes the stage in
  ``create()``, which never passes through that branch of ``write()``;
* records won or lost before an upgrade that introduced the stamping.

Those deals then existed in the database and in a CRM export while counting for
nothing on the dashboard, which is exactly the "card says 15, export says more"
mismatch. The fix is to fill the missing dates once, not to redefine "closed"
as "expected to close".

``date_last_stage_update`` is the best available answer to "when did this reach
its final stage"; ``write_date`` is the fallback when even that is absent. The
pass only ever fills a blank, never overwrites a real Closed Date, so running it
twice changes nothing.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Name of the stage lost opportunities are moved to, matched case-insensitively.
LOST_STAGE_NAME = 'lost'


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    @api.model
    def _ft_backfill_date_closed(self):
        """Stamp a Closed Date on won/lost opportunities missing one.

        Idempotent: only records with ``date_closed`` unset are touched.
        Returns the number of records repaired, so it is usable from a shell
        or a server action as well as from the upgrade hook.
        """
        leads = self.with_context(active_test=False).search([
            ('type', '=', 'opportunity'),
            ('date_closed', '=', False),
            '|',
            ('active', '=', False),                 # lost
            ('stage_id.is_won', '=', True),         # won
        ])
        for lead in leads:
            # Writing date_closed alone does not touch probability, active or
            # stage_id, so crm.lead.write() passes the value straight through
            # instead of recomputing (or clearing) it.
            lead.date_closed = lead.date_last_stage_update or lead.write_date
        if leads:
            _logger.info(
                'ft_sales_dashboard: backfilled Closed Date on %s opportunities',
                len(leads))
        return len(leads)

    # ------------------------------------------------------------------
    # Lost opportunities belong in the Lost stage
    # ------------------------------------------------------------------
    @api.model
    def _ft_lost_stage(self):
        """The stage lost opportunities are parked in, empty if none exists.

        Matched by name rather than by a flag because ``crm.stage`` has
        ``is_won`` but no ``is_lost`` counterpart — the same way
        bt_crm_customization identifies its Cold / Won stages. ``active_test``
        is off so an archived Lost stage is still found; parking a dead deal in
        an archived stage is better than leaving it in Discussion.
        """
        return self.env['crm.stage'].with_context(active_test=False).search(
            [('name', '=ilike', LOST_STAGE_NAME)], order='sequence, id', limit=1)

    def write(self, vals):
        """Archiving an opportunity also moves it into the Lost stage.

        Odoo records a loss by archiving (``action_set_lost`` -> ``active =
        False``) and deliberately leaves ``stage_id`` alone, so a lost deal keeps
        whichever stage it died in. The dashboard already compensates by reading
        every archived record as Lost, but a list view, an export or a pivot
        shows the raw stage — which is how a dead deal ends up displayed under
        Discussion, Demo or Negotiation and why those reports could not be
        verified against the dashboard.

        Only opportunities are moved, and only when the caller has not set a
        stage itself, so an explicit stage change always wins. The recordset is
        split rather than mutating ``vals`` for everyone, so archiving a mixed
        selection cannot drag leads or already-Lost records along with it.
        """
        if vals.get('active') is False and 'stage_id' not in vals:
            stage = self._ft_lost_stage()
            if stage:
                movable = self.filtered(
                    lambda l: l.type == 'opportunity' and l.stage_id != stage)
                if movable:
                    rest = self - movable
                    res = super(CrmLead, movable).write(
                        dict(vals, stage_id=stage.id))
                    if rest:
                        res = super(CrmLead, rest).write(vals) and res
                    return res
        return super().write(vals)

    @api.model
    def _ft_sync_lost_stage(self):
        """Move already-archived opportunities into the Lost stage.

        The write() hook above only catches losses from here on; the records
        archived before it existed still sit in their old stage. Idempotent —
        it only ever selects records that are NOT already in the Lost stage — so
        install and upgrade both running it is harmless.
        """
        stage = self._ft_lost_stage()
        if not stage:
            _logger.warning(
                'ft_sales_dashboard: no stage named "%s"; archived opportunities '
                'keep their original stage', LOST_STAGE_NAME)
            return 0
        leads = self.with_context(active_test=False).search([
            ('type', '=', 'opportunity'),
            ('active', '=', False),
            ('stage_id', '!=', stage.id),
        ])
        if leads:
            # probability MUST be in the write, and 0 is the correct value for a
            # lost deal anyway. crm.lead.write() ends a stage change into a
            # non-won stage with
            #     elif stage_updated and not stage_is_won and not 'probability' in vals:
            #         vals['date_closed'] = False
            # so moving these records on stage_id alone would silently clear the
            # Closed Date on every one of them — the exact field Sales Closed and
            # Opportunities Lost are measured on, which _ft_backfill_date_closed()
            # exists to populate. Naming probability skips that branch and the
            # existing Closed Dates survive.
            leads.write({'stage_id': stage.id, 'probability': 0})
            _logger.info(
                'ft_sales_dashboard: moved %s archived opportunities into the '
                '"%s" stage', len(leads), stage.name)
        return len(leads)


def post_init_hook(env):
    """Repair Closed Dates and Lost stages on install and on every upgrade."""
    env['crm.lead']._ft_backfill_date_closed()
    env['crm.lead']._ft_sync_lost_stage()
