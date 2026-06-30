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
    // -> 'YYYY-MM-DD' in local time.
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
}

export class ProjectDashboard extends Component {
    static template = "ft_project_dashboard.ProjectDashboard";
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

    // ----------------------------------------------------------------
    // Date range handling
    // ----------------------------------------------------------------
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
                const day = (d.getDay() + 6) % 7; // Monday = 0
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
                // Keep whatever is already in the custom inputs.
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

    // ----------------------------------------------------------------
    // Data loading
    // ----------------------------------------------------------------
    async loadData() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call(
                "ft.project.dashboard",
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

    // ----------------------------------------------------------------
    // Drill-downs
    // ----------------------------------------------------------------
    _openProjects(domain, name) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: name || "Projects",
            res_model: "project.project",
            views: [[false, "list"], [false, "form"]],
            domain: domain || [],
            target: "current",
        });
    }

    openActiveProjects() {
        this._openProjects(
            [["active", "=", true], ["status", "not in", ["closed"]]],
            "Active Projects"
        );
    }

    openTimesheets(billableOnly) {
        const domain = [["project_id", "!=", false]];
        if (this.state.dateFrom) domain.push(["date", ">=", this.state.dateFrom]);
        if (this.state.dateTo) domain.push(["date", "<=", this.state.dateTo]);
        if (billableOnly) domain.push(["project_id.allow_billable", "=", true]);
        this.action.doAction({
            type: "ir.actions.act_window",
            name: billableOnly ? "Billable Timesheets" : "Timesheets",
            res_model: "account.analytic.line",
            views: [[false, "list"], [false, "form"]],
            domain,
            target: "current",
        });
    }

    onStatusSegment(index) {
        const meta = this.state.data?.charts?.project_status?.meta;
        const key = meta?.keys?.[index];
        if (key !== undefined) {
            this._openProjects(
                [["active", "=", true], ["status", "=", key]],
                "Projects"
            );
        }
    }

    onProjectHoursSegment(index) {
        const ids = this.state.data?.charts?.project_hours?.meta?.project_ids;
        const pid = ids?.[index];
        if (pid) {
            this.action.doAction({
                type: "ir.actions.act_window",
                res_model: "project.project",
                res_id: pid,
                views: [[false, "form"]],
                target: "current",
            });
        }
    }

    // Convenience getters for the template
    get kpis() {
        return this.state.data?.kpis || {};
    }
    get charts() {
        return this.state.data?.charts || {};
    }

    // Stacked bar options for the Resource Status chart.
    get stackedOptions() {
        return {
            scales: {
                x: { stacked: true, grid: { display: false } },
                y: { stacked: true, beginAtZero: true, grid: { color: "rgba(0,0,0,0.05)" } },
            },
        };
    }

    // Dual-axis options for the Progress Trend line chart.
    get trendOptions() {
        return {
            interaction: { mode: "index", intersect: false },
            scales: {
                x: { grid: { display: false } },
                y: {
                    type: "linear", position: "left", beginAtZero: true,
                    title: { display: true, text: "Hours" },
                },
                y1: {
                    type: "linear", position: "right", beginAtZero: true,
                    grid: { drawOnChartArea: false },
                    title: { display: true, text: "Tasks" },
                },
            },
        };
    }
}

registry.category("actions").add("ft_project_dashboard", ProjectDashboard);
