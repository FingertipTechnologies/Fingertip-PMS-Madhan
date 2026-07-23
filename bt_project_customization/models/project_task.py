from datetime import datetime

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

# Minimum number of characters required in a task title.
TASK_TITLE_MIN_LEN = 20

# Job positions (hr.job) allowed to create tasks. Matched on the lower-cased
# job name, mirroring the classification used elsewhere in the PMS.
TASK_CREATE_JOBS = {
    'technical lead',
    'project manager',
    'project coordinator',
    'project cordinator',   # legacy typo present in source data
}


class ProjectTask(models.Model):
    _inherit = 'project.task'

    estimated = fields.Float(string='Estimated')
    actual = fields.Float(string='Actual')
    ft_reopen_count = fields.Integer(
        string='Times Reopened',
        default=0,
        readonly=True,
        copy=False,
        tracking=True,
        help="How many times this task was moved back out of a Completed "
             "(folded) stage after having reached one. Drives the Rework Rate. "
             "Counted from the day this feature was installed onwards, so tasks "
             "reopened before then read 0.",
    )
    module_id = fields.Many2one('cus.module',string="Module",required=True)
    wc_id = fields.Char(string='Wc Id')
    task_type = fields.Selection([
        ('user_story', 'User Story'),
        ('internal_call', 'Internal Call'),
        ('external_call', 'External Call'),
    ], string='Task Type', default='user_story', required=True)

    @api.model_create_multi
    def create(self, vals_list):
        # Only a Technical Lead, Project Manager or Project Coordinator may
        # create tasks. Superuser and system administrators bypass the check so
        # data imports, automation and mail-to-task keep working.
        self._check_task_create_permission()
        return super().create(vals_list)

    def write(self, vals):
        # Count reopens: a task leaving a folded (Completed) stage for an open
        # one is rework. Snapshot which records were folded BEFORE the super()
        # call, because stage_id is what we are about to change.
        if 'stage_id' not in vals:
            return super().write(vals)
        was_folded = {t.id: t.stage_id.fold for t in self}
        res = super().write(vals)
        reopened = self.filtered(
            lambda t: was_folded.get(t.id) and not t.stage_id.fold
        )
        for task in reopened:
            # sudo: the counter is readonly to users, and whoever drags the card
            # back may not have write access to a field they never edit directly.
            task.sudo().ft_reopen_count = task.ft_reopen_count + 1
        return res

    def _check_task_create_permission(self):
        if self.env.su or self.env.user.has_group('base.group_system'):
            return
        employee = self.env.user.employee_id
        job_name = (employee.job_id.name or '').strip().lower() if employee else ''
        if job_name not in TASK_CREATE_JOBS:
            raise UserError(_(
                "You are not allowed to create tasks. Only a Technical Lead, "
                "Project Manager or Project Coordinator can create tasks."
            ))

    @api.constrains('name')
    def _check_task_title_length(self):
        # #2 - Task title must be at least TASK_TITLE_MIN_LEN characters.
        for task in self:
            if task.name and len(task.name.strip()) < TASK_TITLE_MIN_LEN:
                raise ValidationError(_(
                    "Task title must be at least %s characters long."
                ) % TASK_TITLE_MIN_LEN)

    # ------------------------------------------------------------------
    # On-Time Delivery
    #
    # THE single definition of "delivered" and "on time" for the whole PMS.
    # The project fields (project.project) and the dashboard both call these,
    # so an all-time figure on a project and a date-filtered figure on the
    # dashboard can never disagree about what they are counting.
    # ------------------------------------------------------------------
    @api.model
    def _ft_delivery_domain(self, extra=None, date_from=None, date_to=None):
        """Domain for DELIVERED tasks.

        Delivered = sits in a folded stage (Completed) and carries a date_end.
        Odoo stamps date_end automatically on entering a folded stage and clears
        it on leaving, so it is the completion date; a task reopened and closed
        again counts by its latest completion.

        Keyed off the STAGE, not `state`. Stages do not set state in Odoo 18
        (see the note in views/project_task_views.xml), so counting state
        '1_done' would miss almost everything this DB actually completes.

        Cancelled work is excluded: "Cancelled" is a folded stage in some stage
        sets, and a cancelled task is not a delivery. `state` is only ever set to
        '1_canceled' deliberately, so it is safe as an exclusion even though it
        is unreliable as an inclusion.

        The date range filters on date_end — i.e. what was DELIVERED in the
        period, not what was created in it.
        """
        dom = [
            ('stage_id.fold', '=', True),
            ('state', '!=', '1_canceled'),
            ('date_end', '!=', False),
        ]
        if date_from:
            dom.append(('date_end', '>=', str(date_from)))
        if date_to:
            # date_end is a Datetime; span the whole closing day.
            dom.append(('date_end', '<=', str(date_to) + ' 23:59:59'))
        return dom + (extra or [])

    @api.model
    def _ft_local_date(self, value):
        """A stored UTC value as a calendar date in the reader's timezone.

        Both ``date_end`` and ``date_deadline`` are Datetimes held in UTC, so
        taking ``.date()`` straight off them would bucket work by the UTC day.
        For anything finished late in the local evening that is the WRONG day
        (20:00 UTC is already tomorrow in IST), which would mark on-time work
        late. Converting first puts both sides on the user's calendar.
        """
        if not value:
            return None
        if isinstance(value, datetime):
            return fields.Datetime.context_timestamp(self, value).date()
        return value

    @api.model
    def _ft_on_time_aggregate(self, tasks):
        """Aggregate a recordset of DELIVERED tasks into on-time figures.

        Tasks with no deadline cannot be judged, so they are excluded from the
        denominator and reported separately as ``no_deadline`` — counting them
        as on-time would hand a perfect score to any project that simply never
        sets deadlines.

        On time is judged by CALENDAR DAY, not to the minute. ``date_deadline``
        is a Datetime, so a deadline entered as a day is stored carrying a
        time-of-day; comparing the raw timestamps made a task finished at 13:12
        on its own due date "late" against a 13:00 stamp nobody chose. A
        deadline of the 23rd means end of the 23rd, so any completion on that
        date counts as on time.

        ``rate`` is None (not 0.0) when nothing measurable was delivered, so the
        UI shows "N/A" instead of a 0% that reads as a failure.
        """
        completed = len(tasks)
        measurable = on_time = 0
        for task in tasks:
            if not task.date_deadline:
                continue
            measurable += 1
            if self._ft_local_date(task.date_end) <= self._ft_local_date(task.date_deadline):
                on_time += 1
        return {
            'completed': completed,
            'measurable': measurable,
            'no_deadline': completed - measurable,
            'on_time': on_time,
            'late': measurable - on_time,
            'rate': round(on_time / measurable * 100, 2) if measurable else None,
        }

    @api.model
    def _ft_efficiency_aggregate(self, tasks):
        """Delivery Efficiency for a recordset of DELIVERED tasks.

        (Estimated / Actual) x 100. Target 90-110%: under 90 means the work took
        materially longer than estimated, over 110 means the estimate was padded.

        Only tasks carrying BOTH an estimate and logged time are counted. A task
        estimated at 8h with no timesheet would otherwise divide by zero, and a
        task with time logged but no estimate would drag the ratio toward zero
        while saying nothing about estimation quality. ``unestimated`` reports
        how much work was skipped, so a flattering ratio drawn from three tasks
        out of two hundred is visible rather than trusted.

        Estimated is the custom ``estimated`` field, NOT core ``allocated_hours``.
        ft_task_hours_tracker hides the core Allocated Time block from the task
        form, so ``allocated_hours`` is unreachable in this workflow and reading
        it made the whole metric permanently unmeasurable. ``estimated`` is the
        field the task form actually exposes. Actual stays ``effective_hours``
        (the stored sum of timesheet lines).
        """
        measurable = tasks.filtered(
            lambda t: t.estimated > 0 and t.effective_hours > 0
        )
        estimated = sum(measurable.mapped('estimated'))
        actual = sum(measurable.mapped('effective_hours'))
        return {
            'estimated_hours': round(estimated, 2),
            'actual_hours': round(actual, 2),
            'measurable': len(measurable),
            'unestimated': len(tasks) - len(measurable),
            # None, not 0.0, when nothing is measurable: 0% efficiency reads as
            # catastrophic, while the truth is that nobody estimated anything.
            'rate': round(estimated / actual * 100, 2) if actual else None,
        }

    @api.model
    def _ft_rework_aggregate(self, tasks):
        """Rework Rate for a recordset of DELIVERED tasks.

        (Tasks reopened / Total delivered) x 100. Target: 10% or below.

        Counts TASKS that were reopened at least once, not total reopen events,
        so one task bounced five times cannot push the rate above 100%.
        """
        completed = len(tasks)
        reworked = len(tasks.filtered(lambda t: t.ft_reopen_count > 0))
        return {
            'completed': completed,
            'reworked': reworked,
            'rate': round(reworked / completed * 100, 2) if completed else None,
        }

    @api.model
    def _ft_open_domain(self, extra=None):
        """Domain for OPEN tasks — the complement of ``_ft_delivery_domain``.

        Open = not in a folded stage, i.e. still somewhere in Planned / Working /
        Testing. Keyed off the stage for the same reason delivery is: stages do
        not set `state`, so "not in a closed state" would call almost everything
        open, including finished work.
        """
        return [('stage_id.fold', '=', False)] + (extra or [])

    @api.model
    def _ft_overdue_open_domain(self, extra=None):
        """Domain for open tasks already past their deadline.

        The companion to the on-time rate, and the reason to trust it. The rate
        only looks at work that finished, so a task six months late and still
        open never appears in it — a team could score 100% by never closing its
        late work. This is what stops that hiding. It is a snapshot of now, so
        it is deliberately NOT filtered by the report's date range.
        """
        return self._ft_open_domain([
            ('date_deadline', '!=', False),
            ('date_deadline', '<', fields.Datetime.now()),
        ] + (extra or []))

    @api.model
    def _ft_overdue_open_count(self, extra=None):
        """Count of open, past-deadline tasks. See ``_ft_overdue_open_domain``."""
        return self.search_count(self._ft_overdue_open_domain(extra))

    @api.model
    def _ft_delivery_kpis(self, tasks):
        """All three delivery KPIs for one recordset of DELIVERED tasks.

        One place to add a fourth. Efficiency and rework keys are prefixed so
        they cannot collide with the on-time keys they are merged into.
        """
        stats = self._ft_on_time_aggregate(tasks)
        efficiency = self._ft_efficiency_aggregate(tasks)
        rework = self._ft_rework_aggregate(tasks)
        stats.update({
            'efficiency_rate': efficiency['rate'],
            'estimated_hours': efficiency['estimated_hours'],
            'actual_hours': efficiency['actual_hours'],
            'unestimated': efficiency['unestimated'],
            'rework_rate': rework['rate'],
            'reworked': rework['reworked'],
        })
        return stats

    @api.model
    def _ft_on_time_stats(self, extra=None, date_from=None, date_to=None):
        """All delivery KPIs for any scope. See ``_ft_delivery_domain``."""
        tasks = self.search(self._ft_delivery_domain(extra, date_from, date_to))
        stats = self._ft_delivery_kpis(tasks)
        stats['overdue_open'] = self._ft_overdue_open_count(extra)
        return stats

    @api.model
    def _ft_on_time_stats_by_project(self, project_ids, date_from=None, date_to=None):
        """``{project_id: stats}`` — one search for the whole set, not one each."""
        tasks = self.search(self._ft_delivery_domain(
            [('project_id', 'in', list(project_ids))], date_from, date_to))
        # Group ids and browse once per project: repeatedly unioning recordsets
        # (recs |= task) rebuilds the set on every step.
        ids_by_project = {}
        for task in tasks:
            ids_by_project.setdefault(task.project_id.id, []).append(task.id)
        return {
            pid: self._ft_delivery_kpis(self.browse(ids))
            for pid, ids in ids_by_project.items()
        }

    @api.model
    def _ft_overdue_open_count_by_project(self, project_ids):
        """``{project_id: count}`` of open, past-deadline tasks. One query."""
        groups = self.read_group(
            self._ft_overdue_open_domain([('project_id', 'in', list(project_ids))]),
            ['id'], ['project_id'], lazy=False,
        )
        return {
            g['project_id'][0]: g['__count']
            for g in groups if g.get('project_id')
        }
