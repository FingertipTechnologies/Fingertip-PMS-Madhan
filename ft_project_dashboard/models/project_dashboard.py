import logging
from datetime import datetime, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Map hr.job (position) names -> role bucket. Mirrors the classification used by
# ft_task_hours_tracker so the dashboard counts roles the same way the rest of
# the PMS does. Matching is done on the lower-cased job name.
ROLE_BUCKETS = {
    'software developer': 'dev',
    'technical lead': 'dev',
    'software tester': 'qa',
    'testing lead': 'qa',
    'project manager': 'pm',
    'project cordinator': 'pm',   # legacy typo present in source data
    'project coordinator': 'pm',
    'business analyst': 'ba',
}

# Project statuses considered "active" (i.e. not finished). 'closed' is the only
# terminal status in bt_project_customization; everything else is in-flight.
CLOSED_STATUSES = ('closed',)

# A consistent, professional palette reused across charts.
PALETTE = [
    '#4F46E5', '#06B6D4', '#10B981', '#F59E0B', '#EF4444',
    '#8B5CF6', '#EC4899', '#14B8A6', '#F97316', '#3B82F6',
    '#84CC16', '#A855F7',
]


class FtProjectDashboard(models.TransientModel):
    _name = 'ft.project.dashboard'
    _description = 'FT Project Dashboard data provider'

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _ts_domain(self, date_from, date_to):
        """Domain for timesheet lines (account.analytic.line) within range."""
        domain = [('project_id', '!=', False)]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        return domain

    def _role_employee_ids(self):
        """Active-employee ids grouped by role bucket (via job position).

        Returns the ids, not just a count, so a KPI card can open exactly the
        employees behind its number — the drill-down can't drift from the count
        because both come from this one classification.
        """
        buckets = {'dev': [], 'qa': [], 'pm': [], 'ba': [], 'trainee': [], 'other': []}
        for emp in self.env['hr.employee'].search_read(
                [('active', '=', True)], ['job_id']):
            job = emp.get('job_id')
            name = (job[1] if job else '').strip().lower()
            if name.startswith('trainee'):
                buckets['trainee'].append(emp['id'])
            else:
                buckets[ROLE_BUCKETS.get(name, 'other')].append(emp['id'])
        return buckets

    def _role_counts(self):
        """Count active employees per role bucket via their job position."""
        return {k: len(v) for k, v in self._role_employee_ids().items()}

    @staticmethod
    def _jsonify_domain(domain):
        """Make a domain safe to send to the client.

        Server domains can carry a live ``datetime`` (the overdue cutoff is
        ``now()``); that is not JSON-serialisable, so stamp it to a string while
        leaving every other leaf untouched.
        """
        out = []
        for leaf in domain:
            if isinstance(leaf, (list, tuple)) and len(leaf) == 3:
                field, op, value = leaf
                if isinstance(value, datetime):
                    value = fields.Datetime.to_string(value)
                out.append((field, op, value))
            else:
                out.append(leaf)
        return out

    # ------------------------------------------------------------------
    # Public RPC entry point
    # ------------------------------------------------------------------
    @api.model
    def get_dashboard_data(self, date_from=None, date_to=None):
        """Return all KPI values and chart datasets for the dashboard.

        :param date_from/date_to: 'YYYY-MM-DD' strings (inclusive) or False.
        """
        return {
            'kpis': self._compute_kpis(date_from, date_to),
            'tables': {
                'project_status': self._table_project_status(date_from, date_to),
                'resource_status': self._table_resource_status(date_from, date_to),
                'delivery': self._table_delivery(date_from, date_to),
            },
            'charts': {
                'project_hours': self._chart_project_hours(date_from, date_to),
                'billable': self._chart_billable(date_from, date_to),
                'team_composition': self._chart_team_composition(),
                'progress_trend': self._chart_progress_trend(date_from, date_to),
            },
        }

    @api.model
    def get_resource_status(self, date_from=None, date_to=None):
        """Just the Resource Status rows, for that table's own date range.

        The table carries its own Start/End pickers. Filtering the already
        fetched rows in the browser could only ever hide rows — Hours Spent was
        still whichever period the top filter asked for, so the dates changed
        which rows showed without changing the numbers in them. Recomputing
        server-side is the only way those columns can answer the dates picked.
        """
        return self._table_resource_status(date_from or None, date_to or None)

    # ------------------------------------------------------------------
    # KPI cards
    # ------------------------------------------------------------------
    def _compute_kpis(self, date_from, date_to):
        Project = self.env['project.project']
        AAL = self.env['account.analytic.line']
        Task = self.env['project.task']

        active_projects = Project.search_count([
            ('active', '=', True), ('status', 'not in', CLOSED_STATUSES),
        ])

        ts_domain = self._ts_domain(date_from, date_to)
        spent = sum(g['unit_amount'] for g in AAL.read_group(
            ts_domain, ['unit_amount:sum'], []) if g.get('unit_amount'))

        billable = sum(g['unit_amount'] for g in AAL.read_group(
            ts_domain + [('project_id.allow_billable', '=', True)],
            ['unit_amount:sum'], []) if g.get('unit_amount'))

        estimated = sum(g['estimated'] for g in Task.read_group(
            [('project_id', '!=', False)], ['estimated:sum'], [])
            if g.get('estimated'))

        role_ids = self._role_employee_ids()
        roles = {k: len(v) for k, v in role_ids.items()}

        # On-time delivery for the selected period. The maths lives on
        # project.task so this and the project.project fields can never disagree
        # about what "delivered" or "on time" means.
        delivery = Task._ft_on_time_stats(date_from=date_from, date_to=date_to)

        # Drill-down domains, built from the SAME queries as the numbers above so
        # the list a card opens always holds exactly the count it shows. Cards
        # backed by a sum (hours) or by nothing (N/A) are absent here on purpose.
        emp_action = lambda ids, name: {
            'res_model': 'hr.employee', 'name': name,
            'domain': [('id', 'in', ids)],
        }
        delivery_domain = Task._ft_delivery_domain(date_from=date_from, date_to=date_to)
        actions = {
            'developers': emp_action(role_ids['dev'], 'Developers'),
            'testers': emp_action(role_ids['qa'], 'Testers'),
            'trainees': emp_action(role_ids['trainee'], 'Trainees'),
            'project_managers': emp_action(role_ids['pm'], 'Project Managers'),
            'tasks_delivered': {
                'res_model': 'project.task', 'name': 'Tasks Delivered',
                'domain': delivery_domain,
            },
            # The % is measured only over delivered tasks that HAVE a deadline,
            # so its drill-down is exactly that denominator.
            'on_time_delivery': {
                'res_model': 'project.task', 'name': 'Delivered (with deadline)',
                'domain': delivery_domain + [('date_deadline', '!=', False)],
            },
            'overdue_open_tasks': {
                'res_model': 'project.task', 'name': 'Open & Overdue',
                'domain': self._jsonify_domain(Task._ft_overdue_open_domain()),
            },
        }

        return {
            'active_projects': active_projects,
            'hours_spent': round(spent, 2),
            'billable_hours': round(billable, 2),
            'developers': roles['dev'],
            'testers': roles['qa'],
            # Counted separately from Developers/Testers: trainees are detected
            # by a job position starting with "trainee", so they are never
            # folded into a delivery role bucket.
            'trainees': roles['trainee'],
            'project_managers': roles['pm'],
            'hours_estimated': round(estimated, 2),
            'hours_remaining': round(estimated - spent, 2),
            # None (not 0) when nothing measurable was delivered in the period,
            # so the card reads "N/A" rather than a 0% that looks like failure.
            'on_time_delivery': delivery['rate'],
            'tasks_delivered': delivery['completed'],
            # Snapshot of now, deliberately not period-filtered: it is the check
            # on the percentage above, which only ever counts work that finished.
            'overdue_open_tasks': delivery['overdue_open'],
            # No capacity/planning model installed yet -> shown as "N/A".
            'resource_need': None,
            'available_resources': None,
            # Per-card drill-down targets (see `actions` above).
            'actions': actions,
        }

    # ------------------------------------------------------------------
    # Charts
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Tables (full-width)
    # ------------------------------------------------------------------
    @staticmethod
    def _iso_date(d):
        """Return an ISO 'YYYY-MM-DD' string (sortable), or '' when unset.

        The client formats these for display; ISO strings also sort
        chronologically as plain strings, which the table sorter relies on.
        """
        return fields.Date.to_string(d) if d else ''

    @staticmethod
    def _overlaps_period(start, end, date_from, date_to):
        """True when [start, end] overlaps the selected period.

        Open-ended dates count as overlapping: a project with no end date is
        still running, and one with no start date has no evidence it began
        after the period.
        """
        if date_from and end and fields.Date.to_string(end) < date_from:
            return False
        if date_to and start and fields.Date.to_string(start) > date_to:
            return False
        return True

    def _table_project_status(self, date_from=None, date_to=None):
        """One row per active project with dates and estimated/actual hours.

        Estimated = sum of task.estimated for the project (all-time: an
                    estimate belongs to the whole project, not to a period).
        Actual    = hours logged (account.analytic.line.unit_amount) *within
                    the selected period*, so it lines up with the period's
                    KPI cards.
        Rows are limited to projects whose start/end window overlaps the
        period; projects with open-ended dates always show.
        """
        Project = self.env['project.project']
        Task = self.env['project.task']
        AAL = self.env['account.analytic.line']

        est_by_proj = {}
        for g in Task.read_group(
                [('project_id', '!=', False)], ['estimated:sum'],
                ['project_id'], lazy=False):
            if g.get('project_id'):
                est_by_proj[g['project_id'][0]] = g.get('estimated') or 0.0
        act_by_proj = {}
        for g in AAL.read_group(
                self._ts_domain(date_from, date_to), ['unit_amount:sum'],
                ['project_id'], lazy=False):
            if g.get('project_id'):
                act_by_proj[g['project_id'][0]] = g.get('unit_amount') or 0.0

        rows = []
        for p in Project.search([('active', '=', True)], order='name'):
            if not self._overlaps_period(p.date_start, p.date, date_from, date_to):
                continue
            rows.append({
                'project': p.name or '',
                # Show the standard Kanban stage (the status bar on the project
                # form); the custom 'status' selection is unset on most projects.
                'status': p.stage_id.name or '',
                'start_date': self._iso_date(p.date_start),
                'uat_date': self._iso_date(p.uat_start_date),
                'end_date': self._iso_date(p.date),
                'estimated': round(est_by_proj.get(p.id, 0.0), 2),
                'actual': round(act_by_proj.get(p.id, 0.0), 2),
            })
        return rows

    def _table_delivery(self, date_from, date_to):
        """One row per person: how much they delivered and how much was on time.

        Covers TLs and Developers (and everyone else) in one table, with the
        Role column carrying the employee's actual job position. That is
        deliberate: the dashboard's ROLE_BUCKETS map lumps 'technical lead' and
        'software developer' into the same 'dev' bucket, so bucketing here would
        make TLs and Developers indistinguishable — the very split that was
        asked for. The raw job name keeps them apart without disturbing the
        bucket counts the existing KPIs and the team pie depend on.

        A task with several assignees counts in full for each of them, matching
        _table_resource_status. So the column totals exceed the portfolio's task
        count; each row answers "how did this person's work land", not "who owns
        what share".
        """
        Task = self.env['project.task']
        Emp = self.env['hr.employee']

        employees = Emp.search([('active', '=', True)])
        emp_by_user = {e.user_id.id: e for e in employees if e.user_id}

        # Delivered tasks in the period, attributed to each assignee. Ids are
        # collected and browsed once per employee; unioning recordsets in the
        # loop would rebuild the set on every step.
        delivered_ids = {}
        for task in Task.search(Task._ft_delivery_domain(
                date_from=date_from, date_to=date_to)):
            for user in task.user_ids:
                emp = emp_by_user.get(user.id)
                if emp:
                    delivered_ids.setdefault(emp.id, []).append(task.id)
        delivered_by_emp = {
            emp_id: Task.browse(ids) for emp_id, ids in delivered_ids.items()
        }

        # Open + overdue right now, same attribution. One search, grouped in
        # Python, rather than a count per employee.
        overdue_by_emp = {}
        for task in Task.search(Task._ft_overdue_open_domain()):
            for user in task.user_ids:
                emp = emp_by_user.get(user.id)
                if emp:
                    overdue_by_emp[emp.id] = overdue_by_emp.get(emp.id, 0) + 1

        # Every project participant gets a row, even with all-zero stats: a
        # resource who neither delivered nor is overdue is still a resource and
        # its absence reads as "not on the team". Participants = anyone assigned
        # to at least one project task. One search_read over task assignees
        # keeps it to a single query. Non-project staff (HR, sales, ...) never
        # appear because they are never a task assignee.
        participant_emp_ids = set()
        for t in Task.search_read(
                [('user_ids', '!=', False)], ['user_ids']):
            for uid in t.get('user_ids', []):
                emp = emp_by_user.get(uid)
                if emp:
                    participant_emp_ids.add(emp.id)

        emp_by_id = {e.id: e for e in employees}
        rows = []
        for emp_id in set(delivered_by_emp) | set(overdue_by_emp) | participant_emp_ids:
            emp = emp_by_id.get(emp_id)
            if not emp:
                continue
            stats = Task._ft_on_time_aggregate(
                delivered_by_emp.get(emp_id, Task.browse()))
            rows.append({
                'employee': emp.name or '',
                'role': emp.job_id.name if emp.job_id else '',
                'delivered': stats['completed'],
                'on_time': stats['on_time'],
                'late': stats['late'],
                'no_deadline': stats['no_deadline'],
                'on_time_rate': stats['rate'],
                'overdue_open': overdue_by_emp.get(emp_id, 0),
            })
        rows.sort(key=lambda r: r['employee'].lower())
        return rows

    def _table_resource_status(self, date_from=None, date_to=None):
        """One row per (employee, project), grouped/sorted by employee name.

        Hours Spent    = timesheet hours the employee logged on the project
                         *within the selected period*.
        Estimated      = sum of task.estimated for the project's tasks assigned
                         to that employee (via task assignees -> employee).
        Days Left      = project End Date (project.date) - today.
        Role           = employee's Job Position.
        """
        AAL = self.env['account.analytic.line']
        Emp = self.env['hr.employee']
        Task = self.env['project.task']
        Project = self.env['project.project']

        # Employee lookups (id -> record, user_id -> employee id).
        employees = Emp.search([('active', '=', True)])
        emp_by_id = {e.id: e for e in employees}
        emp_by_user = {e.user_id.id: e.id for e in employees if e.user_id}

        # Project lookups.
        proj_by_id = {p.id: p for p in Project.search([])}

        # Hours spent per (employee, project) from timesheets.
        hours = {}
        for g in AAL.read_group(
                self._ts_domain(date_from, date_to) + [('employee_id', '!=', False)],
                ['unit_amount:sum'], ['employee_id', 'project_id'], lazy=False):
            if g.get('employee_id') and g.get('project_id'):
                hours[(g['employee_id'][0], g['project_id'][0])] = \
                    g.get('unit_amount') or 0.0

        # One pass over assigned tasks yields both facts: the estimate per
        # (employee, project) and the full set of pairs the person is actually
        # on. ``assigned`` is what puts a resource on the table even with no
        # logged hours and no estimate — keying the rows off hours/estimates
        # alone hid anyone who had simply not booked time yet, which reads as
        # "not on the project" rather than "nothing logged".
        est = {}
        assigned = set()
        for t in Task.search_read(
                [('project_id', '!=', False), ('user_ids', '!=', False)],
                ['project_id', 'user_ids', 'estimated']):
            proj_id = t['project_id'][0]
            estimated = t.get('estimated') or 0.0
            for uid in t.get('user_ids', []):
                emp_id = emp_by_user.get(uid)
                if not emp_id:
                    continue
                key = (emp_id, proj_id)
                assigned.add(key)
                if estimated:
                    est[key] = est.get(key, 0.0) + estimated

        today = fields.Date.context_today(self)
        rows = []
        for (emp_id, proj_id) in set(hours) | assigned:
            emp = emp_by_id.get(emp_id)
            proj = proj_by_id.get(proj_id)
            if not emp or not proj:
                continue
            # Hours booked in the period are evidence the work happened, and
            # outrank the project's own dates: time logged against a project
            # that officially closed last year is still time this person spent,
            # and silently dropping it made Hours Spent disagree with the
            # timesheets. The project window only decides pairs with nothing
            # booked, where an estimate carries no date of its own to judge by.
            if not hours.get((emp_id, proj_id)) and not self._overlaps_period(
                    proj.date_start, proj.date, date_from, date_to):
                continue
            days_left = (proj.date - today).days if proj.date else None
            rows.append({
                'employee': emp.name or '',
                'role': emp.job_id.name if emp.job_id else '',
                'project': proj.name or '',
                'status': proj.stage_id.name or '',
                # Project start date, exposed so the client can date-filter the
                # resource rows (they are otherwise timesheet-aggregated totals).
                'start_date': self._iso_date(proj.date_start),
                'days_left': days_left,
                'hours_spent': round(hours.get((emp_id, proj_id), 0.0), 2),
                'estimated': round(est.get((emp_id, proj_id), 0.0), 2),
            })
        rows.sort(key=lambda r: (r['employee'].lower(), r['project'].lower()))
        return rows

    def _chart_project_hours(self, date_from, date_to):
        """Bar: estimated / spent / remaining per project.

        Estimated = the project's Estimated Time (``allocated_hours``) — the
                    value shown on the project form. This is a whole-project
                    figure with no per-period breakdown, so it stays the same
                    across every filter.
        Spent     = timesheet hours logged on the project *within the selected
                    period*, so the Spent bars follow the date filter.
        Remaining = max(Estimated - ALL-time spend, 0) — the budget still left
                    on the project, so it holds still while Spent moves with
                    the filter.

        Remaining deliberately ignores the date filter. Estimated is a
        whole-project allocation, so subtracting one period's hours from it
        yielded a figure that was neither: a project with 50h allocated and 10h
        already burned in June still reported "50 remaining" whenever June sat
        outside the selected range, contradicting the 10h Actual Hours on the
        project form. A remaining budget is not a per-period quantity.
        """
        Project = self.env['project.project']
        AAL = self.env['account.analytic.line']

        name_by_proj = {}
        est_by_proj = {}
        for p in Project.search_read([], ['name', 'allocated_hours']):
            name_by_proj[p['id']] = p['name'] or ''
            est_by_proj[p['id']] = p['allocated_hours'] or 0.0

        # Spent: the selected period only, so the orange bars follow the filter.
        spent_by_proj = {}
        for g in AAL.read_group(
                self._ts_domain(date_from, date_to), ['unit_amount:sum'],
                ['project_id']):
            proj = g.get('project_id')
            if proj:
                spent_by_proj[proj[0]] = g.get('unit_amount') or 0.0

        # Spend to date, unfiltered — the basis for Remaining. Same domain
        # minus the dates, so the two totals can only differ by the period.
        spent_all_by_proj = {}
        for g in AAL.read_group(
                self._ts_domain(None, None), ['unit_amount:sum'],
                ['project_id']):
            proj = g.get('project_id')
            if proj:
                spent_all_by_proj[proj[0]] = g.get('unit_amount') or 0.0

        proj_ids = set(est_by_proj) | set(spent_by_proj)
        rows = []
        for pid in proj_ids:
            est = est_by_proj.get(pid, 0.0)
            spent = spent_by_proj.get(pid, 0.0)
            # Nothing to plot for a project with neither an estimate nor spend.
            if not est and not spent:
                continue
            name = name_by_proj.get(pid) or Project.browse(pid).display_name
            remaining = max(est - spent_all_by_proj.get(pid, 0.0), 0.0)
            rows.append((pid, name, est, spent, remaining))
        # Every project that has estimated or logged hours, biggest first. The
        # chart scrolls horizontally, so there is no cap on the project count.
        rows.sort(key=lambda r: (r[2] + r[3]), reverse=True)
        return {
            'labels': [r[1] for r in rows],
            'datasets': [
                {'label': 'Estimated', 'data': [round(r[2], 2) for r in rows], 'backgroundColor': '#4F46E5'},
                {'label': 'Spent', 'data': [round(r[3], 2) for r in rows], 'backgroundColor': '#F59E0B'},
                {'label': 'Remaining', 'data': [round(r[4], 2) for r in rows], 'backgroundColor': '#10B981'},
            ],
            'meta': {'project_ids': [r[0] for r in rows]},
        }

    def _chart_billable(self, date_from, date_to):
        """Bar: billable vs non-billable hours (by project allow_billable flag)."""
        AAL = self.env['account.analytic.line']
        ts_domain = self._ts_domain(date_from, date_to)
        total = sum(g['unit_amount'] for g in AAL.read_group(
            ts_domain, ['unit_amount:sum'], []) if g.get('unit_amount'))
        billable = sum(g['unit_amount'] for g in AAL.read_group(
            ts_domain + [('project_id.allow_billable', '=', True)],
            ['unit_amount:sum'], []) if g.get('unit_amount'))
        non_billable = max(total - billable, 0.0)
        return {
            'labels': ['Billable', 'Non-Billable'],
            'datasets': [{
                'label': 'Hours',
                'data': [round(billable, 2), round(non_billable, 2)],
                'backgroundColor': ['#10B981', '#94A3B8'],
            }],
        }

    def _chart_team_composition(self):
        """Pie: developers / testers / trainees / project managers."""
        roles = self._role_counts()
        return {
            'labels': ['Developers', 'Testers', 'Trainees', 'Project Managers'],
            'datasets': [{
                'data': [roles['dev'], roles['qa'], roles['trainee'], roles['pm']],
                'backgroundColor': ['#4F46E5', '#06B6D4', '#10B981', '#F59E0B'],
            }],
        }

    # Bucket sizes for the progress trend, picked from the span of the range so
    # the X axis never carries more labels than it can legibly show.
    TREND_DAY_SPAN = 31
    TREND_WEEK_SPAN = 120

    def _trend_bucket(self, days):
        """Return the bucket granularity to use for ``days`` (a sorted list)."""
        if not days:
            return 'day'
        span = (days[-1] - days[0]).days
        if span <= self.TREND_DAY_SPAN:
            return 'day'
        if span <= self.TREND_WEEK_SPAN:
            return 'week'
        return 'month'

    def _trend_bucket_key(self, day, bucket):
        """Collapse ``day`` onto the start of its bucket."""
        if bucket == 'week':
            return day - timedelta(days=day.weekday())
        if bucket == 'month':
            return day.replace(day=1)
        return day

    def _trend_bucket_label(self, key, bucket):
        if bucket == 'week':
            return 'Wk of %s' % key.strftime('%d %b')
        if bucket == 'month':
            return key.strftime('%b %Y')
        return key.strftime('%d %b %Y')

    def _chart_progress_trend(self, date_from, date_to):
        """Bar: hours logged and tasks completed per bucket within the range.

        Uses ``_read_group`` so each day is a real ``date`` object — sorting on
        those keeps the X axis chronological. (Grouping via ``read_group`` yields
        formatted labels like '03 Jul 2026' that sort alphabetically, which
        scrambled the timeline.)

        Days are then rolled up into day/week/month buckets depending on how
        long the selected range is. Plotting a full year day-by-day produced
        ~250 labels that Chart.js thinned to an arbitrary, uneven-looking subset
        ('01 Jan, 10 Jan, 19 Jan, ...'), which read as noise rather than a
        trend. Bucketing keeps every bar meaningful and every label round.
        """
        AAL = self.env['account.analytic.line']
        Task = self.env['project.task']

        def _as_date(d):
            return d.date() if isinstance(d, datetime) else d

        hours_by_day = {}
        for day, total in AAL._read_group(
                self._ts_domain(date_from, date_to), ['date:day'], ['unit_amount:sum']):
            if day:
                hours_by_day[_as_date(day)] = round(total or 0.0, 2)

        tasks_by_day = {}
        try:
            task_domain = [('state', '=', '1_done')]
            if date_from:
                task_domain.append(('date_last_stage_update', '>=', date_from))
            if date_to:
                task_domain.append(('date_last_stage_update', '<=', date_to + ' 23:59:59'))
            for day, count in Task._read_group(
                    task_domain, ['date_last_stage_update:day'], ['__count']):
                if day:
                    tasks_by_day[_as_date(day)] = count
        except Exception as e:  # pragma: no cover - defensive against field/state drift
            _logger.warning('Progress-trend task series unavailable: %s', e)

        days = sorted(set(hours_by_day) | set(tasks_by_day))
        bucket = self._trend_bucket(days)

        hours_by_bucket = {}
        tasks_by_bucket = {}
        for day in days:
            key = self._trend_bucket_key(day, bucket)
            hours_by_bucket[key] = hours_by_bucket.get(key, 0.0) + hours_by_day.get(day, 0.0)
            tasks_by_bucket[key] = tasks_by_bucket.get(key, 0) + tasks_by_day.get(day, 0)

        keys = sorted(hours_by_bucket)
        return {
            'labels': [self._trend_bucket_label(k, bucket) for k in keys],
            'datasets': [
                {
                    'label': 'Hours Logged',
                    'data': [round(hours_by_bucket.get(k, 0.0), 2) for k in keys],
                    'backgroundColor': 'rgba(79,70,229,0.85)',
                    'borderColor': '#4F46E5', 'borderWidth': 1,
                    'borderRadius': 4, 'yAxisID': 'y',
                },
                {
                    'label': 'Tasks Completed',
                    'data': [tasks_by_bucket.get(k, 0) for k in keys],
                    'backgroundColor': 'rgba(16,185,129,0.85)',
                    'borderColor': '#10B981', 'borderWidth': 1,
                    'borderRadius': 4, 'yAxisID': 'y1',
                },
            ],
        }
