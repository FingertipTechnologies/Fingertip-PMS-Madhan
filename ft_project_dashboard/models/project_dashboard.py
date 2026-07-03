import logging
from datetime import datetime

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

    def _role_counts(self):
        """Count active employees per role bucket via their job position."""
        counts = {'dev': 0, 'qa': 0, 'pm': 0, 'ba': 0, 'trainee': 0, 'other': 0}
        employees = self.env['hr.employee'].search_read(
            [('active', '=', True)], ['job_id']
        )
        job_names = {}
        for emp in employees:
            job = emp.get('job_id')
            name = (job[1] if job else '').strip().lower()
            job_names.setdefault(name, 0)
            job_names[name] += 1
        for name, n in job_names.items():
            if name.startswith('trainee'):
                counts['trainee'] += n
            else:
                counts[ROLE_BUCKETS.get(name, 'other')] += n
        return counts

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
                'project_status': self._table_project_status(),
                'resource_status': self._table_resource_status(),
            },
            'charts': {
                'project_hours': self._chart_project_hours(date_from, date_to),
                'billable': self._chart_billable(date_from, date_to),
                'team_composition': self._chart_team_composition(),
                'progress_trend': self._chart_progress_trend(date_from, date_to),
            },
        }

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

        roles = self._role_counts()

        return {
            'active_projects': active_projects,
            'hours_spent': round(spent, 2),
            'billable_hours': round(billable, 2),
            'developers': roles['dev'],
            'testers': roles['qa'],
            'project_managers': roles['pm'],
            'hours_estimated': round(estimated, 2),
            'hours_remaining': round(estimated - spent, 2),
            # No capacity/planning model installed yet -> shown as "N/A".
            'resource_need': None,
            'available_resources': None,
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

    def _table_project_status(self):
        """One row per active project with dates and estimated/actual hours.

        Estimated = sum of task.estimated for the project.
        Actual    = total hours logged (account.analytic.line.unit_amount).
        Both are all-time totals (a project-status snapshot, not date-filtered).
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
                [('project_id', '!=', False)], ['unit_amount:sum'],
                ['project_id'], lazy=False):
            if g.get('project_id'):
                act_by_proj[g['project_id'][0]] = g.get('unit_amount') or 0.0

        rows = []
        for p in Project.search([('active', '=', True)], order='name'):
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

    def _table_resource_status(self):
        """One row per (employee, project), grouped/sorted by employee name.

        Hours Spent    = timesheet hours the employee logged on the project.
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
                [('employee_id', '!=', False), ('project_id', '!=', False)],
                ['unit_amount:sum'], ['employee_id', 'project_id'], lazy=False):
            if g.get('employee_id') and g.get('project_id'):
                hours[(g['employee_id'][0], g['project_id'][0])] = \
                    g.get('unit_amount') or 0.0

        # Estimated per (employee, project) via task assignees.
        est = {}
        for t in Task.search_read(
                [('project_id', '!=', False), ('estimated', '>', 0)],
                ['project_id', 'user_ids', 'estimated']):
            proj_id = t['project_id'][0]
            for uid in t.get('user_ids', []):
                emp_id = emp_by_user.get(uid)
                if emp_id:
                    key = (emp_id, proj_id)
                    est[key] = est.get(key, 0.0) + (t['estimated'] or 0.0)

        today = fields.Date.context_today(self)
        rows = []
        for (emp_id, proj_id) in set(hours) | set(est):
            emp = emp_by_id.get(emp_id)
            proj = proj_by_id.get(proj_id)
            if not emp or not proj:
                continue
            days_left = (proj.date - today).days if proj.date else None
            rows.append({
                'employee': emp.name or '',
                'role': emp.job_id.name if emp.job_id else '',
                'project': proj.name or '',
                'status': proj.stage_id.name or '',
                'days_left': days_left,
                'hours_spent': round(hours.get((emp_id, proj_id), 0.0), 2),
                'estimated': round(est.get((emp_id, proj_id), 0.0), 2),
            })
        rows.sort(key=lambda r: (r['employee'].lower(), r['project'].lower()))
        return rows

    def _chart_project_hours(self, date_from, date_to):
        """Bar: estimated / spent / remaining per project.

        Estimated = the project's Estimated Time (``allocated_hours``) — the
                    value shown on the project form. (Summing the task-level
                    ``estimated`` field instead gives 0 whenever tasks were left
                    blank, which hides the Estimated/Remaining bars.)
        Spent     = all-time timesheet hours logged on the project (not
                    date-filtered, so it stays comparable to Estimated).
        Remaining = max(Estimated - Spent, 0).
        """
        Project = self.env['project.project']
        AAL = self.env['account.analytic.line']

        name_by_proj = {}
        est_by_proj = {}
        for p in Project.search_read([], ['name', 'allocated_hours']):
            name_by_proj[p['id']] = p['name'] or ''
            est_by_proj[p['id']] = p['allocated_hours'] or 0.0

        spent_by_proj = {}
        for g in AAL.read_group(
                [('project_id', '!=', False)], ['unit_amount:sum'], ['project_id']):
            proj = g.get('project_id')
            if proj:
                spent_by_proj[proj[0]] = g.get('unit_amount') or 0.0

        proj_ids = set(est_by_proj) | set(spent_by_proj)
        rows = []
        for pid in proj_ids:
            est = est_by_proj.get(pid, 0.0)
            spent = spent_by_proj.get(pid, 0.0)
            # Nothing to plot for a project with neither an estimate nor spend.
            if not est and not spent:
                continue
            name = name_by_proj.get(pid) or Project.browse(pid).display_name
            rows.append((pid, name, est, spent, max(est - spent, 0.0)))
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
        """Pie: developers / testers / project managers."""
        roles = self._role_counts()
        return {
            'labels': ['Developers', 'Testers', 'Project Managers'],
            'datasets': [{
                'data': [roles['dev'], roles['qa'], roles['pm']],
                'backgroundColor': ['#4F46E5', '#06B6D4', '#F59E0B'],
            }],
        }

    def _chart_progress_trend(self, date_from, date_to):
        """Line: hours logged and tasks completed per day within the range.

        Uses ``_read_group`` so each day is a real ``date`` object — sorting on
        those keeps the X axis chronological. (Grouping via ``read_group`` yields
        formatted labels like '03 Jul 2026' that sort alphabetically, which
        scrambled the timeline.)
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
        labels = [d.strftime('%d %b %Y') for d in days]
        return {
            'labels': labels,
            'datasets': [
                {
                    'label': 'Hours Logged',
                    'data': [hours_by_day.get(d, 0) for d in days],
                    'borderColor': '#4F46E5', 'backgroundColor': 'rgba(79,70,229,0.15)',
                    'tension': 0.35, 'fill': True, 'yAxisID': 'y',
                },
                {
                    'label': 'Tasks Completed',
                    'data': [tasks_by_day.get(d, 0) for d in days],
                    'borderColor': '#10B981', 'backgroundColor': 'rgba(16,185,129,0.15)',
                    'tension': 0.35, 'fill': True, 'yAxisID': 'y1',
                },
            ],
        }
