/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";
import { KpiCard } from "./kpi_card";
import { ChartCard } from "./chart_card";

const PERIODS = [
    { id: "today", label: "Today" },
    { id: "week", label: "This Week" },
    { id: "month", label: "This Month" },
    { id: "quarter", label: "This Quarter" },
    { id: "year", label: "This Year" },
    { id: "custom", label: "Custom" },
];

function fmt(date) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
}

export class SalesDashboard extends Component {
    static template = "ft_sales_dashboard.SalesDashboard";
    static components = { KpiCard, ChartCard };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.periods = PERIODS;
        this.state = useState({
            period: "month",
            dateFrom: null,
            dateTo: null,
            data: null,
            loading: true,
        });

        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            this._applyPeriod("month");
            await this.loadData();
        });
    }

    _applyPeriod(period) {
        const now = new Date();
        let from = null;
        let to = fmt(now);
        switch (period) {
            case "today":
                from = fmt(now);
                break;
            case "week": {
                const d = new Date(now);
                const day = (d.getDay() + 6) % 7;
                d.setDate(d.getDate() - day);
                from = fmt(d);
                break;
            }
            case "month":
                from = fmt(new Date(now.getFullYear(), now.getMonth(), 1));
                break;
            case "quarter": {
                const q = Math.floor(now.getMonth() / 3);
                from = fmt(new Date(now.getFullYear(), q * 3, 1));
                break;
            }
            case "year":
                from = fmt(new Date(now.getFullYear(), 0, 1));
                break;
            case "custom":
                from = this.state.dateFrom;
                to = this.state.dateTo;
                break;
        }
        this.state.period = period;
        this.state.dateFrom = from;
        this.state.dateTo = to;
    }

    async onPeriodChange(period) {
        this._applyPeriod(period);
        if (period !== "custom") {
            await this.loadData();
        }
    }

    onCustomDateChange(field, ev) {
        this.state[field] = ev.target.value || null;
    }

    async applyCustomRange() {
        this.state.period = "custom";
        await this.loadData();
    }

    async loadData() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call(
                "ft.sales.dashboard",
                "get_dashboard_data",
                [this.state.dateFrom, this.state.dateTo]
            );
        } finally {
            this.state.loading = false;
        }
    }

    async refresh() {
        await this.loadData();
    }

    // Drill-downs
    _openLeads(domain, name) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: name || "Opportunities",
            res_model: "crm.lead",
            views: [[false, "list"], [false, "form"]],
            domain: domain || [],
            target: "current",
        });
    }

    openOpportunities() {
        this._openLeads([["type", "=", "opportunity"]], "Opportunities");
    }
    openWon() {
        this._openLeads(
            [["type", "=", "opportunity"], ["stage_id.is_won", "=", true]],
            "Won Opportunities"
        );
    }

    get kpis() {
        return this.state.data?.kpis || {};
    }
    get charts() {
        return this.state.data?.charts || {};
    }

    // Horizontal-bar options for the funnel
    get funnelOptions() {
        return {
            indexAxis: "y",
            plugins: { legend: { display: false } },
            scales: {
                x: { beginAtZero: true, grid: { color: "rgba(0,0,0,0.05)" } },
                y: { grid: { display: false } },
            },
        };
    }
}

registry.category("actions").add("ft_sales_dashboard", SalesDashboard);
