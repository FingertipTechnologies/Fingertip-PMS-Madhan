"""Data provider for the Sales dashboard.

PERIOD FIELD
============
Every metric is dated by ``date_deadline`` (Expected Closing) — see
PERIOD_FIELD below for why, and for the one-line switch back to ``date_closed``
for won/lost once the underlying data supports it.

Creation date is used nowhere. An opportunity created in one month is often
expected to close in another, so dating anything by ``create_date`` reported
the wrong month; that was the original defect.

WON / LOST SEMANTICS (from odoo/addons/crm/models/crm_lead.py)
=============================================================
* Won  = ``probability = 100``, active untouched. Detected here as a won stage
  on a live record: ``stage_id.is_won = True AND active = True``.
* Lost = ``action_set_lost`` archives the record, so ``active = False``.
* Open = live and not in a won stage.

Archived is therefore what separates lost from won; a won stage alone is not
enough, because a won lead that is later archived is no longer a live sale.
"""
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

# Consistent palette shared across the dashboard charts.
PALETTE = [
    '#4F46E5', '#06B6D4', '#10B981', '#F59E0B', '#EF4444',
    '#8B5CF6', '#EC4899', '#14B8A6', '#F97316', '#3B82F6',
]

# THE period field for every metric on this dashboard.
#
# An opportunity created in one month is often expected to close in another, so
# filtering on create_date reported the wrong month for everything — that was
# the original defect. Expected Closing is the business date, so it is used
# uniformly: pipeline, funnel, executive reports, won and lost alike.
#
# Odoo's own CRM reports date outcomes by ``date_closed`` instead. That is left
# here as a one-line switch rather than removed: in THIS database only 21 of 53
# won opportunities carry a date_closed (32 were imported straight into a Won
# stage, which never stamps it), against 47 that carry an Expected Closing.
# Once that data is repaired, flipping OUTCOME_FIELD to 'date_closed' restores
# strict "when did it actually close" semantics for won/lost.
PERIOD_FIELD = 'date_deadline'
OUTCOME_FIELD = 'date_deadline'

MONTHS_AHEAD = 6
MONTHS_BACK = 6
# Opportunities listed inline on each month card; the rest are reached by
# clicking through, so a busy month cannot make the card unreadable.
LIST_PER_MONTH = 5
# Safety cap on the record fetch behind the month cards. Totals are computed
# separately by read_group, so a cap here never makes a number wrong — it only
# limits how many rows can be listed inline.
FETCH_CAP = 400


class FtSalesDashboard(models.TransientModel):
    _name = 'ft.sales.dashboard'
    _description = 'Sales Dashboard data provider'

    # ------------------------------------------------------------------
    # Domain helpers
    # ------------------------------------------------------------------
    def _date_domain(self, field, date_from, date_to):
        """Inclusive range on a Date or Datetime field.

        ``date_deadline`` is a Date and ``date_closed`` a Datetime, so the time
        component is only appended for the latter — comparing a Date against
        '2026-07-31 23:59:59' silently matches nothing on some backends.
        """
        is_datetime = self.env['crm.lead']._fields[field].type == 'datetime'
        dom = []
        if date_from:
            dom.append((field, '>=', date_from + ' 00:00:00' if is_datetime else date_from))
        if date_to:
            dom.append((field, '<=', date_to + ' 23:59:59' if is_datetime else date_to))
        return dom

    def _opp_domain(self):
        return [('type', '=', 'opportunity')]

    def _open_domain(self):
        """Still in play: live and not yet in a won stage."""
        return [('active', '=', True), ('stage_id.is_won', '=', False)]

    def _won_domain(self):
        return [('active', '=', True), ('stage_id.is_won', '=', True)]

    def _lost_domain(self):
        """Lost = archived (action_set_lost calls action_archive)."""
        return [('active', '=', False)]

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    @api.model
    def get_dashboard_data(self, date_from=None, date_to=None):
        """Every KPI, table and chart for the Sales dashboard.

        Everything except the three rolling month charts responds to the
        selected period; those are fixed windows by definition (see
        ``_chart_pipeline_next_months`` / ``_chart_by_month``).
        """
        opp = self._opp_domain()
        # One field for everything — see PERIOD_FIELD.
        period = opp + self._date_domain(PERIOD_FIELD, date_from, date_to)
        outcome = opp + self._date_domain(OUTCOME_FIELD, date_from, date_to)

        today = fields.Date.context_today(self)
        ahead = self._month_buckets(today, MONTHS_AHEAD)
        back = self._month_buckets(
            today.replace(day=1) - relativedelta(months=MONTHS_BACK - 1), MONTHS_BACK)

        return {
            'kpis': self._kpis(period, outcome),
            'charts': {
                # The stage picture is the funnel only. A separate
                # "revenue by stage" bar chart showed the same figures a second
                # time, so it was removed rather than kept as a duplicate.
                'funnel': self._chart_funnel(period),
            },
            'boards': {
                # Trailing pipeline is what the spec asks for; the forward view
                # is kept alongside it because a pipeline that only looks
                # backwards cannot answer "what is coming". The front end
                # toggles between the two on one card.
                'pipeline_last_months': self._month_board(
                    opp + self._open_domain(), PERIOD_FIELD, back, '#4F46E5'),
                'pipeline_next_months': self._month_board(
                    opp + self._open_domain(), PERIOD_FIELD, ahead, '#06B6D4'),
                'closed_last_months': self._month_board(
                    opp + self._won_domain(), OUTCOME_FIELD, back, '#10B981'),
                'lost_last_months': self._month_board(
                    opp + self._lost_domain(), OUTCOME_FIELD, back, '#EF4444',
                    active_test=False),
            },
            'executives': self._executive_report(period),
        }

    # ------------------------------------------------------------------
    # KPIs
    # ------------------------------------------------------------------
    def _kpis(self, period, outcome):
        Lead = self.env['crm.lead']

        generated = Lead.search_count(period)

        # Pipeline Value: Expected Revenue of everything still open whose
        # Expected Closing falls in the period. Previously this summed by
        # creation date, which is why it never moved with the filter.
        pipeline_value = self._sum_revenue(period + self._open_domain())

        # Sales Closed / Lost: same period field as everything else, so the
        # conversion ratio below divides two numbers drawn from one population.
        # Dating these by create_date made them static; dating them by
        # date_closed made them disagree with the rest of the dashboard.
        won_domain = outcome + self._won_domain()
        sales_closed = Lead.search_count(won_domain)
        sales_closed_value = self._sum_closed_amount(won_domain)

        lost = Lead.search_count(outcome + self._lost_domain())

        # Conversion over the same population the two numbers come from.
        conversion = round(sales_closed / generated * 100, 1) if generated else 0.0

        return {
            'opportunities': generated,
            'pipeline_value': pipeline_value,
            'sales_closed': sales_closed,
            'sales_closed_value': sales_closed_value,
            'opportunities_lost': lost,
            'conversion_ratio': conversion,
        }

    def _sum(self, domain, field):
        """SUM(field) over a domain in a single aggregate query."""
        groups = self.env['crm.lead'].read_group(domain, [f'{field}:sum'], [], lazy=False)
        return sum(g.get(field) or 0.0 for g in groups)

    def _sum_revenue(self, domain):
        """SUM(expected_revenue) — the pipeline figure."""
        return round(self._sum(domain, 'expected_revenue'), 2)

    def _sum_closed_amount(self, domain):
        """SUM of Closed Amount, falling back to Expected Revenue per record.

        ``revenue`` (Closed Amount) is only filled on some won records, so a
        plain SUM(revenue) under-reports. Split into two aggregate queries —
        records that have a closed amount, and those that do not — instead of
        looping records, so cost stays flat as the pipeline grows.
        """
        has_revenue = self._sum(domain + [('revenue', '!=', 0)], 'revenue')
        no_revenue = self._sum(domain + [('revenue', '=', 0)], 'expected_revenue')
        return round(has_revenue + no_revenue, 2)

    # ------------------------------------------------------------------
    # Stage charts
    # ------------------------------------------------------------------
    def _stage_groups(self, domain):
        """Expected Revenue + count per stage, ordered by the CRM stage flow.

        Sorted by crm.stage.sequence rather than by value so the funnel reads
        as the pipeline (Cold -> Discussion -> ... -> Won). Stages with no
        sequence and the 'Undefined' bucket sort last.
        """
        groups = self.env['crm.lead'].read_group(
            domain, ['expected_revenue:sum'], ['stage_id'], lazy=False)
        seq_by_stage = {
            s.id: s.sequence
            for s in self.env['crm.stage'].browse(
                [g['stage_id'][0] for g in groups if g.get('stage_id')])
        }
        groups.sort(key=lambda g: seq_by_stage.get(
            g['stage_id'][0] if g.get('stage_id') else False, 10 ** 6))
        return groups

    def _chart_funnel(self, base_domain):
        """Sales funnel by Expected Revenue (not opportunity count).

        Bands are stages — that is what makes it a funnel — but the value shown
        and the band width are now Expected Revenue, and the period filter is
        Expected Closing. Won/lost stages are included so the funnel shows the
        whole flow; only archived (lost) records drop out.
        """
        groups = self._stage_groups(base_domain + [('active', '=', True)])
        labels = [g['stage_id'][1] if g.get('stage_id') else 'Undefined' for g in groups]
        values = [round(g.get('expected_revenue') or 0.0, 2) for g in groups]
        counts = [g['__count'] for g in groups]
        stage_ids = [g['stage_id'][0] if g.get('stage_id') else False for g in groups]
        return {
            'labels': labels,
            'stage_ids': stage_ids,
            'counts': counts,
            'datasets': [{
                'label': 'Expected Revenue',
                'data': values,
                'backgroundColor': PALETTE[:len(values)] or ['#4F46E5'],
            }],
        }

    # ------------------------------------------------------------------
    # Month-window charts
    # ------------------------------------------------------------------
    def _month_buckets(self, start, count):
        """``count`` consecutive month starts from ``start`` (a date)."""
        first = start.replace(day=1)
        return [first + relativedelta(months=i) for i in range(count)]

    def _month_board(self, domain, date_field, buckets, color, active_test=True):
        """Month cards carrying both the totals and the deals behind them.

        Replaces the plain bar chart these three views used to be. A bar says
        "how much" but never "which"; a flat table of six months of records
        buries the trend. Each month returns its total, its count and the
        largest few opportunities, so the shape and the detail are readable at
        once and every number can be opened.

        Totals come from ``read_group`` and are always exact. The inline list
        is a separate fetch, ordered by value and capped, so one huge month
        cannot pull the whole table into memory — anything past
        ``LIST_PER_MONTH`` is reported as ``more`` and reached via drill-down.

        ``active_test=False`` is required for the Lost board: lost leads are
        archived, and the default ORM filter would return an empty set.
        """
        Lead = self.env['crm.lead']
        if not active_test:
            Lead = Lead.with_context(active_test=False)

        is_datetime = Lead._fields[date_field].type == 'datetime'

        def month_key(value):
            """YYYY-MM of ``value`` as the USER sees it.

            read_group groups a Datetime in the user's timezone but reports
            __range in UTC, so for any timezone ahead of UTC the month start
            comes back as the previous month (IST: March -> 2026-02-28 18:30).
            Slicing that string put every total on the wrong card while the
            record list, which is bucketed from the record's own date, stayed
            correct. Converting to the user's timezone first is what keeps the
            two in step. Date fields carry no timezone and pass through.
            """
            if not value:
                return None
            if is_datetime:
                dt = fields.Datetime.to_datetime(value)
                return fields.Datetime.context_timestamp(self, dt).strftime('%Y-%m')
            return str(value)[:7]

        # Widen the fetch by a day at each end: the bounds below are naive while
        # bucketing is timezone-aware, so a record within a few hours of a
        # boundary would otherwise be dropped before it could be bucketed.
        # Anything landing outside the six buckets is ignored when mapping, so
        # the wider window cannot inflate a total.
        window = domain + [
            (date_field, '>=', fields.Date.to_string(
                buckets[0] - relativedelta(days=1))),
            (date_field, '<', fields.Date.to_string(
                buckets[-1] + relativedelta(months=1, days=1))),
        ]

        # --- exact totals -------------------------------------------------
        # Buckets are built in Python so an empty month still shows a card;
        # read_group only returns months that have rows.
        totals = {}
        for group in Lead.read_group(
                window, ['expected_revenue:sum'], [f'{date_field}:month'], lazy=False):
            rng = (group.get('__range') or {}).get(f'{date_field}:month')
            key = month_key(rng['from']) if rng else None
            if not key:
                continue
            totals[key] = {
                'amount': round(group.get('expected_revenue') or 0.0, 2),
                'count': group['__count'],
            }

        # --- the deals themselves ----------------------------------------
        records = Lead.search_read(
            window,
            ['name', 'partner_id', 'expected_revenue', 'user_id', date_field],
            order='expected_revenue desc, id desc',
            limit=FETCH_CAP,
        )
        by_month = {}
        for rec in records:
            value = rec.get(date_field)
            key = month_key(value)
            if not key:
                continue
            # Display the date in the user's timezone too, so a deal closed
            # late in the evening is not shown under the previous day.
            if is_datetime:
                shown = fields.Datetime.context_timestamp(
                    self, fields.Datetime.to_datetime(value)).strftime('%Y-%m-%d')
            else:
                shown = str(value)[:10]
            by_month.setdefault(key, []).append({
                'id': rec['id'],
                'name': rec['name'],
                'partner': rec['partner_id'][1] if rec.get('partner_id') else '',
                'user': rec['user_id'][1] if rec.get('user_id') else 'Unassigned',
                'amount': round(rec.get('expected_revenue') or 0.0, 2),
                'date': shown,
            })

        months = []
        for bucket in buckets:
            key = bucket.strftime('%Y-%m')
            total = totals.get(key) or {'amount': 0.0, 'count': 0}
            items = by_month.get(key, [])[:LIST_PER_MONTH]
            months.append({
                'key': key,
                'label': bucket.strftime('%b %Y'),
                'short': bucket.strftime('%b'),
                'year': bucket.strftime('%Y'),
                'amount': total['amount'],
                'count': total['count'],
                'items': items,
                'more': max(total['count'] - len(items), 0),
            })

        # Shared scale so the bars compare across months rather than each
        # month rescaling to itself.
        return {
            'months': months,
            'max_amount': max([m['amount'] for m in months] or [0.0]),
            'total_amount': round(sum(m['amount'] for m in months), 2),
            'total_count': sum(m['count'] for m in months),
            'color': color,
            'date_field': date_field,
        }

    # ------------------------------------------------------------------
    # Executive-wise report
    # ------------------------------------------------------------------
    def _executive_report(self, base_domain):
        """Per-salesperson count, Expected Revenue and conversion ratio.

        Three read_groups for the whole table regardless of how many
        salespeople exist — never one query per executive.

        Conversion = won / assigned x 100, both measured over the SAME
        population (the period's Expected Closing). Mixing populations — e.g.
        wins by close date against assignments by expected close — produces
        ratios above 100% and is why this is computed here rather than reusing
        the global KPI.
        """
        Lead = self.env['crm.lead']

        def by_user(domain, value_field=None):
            fields_ = [f'{value_field}:sum'] if value_field else []
            out = {}
            for group in Lead.read_group(domain, fields_, ['user_id'], lazy=False):
                uid = group['user_id'][0] if group.get('user_id') else False
                name = group['user_id'][1] if group.get('user_id') else 'Unassigned'
                out[uid] = {
                    'name': name,
                    'value': (round(group.get(value_field) or 0.0, 2) if value_field
                              else group['__count']),
                }
            return out

        counts = by_user(base_domain)
        amounts = by_user(base_domain, value_field='expected_revenue')
        won = by_user(base_domain + self._won_domain())

        rows = []
        for uid, entry in counts.items():
            total = entry['value']
            won_count = won.get(uid, {}).get('value', 0)
            rows.append({
                'user_id': uid,
                'name': entry['name'],
                'count': total,
                'amount': amounts.get(uid, {}).get('value', 0.0),
                'won': won_count,
                'conversion': round(won_count / total * 100, 1) if total else 0.0,
            })
        # Biggest pipeline first: the ordering a sales manager reads top-down.
        rows.sort(key=lambda r: r['amount'], reverse=True)
        return rows
