from odoo import api, models

# Consistent palette shared across the dashboard charts.
PALETTE = [
    '#4F46E5', '#06B6D4', '#10B981', '#F59E0B', '#EF4444',
    '#8B5CF6', '#EC4899', '#14B8A6', '#F97316', '#3B82F6',
]


class FtSalesDashboard(models.TransientModel):
    _name = 'ft.sales.dashboard'
    _description = 'Sales Dashboard data provider'

    # ------------------------------------------------------------------
    def _date_domain(self, field, date_from, date_to):
        dom = []
        if date_from:
            dom.append((field, '>=', date_from + ' 00:00:00'))
        if date_to:
            dom.append((field, '<=', date_to + ' 23:59:59'))
        return dom

    # ------------------------------------------------------------------
    @api.model
    def get_dashboard_data(self, date_from=None, date_to=None):
        """KPIs + chart datasets for the Sales dashboard.

        Opportunities are crm.lead records with type='opportunity'.
        Won is detected via the stage's is_won flag.
        """
        Lead = self.env['crm.lead']
        opp = [('type', '=', 'opportunity')]
        created = self._date_domain('create_date', date_from, date_to)

        # Opportunities generated in the period
        generated = Lead.search_count(opp + created)

        # Open pipeline value (created in period, still open)
        pipeline_value = sum(
            g['expected_revenue'] for g in Lead.read_group(
                opp + created + [('active', '=', True), ('stage_id.is_won', '=', False)],
                ['expected_revenue:sum'], []) if g.get('expected_revenue'))

        # Won opportunities (created in period)
        won = Lead.search(opp + created + [('stage_id.is_won', '=', True)])
        sales_closed = len(won)
        # "Closed Amount" custom field, falling back to expected_revenue.
        sales_closed_value = sum((lead.revenue or lead.expected_revenue) for lead in won)

        conversion = round(sales_closed / generated * 100, 1) if generated else 0.0

        return {
            'kpis': {
                'opportunities': generated,
                'pipeline_value': round(pipeline_value, 2),
                'sales_closed': sales_closed,
                'sales_closed_value': round(sales_closed_value, 2),
                'conversion_ratio': conversion,
            },
            'charts': {
                'funnel': self._chart_funnel(opp + created),
                'pipeline_by_stage': self._chart_pipeline_by_stage(opp + created),
            },
        }

    # ------------------------------------------------------------------
    def _chart_funnel(self, base_domain):
        """Opportunity count per stage (the sales funnel).

        Bands follow the configured CRM stage sequence (Cold -> Discussion ->
        ... -> Won -> Lost), not the opportunity count, so the funnel reads as
        the pipeline flow. Stages without a sequence match / the 'Undefined'
        group sort last.
        """
        groups = self.env['crm.lead'].read_group(
            base_domain + [('active', '=', True)],
            ['expected_revenue:sum'], ['stage_id'], lazy=False)
        seq_by_stage = {
            s.id: s.sequence
            for s in self.env['crm.stage'].browse(
                [g['stage_id'][0] for g in groups if g.get('stage_id')])
        }
        groups.sort(key=lambda g: seq_by_stage.get(
            g['stage_id'][0] if g.get('stage_id') else False, 10 ** 6))
        labels = [g['stage_id'][1] if g.get('stage_id') else 'Undefined' for g in groups]
        counts = [g['__count'] for g in groups]
        # Stage id per band (False for the "Undefined" group) so the front-end
        # can open exactly that stage's opportunities on click.
        stage_ids = [g['stage_id'][0] if g.get('stage_id') else False for g in groups]
        return {
            'labels': labels,
            'stage_ids': stage_ids,
            'datasets': [{
                'label': 'Opportunities',
                'data': counts,
                'backgroundColor': PALETTE[:len(counts)] or ['#4F46E5'],
            }],
        }

    def _chart_pipeline_by_stage(self, base_domain):
        """Open pipeline value per stage."""
        groups = self.env['crm.lead'].read_group(
            base_domain + [('active', '=', True), ('stage_id.is_won', '=', False)],
            ['expected_revenue:sum'], ['stage_id'], lazy=False)
        labels = [g['stage_id'][1] if g.get('stage_id') else 'Undefined' for g in groups]
        values = [round(g.get('expected_revenue') or 0.0, 2) for g in groups]
        return {
            'labels': labels,
            'datasets': [{
                'label': 'Pipeline Value',
                'data': values,
                'backgroundColor': '#4F46E5',
            }],
        }
