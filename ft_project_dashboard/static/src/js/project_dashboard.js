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

// How many rows the Project/Resource tables show before "Show all" is used.
const ROW_LIMIT = 10;

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
        this.rowLimit = ROW_LIMIT;
        this.state = useState({
            period: "month",
            dateFrom: null,
            dateTo: null,
            data: null,
            loading: true,
            projectSearch: "",
            projectShowAll: false,
            resourceSearch: "",
            resourceProjectSearch: "",
            resourceShowAll: false,
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
    get tables() {
        return this.state.data?.tables || {};
    }

    // ----------------------------------------------------------------
    // Project / Resource table search + row limiting (client-side).
    // The rows already arrive sorted alphabetically from the server
    // (project name / resource name).
    // ----------------------------------------------------------------
    // Project Status — filter by company/project name.
    get projectRows() {
        const q = (this.state.projectSearch || "").trim().toLowerCase();
        const rows = this.tables.project_status || [];
        if (!q) return rows;
        return rows.filter((r) => (r.project || "").toLowerCase().includes(q));
    }
    get visibleProjectRows() {
        const rows = this.projectRows;
        return this.state.projectShowAll ? rows : rows.slice(0, this.rowLimit);
    }
    onProjectSearch(ev) {
        this.state.projectSearch = ev.target.value || "";
        this.state.projectShowAll = false;
    }
    toggleProjects() {
        this.state.projectShowAll = !this.state.projectShowAll;
    }

    // Resource Status — filter by resource (employee) name and/or project.
    // Rows stay per (resource, project) so per-project status/data is kept; the
    // template blanks the name/role on repeat rows so each resource shows once.
    get resourceRows() {
        const q = (this.state.resourceSearch || "").trim().toLowerCase();
        const pq = (this.state.resourceProjectSearch || "").trim().toLowerCase();
        let rows = this.tables.resource_status || [];
        if (q) {
            rows = rows.filter((r) => (r.employee || "").toLowerCase().includes(q));
        }
        if (pq) {
            rows = rows.filter((r) => (r.project || "").toLowerCase().includes(pq));
        }
        return rows;
    }
    get visibleResourceRows() {
        const rows = this.state.resourceShowAll
            ? this.resourceRows
            : this.resourceRows.slice(0, this.rowLimit);
        // Flag the first row of each resource group so the resource name/role
        // render only once — consecutive rows for the same person read as one
        // consolidated entry with no duplicate names.
        let prev = null;
        const mapped = rows.map((r) => {
            const firstOfGroup = r.employee !== prev;
            prev = r.employee;
            return { ...r, firstOfGroup };
        });
        // Flag rows that are NOT the last of their group so the template can drop
        // the divider between rows of the same resource (keeping it between
        // different resources).
        mapped.forEach((r, i) => {
            r.midGroup = i < mapped.length - 1 && mapped[i + 1].employee === r.employee;
        });
        return mapped;
    }
    // Count of distinct resources across the current (filtered) rows.
    get resourceCount() {
        return new Set(this.resourceRows.map((r) => r.employee)).size;
    }
    onResourceSearch(ev) {
        this.state.resourceSearch = ev.target.value || "";
        this.state.resourceShowAll = false;
    }
    onResourceProjectSearch(ev) {
        this.state.resourceProjectSearch = ev.target.value || "";
        this.state.resourceShowAll = false;
    }
    toggleResources() {
        this.state.resourceShowAll = !this.state.resourceShowAll;
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
