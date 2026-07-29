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

# Project stages that do not represent active delivery work: "General" is the
# intake bucket, "Hold" is paused and "Closed" is finished. Everything else is
# in-flight and counts towards Active Projects.
#
# Matched by stage NAME rather than id because project.project.stage rows are
# created per database, so the ids differ between staging and production. The
# older `status` selection on bt_project_customization is NOT used here: it is
# NULL on every project, which made the previous `status not in ('closed',)`
# filter a no-op that counted closed projects as active.
INACTIVE_STAGE_NAMES = ('General', 'Hold', 'Closed')

# Stage holding projects under an annual maintenance contract.
AMC_STAGE_NAME = 'AMC'

# Project whose task time is reported as Standup Hours. Matched by name for the
# same reason stages are: the project id differs between databases.
STANDUP_PROJECT_NAME = 'Fingertip Standup'

# task_type values (bt_project_customization) that count as meetings.
INTERNAL_MEETING_TYPE = 'internal_call'
EXTERNAL_MEETING_TYPE = 'external_call'

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

    def _stage_ids_named(self, names):
        """Resolve project stage names to ids.

        Domains are built on ids rather than on ``stage_id.name`` because the
        stage name is a translated (jsonb) column, and comparing it inside a
        domain is both slower and language-dependent. Archived stages are
        included: a project can still sit in one.
        """
        return self.env['project.project.stage'].with_context(
            active_test=False).search([('name', 'in', list(names))]).ids

    def _active_project_domain(self):
        """Projects counted as active: not General, not Hold, not Closed.

        ``not in`` on a many2one also matches rows with no stage set, so a
        project that has never been staged still counts as active rather than
        silently disappearing from the figure.
        """
        return [
            ('active', '=', True),
            ('stage_id', 'not in', self._stage_ids_named(INACTIVE_STAGE_NAMES)),
        ]

    def _amc_project_domain(self):
        """Projects sitting in the AMC stage."""
        return [
            ('active', '=', True),
            ('stage_id', 'in', self._stage_ids_named((AMC_STAGE_NAME,))),
        ]

    def _implementation_project_domain(self):
        """Active projects still being implemented: Active Projects minus AMC.

        AMC is ongoing maintenance rather than delivery work, so it is reported
        on its own card and excluded here. This keeps the two cards additive:
        Active Projects == Implementation Projects + AMC Projects.
        """
        return [
            ('active', '=', True),
            ('stage_id', 'not in',
             self._stage_ids_named(INACTIVE_STAGE_NAMES + (AMC_STAGE_NAME,))),
        ]

    def _hours_filter_domain(self, filters=None):
        """Timesheet-line domain behind the Hours Utilisation section.

        Every figure in that section is built from this one domain, so the
        cards can never disagree with each other about what is being counted.
        With no filters it is simply "every line attached to a task", which is
        exactly what the task form's Dev/QA/PM/BA Hours fields sum.
        """
        filters = filters or {}
        domain = [('task_id', '!=', False)]
        if filters.get('date_from'):
            domain.append(('date', '>=', filters['date_from']))
        if filters.get('date_to'):
            domain.append(('date', '<=', filters['date_to']))
        if filters.get('project_id'):
            domain.append(('project_id', '=', int(filters['project_id'])))
        if filters.get('stage_id'):
            domain.append(('project_id.stage_id', '=', int(filters['stage_id'])))
        # PM and Dev both mean "the person who booked the time", so they are
        # OR-ed. AND-ing two employee filters could only ever match nothing,
        # since a line has exactly one employee.
        people = [int(x) for x in (filters.get('pm_id'), filters.get('dev_id')) if x]
        if people:
            domain.append(('employee_id', 'in', people))
        return domain

    def _role_hours(self, domain):
        """Dev / QA / PM / BA hours for the given timesheet-line domain.

        Aggregated from the lines rather than read off ``ft_dev_hours`` and
        friends because those task fields are whole-task totals with no date
        dimension — they cannot answer "Developer Hours in July". Grouping the
        lines by employee and bucketing by job position reproduces exactly what
        those fields compute (verified equal to the task-field sum when no
        filter is applied), while staying sliceable by date, project and person.

        Archived employees are included: their past hours still show on the
        task form, so dropping them would make the cards disagree with it.
        """
        AAL = self.env['account.analytic.line']
        groups = AAL.read_group(domain, ['unit_amount:sum'], ['employee_id'])

        emp_ids = [g['employee_id'][0] for g in groups if g.get('employee_id')]
        # sudo: hr.job is readable only by HR officers, but every project user
        # still needs their hours bucketed.
        bucket_by_emp = {}
        for emp in self.env['hr.employee'].sudo().with_context(
                active_test=False).search_read([('id', 'in', emp_ids)], ['job_id']):
            job = emp.get('job_id')
            name = (job[1] if job else '').strip().lower()
            bucket_by_emp[emp['id']] = (
                'trainee' if name.startswith('trainee')
                else ROLE_BUCKETS.get(name, 'other')
            )

        totals = dict.fromkeys(('dev', 'qa', 'pm', 'ba', 'trainee', 'other'), 0.0)
        for group in groups:
            emp = group.get('employee_id')
            if not emp:
                continue
            totals[bucket_by_emp.get(emp[0], 'other')] += group.get('unit_amount') or 0.0
        return totals

    def _activity_hours(self, domain):
        """Standup and meeting hours for the given timesheet-line domain.

        Built from the same lines as the role split so both halves of the
        section always answer the same question. Meeting Hours is internal +
        external, keeping the three meeting figures additive.

        Standup and Meeting can overlap: a task in the Standup project that is
        also typed as a call counts in both. They are two views of the same
        time, not a partition.
        """
        AAL = self.env['account.analytic.line']

        def total(extra):
            return sum(
                group['unit_amount']
                for group in AAL.read_group(domain + extra, ['unit_amount:sum'], [])
                if group.get('unit_amount')
            )

        internal = total([('task_id.task_type', '=', INTERNAL_MEETING_TYPE)])
        external = total([('task_id.task_type', '=', EXTERNAL_MEETING_TYPE)])
        return {
            'standup': total([('project_id.name', '=', STANDUP_PROJECT_NAME)]),
            'internal_meeting': internal,
            'external_meeting': external,
            'meeting': internal + external,
        }

    def _hours_utilisation_values(self, filters=None):
        """The eight Hours Utilisation figures for a set of filters."""
        domain = self._hours_filter_domain(filters)
        role = self._role_hours(domain)
        activity = self._activity_hours(domain)
        return {
            'dev_hours': round(role['dev'], 2),
            'pm_hours': round(role['pm'], 2),
            'qa_hours': round(role['qa'], 2),
            'ba_hours': round(role['ba'], 2),
            'standup_hours': round(activity['standup'], 2),
            'meeting_hours': round(activity['meeting'], 2),
            'internal_meeting_hours': round(activity['internal_meeting'], 2),
            'external_meeting_hours': round(activity['external_meeting'], 2),
        }

    @api.model
    def get_hours_utilisation(self, filters=None):
        """Recompute just the Hours Utilisation cards for its own filters.

        The section carries filters the top period bar knows nothing about, so
        the numbers have to be rebuilt server-side — the browser holds totals,
        and no amount of client-side filtering can turn a total into a subset.
        """
        return self._hours_utilisation_values(filters)

    # ------------------------------------------------------------------
    # Tasks Summary
    # ------------------------------------------------------------------
    @staticmethod
    def _date_leaves(field, date_from, date_to):
        """Range leaves for a Datetime field bounded by two calendar dates.

        ``create_date`` and ``date_deadline`` are both Datetimes, so an upper
        bound of the bare date would cut the closing day off at midnight and
        drop everything recorded during it.
        """
        leaves = []
        if date_from:
            leaves.append((field, '>=', str(date_from) + ' 00:00:00'))
        if date_to:
            leaves.append((field, '<=', str(date_to) + ' 23:59:59'))
        return leaves

    def _task_scope_domain(self, filters=None):
        """The non-date part of the Tasks Summary filters.

        Kept apart from the dates because each card anchors on a different
        date — created on ``create_date``, due on ``date_deadline``, completed
        on the completion date — while project / stage / people apply to all of
        them identically.

        PM and Dev match different fields here (project manager vs assignee), so
        unlike the Hours filters they AND together and stay meaningful.
        """
        filters = filters or {}
        domain = []
        if filters.get('project_id'):
            domain.append(('project_id', '=', int(filters['project_id'])))
        if filters.get('stage_id'):
            domain.append(('project_id.stage_id', '=', int(filters['stage_id'])))

        # The dropdowns carry hr.employee ids but tasks reference res.users, so
        # each pick has to be resolved through the employee's linked user. An
        # employee with no user matches nothing rather than being ignored —
        # silently dropping the filter would show totals that look unfiltered.
        Employee = self.env['hr.employee'].sudo()
        if filters.get('dev_id'):
            user = Employee.browse(int(filters['dev_id'])).user_id
            domain.append(('user_ids', 'in', user.ids) if user else ('id', '=', 0))
        if filters.get('pm_id'):
            user = Employee.browse(int(filters['pm_id'])).user_id
            domain.append(('project_id.user_id', '=', user.id) if user else ('id', '=', 0))
        return domain

    def _tasks_summary_values(self, filters=None):
        """The eight Tasks Summary figures for a set of filters.

        Completed / on-timeline / missed all come from project.task's own
        delivery helpers — the single definition of "delivered" and "on time"
        for the whole PMS — so these cards can never disagree with the On-Time
        Delivery card in Project Summary.
        """
        filters = filters or {}
        Task = self.env['project.task']
        scope = self._task_scope_domain(filters)
        date_from, date_to = filters.get('date_from'), filters.get('date_to')

        created = scope + self._date_leaves('create_date', date_from, date_to)
        due = scope + [('date_deadline', '!=', False)] + self._date_leaves(
            'date_deadline', date_from, date_to)

        # Delivered tasks are fetched once and split here rather than asking for
        # counts and then re-searching for the drill-downs: the list a card
        # opens is then literally the recordset its number was taken from.
        delivered = Task.search(Task._ft_delivery_domain(scope, date_from, date_to))
        split = Task._ft_on_time_split(delivered)

        # A snapshot of now, like Open & Overdue: a task open today is open
        # whatever window is being looked at.
        open_domain = Task._ft_open_domain(scope)
        # Estimation is reported over the tasks CREATED in the window, so the
        # two add back up to Tasks Created.
        estimated = created + [('estimated', '>', 0)]
        not_estimated = created + [('estimated', '<=', 0)]

        counts = {
            'tasks_created': Task.search_count(created),
            'tasks_due': Task.search_count(due),
            'tasks_completed': len(delivered),
            'tasks_open': Task.search_count(open_domain),
            'tasks_estimated': Task.search_count(estimated),
            'tasks_not_estimated': Task.search_count(not_estimated),
            'tasks_on_timeline': len(split['on_time']),
            'tasks_missed_timeline': len(split['late']),
        }

        def action(name, domain):
            return {'res_model': 'project.task', 'name': name,
                    'domain': self._jsonify_domain(domain)}

        counts['actions'] = {
            'tasks_created': action('Tasks Created', created),
            'tasks_due': action('Tasks Due', due),
            'tasks_completed': action('Completed Tasks', [('id', 'in', delivered.ids)]),
            'tasks_open': action('Open Tasks', open_domain),
            'tasks_estimated': action('Estimated Tasks', estimated),
            'tasks_not_estimated': action('Not Estimated', not_estimated),
            # By id: on time is a calendar-day comparison done in Python, so
            # there is no domain that could express it.
            'tasks_on_timeline': action('Completed on Timeline',
                                        [('id', 'in', split['on_time'])]),
            'tasks_missed_timeline': action('Missed Timeline',
                                            [('id', 'in', split['late'])]),
        }
        return counts

    @api.model
    def get_tasks_summary(self, filters=None):
        """Recompute just the Tasks Summary cards for its own filters."""
        return self._tasks_summary_values(filters)

    def _task_hours_summary_values(self, filters=None):
        """Hour totals read off the task records themselves.

        Every figure here is a stored column on project.task, so each is one
        SQL sum. This is deliberately task-centric: it answers "what do these
        tasks add up to", which is why it can report Estimated, Billable and
        Billed alongside Actual — none of which exist on a timesheet line.

        Scope matches Tasks Summary (tasks CREATED in the window, plus the
        project / stage / people filters) rather than Hours Utilisation's
        "time booked in the window". The two sections answer different
        questions and will not tally when a date filter is on.
        """
        filters = filters or {}
        Task = self.env['project.task']
        base = self._task_scope_domain(filters) + self._date_leaves(
            'create_date', filters.get('date_from'), filters.get('date_to'))

        def total(field, extra=None):
            return sum(
                group[field]
                for group in Task.read_group(base + (extra or []), [field + ':sum'], [])
                if group.get(field)
            )

        internal = total('ft_total_hours_taken',
                         [('task_type', '=', INTERNAL_MEETING_TYPE)])
        external = total('ft_total_hours_taken',
                         [('task_type', '=', EXTERNAL_MEETING_TYPE)])
        return {
            'th_meeting_hours': round(internal + external, 2),
            'th_internal_meeting_hours': round(internal, 2),
            'th_external_meeting_hours': round(external, 2),
            'th_estimated_hours': round(total('estimated'), 2),
            'th_actual_hours': round(total('ft_total_hours_taken'), 2),
            'th_billable_hours': round(total('ft_billable_hours'), 2),
            'th_non_billable_hours': round(total('ft_non_billable_hours'), 2),
            # Billable hours on tasks marked Billed — the hours actually
            # invoiced, not merely invoiceable.
            'th_billed_hours': round(
                total('ft_billable_hours', [('ft_billing_status', '=', 'billed')]), 2),
        }

    @api.model
    def get_task_hours_summary(self, filters=None):
        """Recompute just the Task Hours Summary cards for its own filters."""
        return self._task_hours_summary_values(filters)

    @api.model
    def get_hours_filter_options(self):
        """Dropdown contents for the Hours Utilisation filter bar.

        Only projects that actually carry task time are offered: a picker
        listing every project ever created would mostly be options that can
        only ever produce zero.
        """
        AAL = self.env['account.analytic.line']
        project_groups = AAL.read_group(
            [('task_id', '!=', False), ('project_id', '!=', False)],
            ['unit_amount:sum'], ['project_id'])
        projects = sorted(
            ({'id': g['project_id'][0], 'name': g['project_id'][1]}
             for g in project_groups if g.get('project_id')),
            key=lambda p: (p['name'] or '').lower())

        stages = [
            {'id': s.id, 'name': s.name}
            for s in self.env['project.project.stage'].search([], order='sequence, name')
        ]

        role_ids = self._role_employee_ids()
        Employee = self.env['hr.employee'].sudo()

        def people(bucket):
            return [
                {'id': e.id, 'name': e.name}
                for e in Employee.browse(role_ids[bucket]).sorted(
                    lambda e: (e.name or '').lower())
            ]

        return {
            'projects': projects,
            'stages': stages,
            'project_managers': people('pm'),
            'developers': people('dev'),
        }

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

        Resource Status and Resource Performance are deliberately NOT
        given the period: both are per-person standing views that carry their
        own Start/End pickers, and answering to two date filters at once made
        the numbers unreadable — a range typed into the table was silently
        intersected with whatever the top bar was on. They load all-time and
        change only through their own pickers (get_resource_status /
        get_delivery_by_resource).
        """
        return {
            'kpis': self._compute_kpis(date_from, date_to),
            'tables': {
                'project_status': self._table_project_status(date_from, date_to),
                'resource_status': self._table_resource_status(),
                'delivery': self._table_delivery(),
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

    @api.model
    def get_delivery_by_resource(self, date_from=None, date_to=None):
        """Just the Resource Performance rows, for its own date range.

        Same reasoning as ``get_resource_status``: Delivered / On Time / Late are
        aggregates, not per-row dates, so the browser has nothing it could filter
        them by. The range has to reach the delivery domain, which means the
        server recomputes. With both bounds empty this is the all-time table.

        Open & Overdue stays a snapshot of now whatever the range says — a task
        that is late today is late regardless of the window being looked at.
        """
        return self._table_delivery(date_from or None, date_to or None)

    # ------------------------------------------------------------------
    # KPI cards
    # ------------------------------------------------------------------
    def _compute_kpis(self, date_from, date_to):
        Project = self.env['project.project']
        AAL = self.env['account.analytic.line']
        Task = self.env['project.task']

        active_project_domain = self._active_project_domain()
        amc_project_domain = self._amc_project_domain()
        implementation_project_domain = self._implementation_project_domain()
        active_projects = Project.search_count(active_project_domain)
        amc_projects = Project.search_count(amc_project_domain)
        implementation_projects = Project.search_count(implementation_project_domain)

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

        # Hours Utilisation first paint: unfiltered totals. The section has its
        # own filter bar and refetches through get_hours_utilisation, so it is
        # deliberately NOT tied to the period filter at the top.
        hours_utilisation = self._hours_utilisation_values()
        tasks_summary = self._tasks_summary_values()
        # Lifted out before the spread below: the payload has one shared
        # `actions` map, so leaving this key in place would collide with it and
        # the Tasks Summary cards would open nothing on first paint.
        task_actions = tasks_summary.pop('actions', {})
        task_hours_summary = self._task_hours_summary_values()

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
            # Served from the same domains as the counts above, so the list the
            # card opens always holds exactly the number the card shows.
            'active_projects': {
                'res_model': 'project.project', 'name': 'Active Projects',
                'domain': active_project_domain,
            },
            'amc_projects': {
                'res_model': 'project.project', 'name': 'AMC Projects',
                'domain': amc_project_domain,
            },
            'implementation_projects': {
                'res_model': 'project.project', 'name': 'Implementation Projects',
                'domain': implementation_project_domain,
            },
            # Hours Utilisation cards are read-only totals with no drill-down,
            # so they intentionally contribute no action here.
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
            # Tasks Summary drill-downs, built by _tasks_summary_values.
            **task_actions,
        }

        return {
            'active_projects': active_projects,
            'implementation_projects': implementation_projects,
            'amc_projects': amc_projects,
            'hours_spent': round(spent, 2),
            # Hours Utilisation and Tasks Summary (unfiltered first paint —
            # both sections refetch through their own filter bars).
            **hours_utilisation,
            **tasks_summary,
            **task_hours_summary,
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

        shown = Project.search([('active', '=', True)], order='name').filtered(
            lambda p: self._overlaps_period(
                p.date_start, p.date, date_from, date_to))

        # DE / OTD / RWR / DWD for every shown project in ONE search, from the
        # same helper project.project's own ft_* fields use. Those fields are
        # all-time, though, while this table is period-scoped — so the range is
        # passed through here instead of reading them, keeping these columns
        # consistent with the Actual Hrs beside them.
        stats_by_project = Task._ft_on_time_stats_by_project(
            shown.ids, date_from, date_to)
        # A project that delivered nothing in the period reads like an empty
        # recordset rather than a zero: rates come back None so the UI shows
        # "N/A" instead of a 0% that looks like failure.
        no_delivery = Task._ft_delivery_kpis(Task.browse())

        rows = []
        for p in shown:
            stats = stats_by_project.get(p.id) or no_delivery
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
                # Same four measures as Resource Performance, per project.
                'de_rate': stats['efficiency_rate'],
                'otd_rate': stats['rate'],
                'rwr_rate': stats['rework_rate'],
                'dwd': stats['no_deadline'],
                # Kept alongside so a percentage drawn from two tasks is not
                # read as if it came from two hundred.
                'delivered': stats['completed'],
            })
        return rows

    def _table_delivery(self, date_from=None, date_to=None):
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
            # _ft_delivery_kpis rather than _ft_on_time_aggregate: it returns
            # the efficiency and rework figures too, from the same recordset, so
            # DE / OTD / RWR on a row are all measured over exactly the same
            # delivered tasks.
            stats = Task._ft_delivery_kpis(
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
                # Resource Performance columns.
                # DE  — (Estimated / Actual) x 100, target 90-110%.
                # OTD — (On time / Delivered with a deadline) x 100, target >=95%.
                # RWR — (Reopened / Delivered) x 100, target <=10%.
                # DWD — Delivered Without Deadline: tasks that carried no
                #       deadline and so could not be judged on time at all.
                #       It is the count OTD had to ignore, which is what makes
                #       a high OTD trustworthy or not.
                'de_rate': stats['efficiency_rate'],
                'otd_rate': stats['rate'],
                'rwr_rate': stats['rework_rate'],
                'dwd': stats['no_deadline'],
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
            if not hours.get((emp_id, proj_id)):
                # A date range was asked for, so nothing logged in it means the
                # person was not on this project then — drop the row rather than
                # print a line of zeros. Someone who had not joined yet, or was
                # on something else entirely, otherwise filled the table with
                # rows that answered "no" to the question being asked.
                # Project dates cannot stand in for this: most projects here
                # carry no start or end date at all, and _overlaps_period counts
                # an undated project as overlapping everything.
                if date_from or date_to:
                    continue
                # No range: the all-time view keeps assigned-but-unlogged pairs,
                # so a resource who simply has not booked time yet still reads
                # as being on the project.
                if not self._overlaps_period(
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
