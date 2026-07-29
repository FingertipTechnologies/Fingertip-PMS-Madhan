/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { browser } from "@web/core/browser/browser";
import { loadJS } from "@web/core/assets";
import { KpiCard } from "./kpi_card";
import { ChartCard } from "./chart_card";
import { DataTable } from "./data_table";

const PERIODS = [
    { id: "today", label: "Today" },
    { id: "week", label: "This Week" },
    { id: "month", label: "This Month" },
    { id: "quarter", label: "This Quarter" },
    { id: "year", label: "This Year" },
    { id: "custom", label: "Custom" },
];

const DEFAULT_PERIOD = "month";

// Drilling into a card opens a list view as a new action; coming back rebuilds
// this dashboard from scratch, which reset the period to the default and threw
// away the selection. Mirror it into sessionStorage so the round trip returns to
// the period the user was actually looking at. Only the period/range is stored —
// the data itself is always refetched, so nothing stale is shown.
const PERIOD_KEY = "ft_project_dashboard.period";

function readStoredPeriod() {
    try {
        const stored = JSON.parse(browser.sessionStorage.getItem(PERIOD_KEY) || "null");
        // Guard against a stale key from an older build naming a period that no
        // longer exists, which would leave the dashboard with no range at all.
        if (stored && PERIODS.some((p) => p.id === stored.period)) {
            return stored;
        }
    } catch {
        // Unreadable/corrupt storage: fall back to the default period.
    }
    return null;
}

function writeStoredPeriod(period, dateFrom, dateTo) {
    try {
        browser.sessionStorage.setItem(
            PERIOD_KEY, JSON.stringify({ period, dateFrom, dateTo })
        );
    } catch {
        // Storage unavailable/full: the period just won't persist.
    }
}

function fmt(date) {
    // -> 'YYYY-MM-DD' in local time.
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
}

export class ProjectDashboard extends Component {
    static template = "ft_project_dashboard.ProjectDashboard";
    static components = { KpiCard, ChartCard, DataTable };
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
            projectSearch: "",
            projectStatus: "",
            projectDateFrom: null,
            projectDateTo: null,
            resourceSearch: "",
            resourceProjectSearch: "",
            resourceDateFrom: null,
            resourceDateTo: null,
            // Rows recomputed by the server for the resource table's own date
            // range. Null means "no range set" -> fall back to the rows the
            // top period filter already delivered.
            resourceRowsOverride: null,
            projectHoursSearch: "",
            deliverySearch: "",
            deliveryDateFrom: null,
            deliveryDateTo: null,
            // Same contract as resourceRowsOverride: rows the server recomputed
            // for this table's own range, or null for the all-time rows that
            // came with the dashboard payload.
            deliveryRowsOverride: null,
            // Hours Utilisation has its own filters, independent of the period
            // bar at the top. hoursOverride null means "no filter applied" ->
            // show the unfiltered totals that came with the payload.
            hoursDateFrom: null,
            hoursDateTo: null,
            hoursProjectId: "",
            hoursStageId: "",
            hoursPmId: "",
            hoursDevId: "",
            hoursOverride: null,
            hoursLoading: false,
            hoursOptions: { projects: [], stages: [], project_managers: [], developers: [] },
            // Tasks Summary carries the same filter shape as Hours Utilisation
            // but its own values, so the two sections can be sliced apart.
            tasksDateFrom: null,
            tasksDateTo: null,
            tasksProjectId: "",
            tasksStageId: "",
            tasksPmId: "",
            tasksDevId: "",
            tasksOverride: null,
            tasksLoading: false,
            // Task Hours Summary — same filter shape again, own values.
            taskHoursDateFrom: null,
            taskHoursDateTo: null,
            taskHoursProjectId: "",
            taskHoursStageId: "",
            taskHoursPmId: "",
            taskHoursDevId: "",
            taskHoursOverride: null,
            taskHoursLoading: false,
        });

        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            const restored = readStoredPeriod();
            if (restored?.period === "custom") {
                // _applyPeriod's "custom" branch reads the dates back off state,
                // so they must be in place before it runs.
                this.state.dateFrom = restored.dateFrom;
                this.state.dateTo = restored.dateTo;
            }
            // Named periods are recomputed against today rather than restored
            // from the stored dates: coming back to "This Year" should mean this
            // year now, not the year it was when the range was first picked.
            this._applyPeriod(restored?.period || DEFAULT_PERIOD);
            await this.loadData();
            // Filter choices are independent of the period, so they are fetched
            // once. A failure here only costs empty dropdowns, never the board.
            try {
                this.state.hoursOptions = await this.orm.call(
                    "ft.project.dashboard", "get_hours_filter_options", []
                );
            } catch (e) {
                console.warn("Hours filter options failed to load", e);
            }
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
        writeStoredPeriod(period, from, to);
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
        // Set directly rather than via _applyPeriod, so persist here too.
        writeStoredPeriod("custom", this.state.dateFrom, this.state.dateTo);
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

    // Generic KPI drill-down: opens the record list the server prepared for
    // this card, so the list length always equals the number on the card. No-op
    // for cards with no backing records (sums, N/A) — those pass no action.
    openKpi(key) {
        const action = this.kpis.actions && this.kpis.actions[key];
        if (!action) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: action.name,
            res_model: action.res_model,
            views: [[false, "list"], [false, "form"]],
            domain: action.domain || [],
            target: "current",
        });
    }

    /** Drill-down for a Tasks Summary card.
     *
     *  Reads from `tasks` rather than `kpis` so a filtered section opens the
     *  filtered list: when a filter is active the actions come back with the
     *  refetched figures, so the list always matches the number clicked.
     */
    openTaskKpi(key) {
        const action = this.tasks.actions && this.tasks.actions[key];
        if (!action) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: action.name,
            res_model: action.res_model,
            views: [[false, "list"], [false, "form"]],
            domain: action.domain || [],
            target: "current",
        });
    }

    onProjectHoursSegment(index) {
        const ids = this.projectHoursData?.meta?.project_ids;
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
    // Column definitions for the two full-width tables. DataTable handles
    // sorting / pagination / rows-per-page / scroll from these.
    // ----------------------------------------------------------------
    // Project Performance. Existing columns kept; DE / OTD / RWR / DWD added,
    // same four measures as Resource Performance but per project. Delivered
    // rides along as the denominator behind the three percentages.
    get projectColumns() {
        return [
            { key: "project", label: "Project Name" },
            { key: "status", label: "Status" },
            { key: "start_date", label: "Start Date", date: true },
            { key: "uat_date", label: "UAT Date", date: true },
            { key: "end_date", label: "End Date", date: true },
            { key: "estimated", label: "Estimated Hrs", numeric: true },
            { key: "actual", label: "Actual Hrs", numeric: true },
            { key: "delivered", label: "Delivered", numeric: true },
            { key: "de_rate", label: "DE (%)", numeric: true },
            { key: "otd_rate", label: "OTD (%)", numeric: true },
            { key: "rwr_rate", label: "RWR (%)", numeric: true },
            { key: "dwd", label: "DWD", numeric: true },
        ];
    }
    get resourceColumns() {
        return [
            { key: "employee", label: "Resource Name", group: true, cls: "ftpd_res_name" },
            { key: "role", label: "Role", group: true },
            { key: "project", label: "Project Name" },
            { key: "status", label: "Project Status" },
            { key: "days_left", label: "Days Left", numeric: true },
            { key: "hours_spent", label: "Hours Spent", numeric: true },
            { key: "estimated", label: "Estimated Hrs", numeric: true },
        ];
    }

    // Resource Performance: the original counts kept, with the three PM KPIs
    // added alongside them.
    //   DE  (%) = Estimated / Actual                target 90-110%
    //   OTD (%) = On time / Delivered w/ deadline   target >= 95%
    //   RWR (%) = Reopened / Delivered              target <= 10%
    //   DWD     = Delivered Without Deadline — the tasks OTD could not judge
    //
    // Every original column is kept. On-Time % and OTD (%) carry the same
    // number, as do No Deadline and DWD — both pairs are shown because both
    // labels were asked for.
    get deliveryColumns() {
        return [
            { key: "employee", label: "Resource Name", group: true, cls: "ftpd_res_name" },
            { key: "role", label: "Role", group: true },
            { key: "delivered", label: "Delivered", numeric: true },
            { key: "on_time", label: "On Time", numeric: true },
            { key: "late", label: "Late", numeric: true },
            { key: "on_time_rate", label: "On-Time %", numeric: true },
            { key: "no_deadline", label: "No Deadline", numeric: true },
            { key: "de_rate", label: "DE (%)", numeric: true },
            { key: "otd_rate", label: "OTD (%)", numeric: true },
            { key: "rwr_rate", label: "RWR (%)", numeric: true },
            { key: "dwd", label: "DWD", numeric: true },
            { key: "overdue_open", label: "Open & Overdue", numeric: true },
        ];
    }

    // ----------------------------------------------------------------
    // Table search / filters (client-side). Rows arrive sorted from the
    // server; DataTable re-sorts/paginates on top of the filtered set.
    // Dates are ISO 'YYYY-MM-DD' strings, which compare chronologically as
    // plain strings, so a range check is a simple lexicographic comparison.
    // ----------------------------------------------------------------
    get deliveryRows() {
        const q = (this.state.deliverySearch || "").trim().toLowerCase();
        // With a range set the server has recomputed DE / OTD / RWR / DWD for
        // it; without one these are the all-time rows. Either way the top
        // period filter does not reach this table.
        const rows = this.state.deliveryRowsOverride || this.tables.delivery || [];
        if (!q) return rows;
        return rows.filter((r) => (r.employee || "").toLowerCase().includes(q));
    }
    onDeliverySearch(ev) {
        this.state.deliverySearch = ev.target.value || "";
    }
    onDeliveryDateFrom(ev) {
        this.state.deliveryDateFrom = ev.target.value || null;
        this.reloadDeliveryByResource();
    }
    onDeliveryDateTo(ev) {
        this.state.deliveryDateTo = ev.target.value || null;
        this.reloadDeliveryByResource();
    }
    clearDeliveryDates() {
        this.state.deliveryDateFrom = null;
        this.state.deliveryDateTo = null;
        this.state.deliveryRowsOverride = null;
    }
    /** Refetch the delivery rows for this table's own range (both bounds
     *  optional). Clearing both returns the table to all-time. */
    async reloadDeliveryByResource() {
        const from = this.state.deliveryDateFrom;
        const to = this.state.deliveryDateTo;
        if (!from && !to) {
            this.state.deliveryRowsOverride = null;
            return;
        }
        try {
            this.state.deliveryRowsOverride = await this.orm.call(
                "ft.project.dashboard",
                "get_delivery_by_resource",
                [from, to]
            );
        } catch (e) {
            // Keep the last good rows rather than blanking the table.
            console.warn("Delivery by resource reload failed", e);
        }
    }
    _inDateRange(iso, from, to) {
        // Rows without a date are dropped once any bound is active.
        if (!from && !to) return true;
        if (!iso) return false;
        if (from && iso < from) return false;
        if (to && iso > to) return false;
        return true;
    }

    // Distinct project statuses present in the current data, for the
    // Project Status dropdown ("" = All Statuses).
    get projectStatusOptions() {
        const seen = new Set();
        for (const r of this.tables.project_status || []) {
            if (r.status) seen.add(r.status);
        }
        return Array.from(seen).sort((a, b) => a.localeCompare(b));
    }

    get projectRows() {
        const q = (this.state.projectSearch || "").trim().toLowerCase();
        const status = this.state.projectStatus || "";
        const from = this.state.projectDateFrom;
        const to = this.state.projectDateTo;
        let rows = this.tables.project_status || [];
        if (q) {
            rows = rows.filter((r) => (r.project || "").toLowerCase().includes(q));
        }
        if (status) {
            rows = rows.filter((r) => (r.status || "") === status);
        }
        if (from || to) {
            rows = rows.filter((r) => this._inDateRange(r.start_date, from, to));
        }
        return rows;
    }
    onProjectSearch(ev) {
        this.state.projectSearch = ev.target.value || "";
    }
    onProjectStatus(ev) {
        this.state.projectStatus = ev.target.value || "";
    }
    onProjectDateFrom(ev) {
        this.state.projectDateFrom = ev.target.value || null;
    }
    onProjectDateTo(ev) {
        this.state.projectDateTo = ev.target.value || null;
    }
    clearProjectFilters() {
        this.state.projectStatus = "";
        this.state.projectDateFrom = null;
        this.state.projectDateTo = null;
    }

    get resourceRows() {
        const q = (this.state.resourceSearch || "").trim().toLowerCase();
        const pq = (this.state.resourceProjectSearch || "").trim().toLowerCase();
        // With a date range set the server has already recomputed Hours Spent
        // for it; without one the top period filter's rows stand. Either way
        // only the text searches are applied here — dropping rows by date in
        // the browser would leave the figures answering a different period
        // than the dates on screen.
        let rows = this.state.resourceRowsOverride || this.tables.resource_status || [];
        if (q) {
            rows = rows.filter((r) => (r.employee || "").toLowerCase().includes(q));
        }
        if (pq) {
            rows = rows.filter((r) => (r.project || "").toLowerCase().includes(pq));
        }
        return rows;
    }
    onResourceSearch(ev) {
        this.state.resourceSearch = ev.target.value || "";
    }
    onResourceProjectSearch(ev) {
        this.state.resourceProjectSearch = ev.target.value || "";
    }
    onResourceDateFrom(ev) {
        this.state.resourceDateFrom = ev.target.value || null;
        this.reloadResourceStatus();
    }
    onResourceDateTo(ev) {
        this.state.resourceDateTo = ev.target.value || null;
        this.reloadResourceStatus();
    }
    clearResourceDates() {
        this.state.resourceDateFrom = null;
        this.state.resourceDateTo = null;
        this.state.resourceRowsOverride = null;
    }
    /** Refetch the resource rows for this table's own range (both bounds
     *  optional). Clearing both hands the table back to the top filter. */
    async reloadResourceStatus() {
        const from = this.state.resourceDateFrom;
        const to = this.state.resourceDateTo;
        if (!from && !to) {
            this.state.resourceRowsOverride = null;
            return;
        }
        try {
            this.state.resourceRowsOverride = await this.orm.call(
                "ft.project.dashboard",
                "get_resource_status",
                [from, to]
            );
        } catch (e) {
            // Keep the last good rows rather than blanking the table.
            console.warn("Resource status reload failed", e);
        }
    }

    // ----------------------------------------------------------------
    // Hours Utilisation — its own filters, recomputed server-side.
    // ----------------------------------------------------------------
    /** Cards read from here: the filtered figures when a filter is set,
     *  otherwise the unfiltered ones that shipped with the dashboard. */
    get hours() {
        return this.state.hoursOverride || this.kpis;
    }

    /** Compare a dropdown option id with the stored filter value.
     *
     *  Lives here rather than inline in the template because Owl resolves bare
     *  identifiers against the component, so JS globals like String() are not
     *  callable from a template expression. Option ids arrive as numbers and
     *  select values as strings, hence the coercion.
     */
    isHoursFilterSelected(optionId, current) {
        return String(optionId) === String(current);
    }

    get hasHoursFilter() {
        return this._hasFilter("hours");
    }

    get hasTasksFilter() {
        return this._hasFilter("tasks");
    }

    get hasTaskHoursFilter() {
        return this._hasFilter("taskHours");
    }

    get taskHours() {
        return this.state.taskHoursOverride || this.kpis;
    }

    /** Cards read from here: the filtered figures when a filter is set,
     *  otherwise the unfiltered ones that shipped with the dashboard. */
    get tasks() {
        return this.state.tasksOverride || this.kpis;
    }

    // Both filter bars share a shape (from/to + project/stage/pm/dev), so the
    // plumbing is written once and keyed by prefix rather than twice.
    _filterFields(prefix) {
        return [`${prefix}DateFrom`, `${prefix}DateTo`, `${prefix}ProjectId`,
                `${prefix}StageId`, `${prefix}PmId`, `${prefix}DevId`];
    }

    _hasFilter(prefix) {
        return this._filterFields(prefix).some((f) => !!this.state[f]);
    }

    _filterPayload(prefix) {
        const s = this.state;
        return {
            date_from: s[`${prefix}DateFrom`],
            date_to: s[`${prefix}DateTo`],
            project_id: s[`${prefix}ProjectId`],
            stage_id: s[`${prefix}StageId`],
            pm_id: s[`${prefix}PmId`],
            dev_id: s[`${prefix}DevId`],
        };
    }

    onHoursFilter(field, ev) {
        this.state[field] = ev.target.value || (field.endsWith("Id") ? "" : null);
        this.reloadHoursUtilisation();
    }

    onTasksFilter(field, ev) {
        this.state[field] = ev.target.value || (field.endsWith("Id") ? "" : null);
        this.reloadTasksSummary();
    }

    onTaskHoursFilter(field, ev) {
        this.state[field] = ev.target.value || (field.endsWith("Id") ? "" : null);
        this.reloadTaskHoursSummary();
    }

    clearHoursFilters() {
        this._clearFilters("hours");
    }

    clearTaskHoursFilters() {
        this._clearFilters("taskHours");
    }

    async reloadTaskHoursSummary() {
        await this._reloadSection("taskHours", "get_task_hours_summary");
    }

    clearTasksFilters() {
        this._clearFilters("tasks");
    }

    _clearFilters(prefix) {
        for (const f of this._filterFields(prefix)) {
            this.state[f] = f.endsWith("Id") ? "" : null;
        }
        this.state[`${prefix}Override`] = null;
    }

    async reloadHoursUtilisation() {
        await this._reloadSection("hours", "get_hours_utilisation");
    }

    async reloadTasksSummary() {
        await this._reloadSection("tasks", "get_tasks_summary");
    }

    /** Refetch one section for its own filters. No filter set hands the
     *  section back to the unfiltered payload rather than calling the server. */
    async _reloadSection(prefix, method) {
        if (!this._hasFilter(prefix)) {
            this.state[`${prefix}Override`] = null;
            return;
        }
        this.state[`${prefix}Loading`] = true;
        try {
            this.state[`${prefix}Override`] = await this.orm.call(
                "ft.project.dashboard", method, [this._filterPayload(prefix)]
            );
        } catch (e) {
            // Keep the last good figures rather than blanking the cards.
            console.warn(`${prefix} section reload failed`, e);
        } finally {
            this.state[`${prefix}Loading`] = false;
        }
    }

    // ----------------------------------------------------------------
    // Project Hours Analysis chart — search filter + horizontal scroll.
    // ----------------------------------------------------------------
    get projectHoursData() {
        const d = this.charts.project_hours;
        if (!d || !d.labels) return d || { labels: [], datasets: [] };
        const q = (this.state.projectHoursSearch || "").trim().toLowerCase();
        if (!q) return d;
        const keep = [];
        d.labels.forEach((l, i) => {
            if ((l || "").toLowerCase().includes(q)) keep.push(i);
        });
        const ids = (d.meta && d.meta.project_ids) || [];
        return {
            labels: keep.map((i) => d.labels[i]),
            datasets: d.datasets.map((ds) => ({ ...ds, data: keep.map((i) => ds.data[i]) })),
            meta: { project_ids: keep.map((i) => ids[i]) },
        };
    }
    // Width per project group so many bars scroll horizontally rather than
    // squashing together; a sensible floor keeps a short list full-width.
    get projectHoursMinWidth() {
        const n = (this.projectHoursData.labels || []).length;
        return Math.max(n * 90, 640);
    }
    onProjectHoursSearch(ev) {
        this.state.projectHoursSearch = ev.target.value || "";
    }

    // Dual-axis options for the Progress Trend bar chart. The server buckets the
    // range into days/weeks/months, so every label it sends is meant to be shown.
    get trendOptions() {
        return {
            interaction: { mode: "index", intersect: false },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { autoSkip: false, maxRotation: 45, minRotation: 0 },
                },
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
