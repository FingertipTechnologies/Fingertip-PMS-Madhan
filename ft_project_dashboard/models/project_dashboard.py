import logging

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
            'charts': {
                'project_status': self._chart_project_status(),
                'resource_status': self._chart_resource_status(date_from, date_to),
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
            # No capacity/planning model exists yet — surfaced as placeholders.
            'resource_need': None,
            'available_resources': None,
        }

    # ------------------------------------------------------------------
    # Charts
    # ------------------------------------------------------------------
    def _chart_project_status(self):
        """Doughnut: project count by the 12 real status values."""
        Project = self.env['project.project']
        sel = dict(Project.fields_get(['status'])['status']['selection'])
        groups = Project.read_group(
            [('active', '=', True)], ['status'], ['status'], lazy=False)
        labels, values, ids_by_label = [], [], []
        for g in groups:
            key = g.get('status')
            labels.append(sel.get(key, key or 'Undefined'))
            values.append(g['__count'])
            ids_by_label.append(key)
        return {
            'labels': labels,
            'datasets': [{'data': values, 'backgroundColor': PALETTE[:len(values)]}],
            'meta': {'field': 'status', 'keys': ids_by_label},
        }

    def _chart_resource_status(self, date_from, date_to):
        """Stacked bar: a light heuristic since no planning module exists.

        Allocated  = distinct active employees with timesheet activity in range.
        Available  = active employees - allocated.
        Overallocated = 0 (no capacity model to detect over-allocation).
        """
        AAL = self.env['account.analytic.line']
        groups = AAL.read_group(
            self._ts_domain(date_from, date_to) + [('employee_id', '!=', False)],
            ['employee_id'], ['employee_id'])
        allocated = len([g for g in groups if g.get('employee_id')])
        total = self.env['hr.employee'].search_count([('active', '=', True)])
        available = max(total - allocated, 0)
        return {
            'labels': ['Resources'],
            'datasets': [
                {'label': 'Available', 'data': [available], 'backgroundColor': '#10B981'},
                {'label': 'Allocated', 'data': [allocated], 'backgroundColor': '#4F46E5'},
                {'label': 'Overallocated', 'data': [0], 'backgroundColor': '#EF4444'},
            ],
            'note': 'Heuristic — no planning/capacity model installed.',
        }

    def _chart_project_hours(self, date_from, date_to):
        """Bar: estimated / spent / remaining for the top active projects."""
        Task = self.env['project.task']
        AAL = self.env['account.analytic.line']

        est_by_proj = {}
        for g in Task.read_group(
                [('project_id', '!=', False)], ['estimated:sum'], ['project_id']):
            proj = g.get('project_id')
            if proj:
                est_by_proj[proj[0]] = (proj[1], g.get('estimated') or 0.0)

        spent_by_proj = {}
        for g in AAL.read_group(
                self._ts_domain(date_from, date_to), ['unit_amount:sum'], ['project_id']):
            proj = g.get('project_id')
            if proj:
                spent_by_proj[proj[0]] = g.get('unit_amount') or 0.0

        proj_ids = set(est_by_proj) | set(spent_by_proj)
        rows = []
        for pid in proj_ids:
            name, est = est_by_proj.get(pid, (None, 0.0))
            if name is None:
                name = self.env['project.project'].browse(pid).display_name
            spent = spent_by_proj.get(pid, 0.0)
            rows.append((pid, name, est, spent, max(est - spent, 0.0)))
        # Top 10 by estimated+spent volume, descending.
        rows.sort(key=lambda r: (r[2] + r[3]), reverse=True)
        rows = rows[:10]
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
        """Line: hours logged and tasks completed per day within the range."""
        AAL = self.env['account.analytic.line']
        Task = self.env['project.task']

        hours_by_day = {}
        for g in AAL.read_group(
                self._ts_domain(date_from, date_to), ['unit_amount:sum'], ['date:day']):
            label = g.get('date:day')
            if label:
                hours_by_day[label] = round(g.get('unit_amount') or 0.0, 2)

        tasks_by_day = {}
        try:
            task_domain = [('state', '=', '1_done')]
            if date_from:
                task_domain.append(('date_last_stage_update', '>=', date_from))
            if date_to:
                task_domain.append(('date_last_stage_update', '<=', date_to + ' 23:59:59'))
            for g in Task.read_group(
                    task_domain, [], ['date_last_stage_update:day'], lazy=False):
                label = g.get('date_last_stage_update:day')
                if label:
                    tasks_by_day[label] = g['__count']
        except Exception as e:  # pragma: no cover - defensive against field/state drift
            _logger.warning('Progress-trend task series unavailable: %s', e)

        labels = sorted(set(hours_by_day) | set(tasks_by_day))
        return {
            'labels': labels,
            'datasets': [
                {
                    'label': 'Hours Logged',
                    'data': [hours_by_day.get(d, 0) for d in labels],
                    'borderColor': '#4F46E5', 'backgroundColor': 'rgba(79,70,229,0.15)',
                    'tension': 0.35, 'fill': True, 'yAxisID': 'y',
                },
                {
                    'label': 'Tasks Completed',
                    'data': [tasks_by_day.get(d, 0) for d in labels],
                    'borderColor': '#10B981', 'backgroundColor': 'rgba(16,185,129,0.15)',
                    'tension': 0.35, 'fill': True, 'yAxisID': 'y1',
                },
            ],
        }
