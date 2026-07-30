/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";
import { browser } from "@web/core/browser/browser";
import { loadJS } from "@web/core/assets";
import { KpiCard } from "./kpi_card";
import { ChartCard } from "./chart_card";
import { FunnelChart } from "./funnel_chart";
import { TableCard } from "./table_card";
import { MonthBoard } from "./month_board";

// Each month board and the domain a click on one of its months should open.
// Keeps the drill-down in step with what the server counted for that board.
const BOARD_DOMAINS = {
    pipeline_last_months: {
        name: "Pipeline",
        domain: [["active", "=", true], ["stage_id.is_won", "=", false]],
    },
    pipeline_next_months: {
        name: "Pipeline",
        domain: [["active", "=", true], ["stage_id.is_won", "=", false]],
    },
    closed_last_months: {
        name: "Won Opportunities",
        domain: [["active", "=", true], ["stage_id.is_won", "=", true]],
    },
    lost_last_months: {
        name: "Lost Opportunities",
        domain: [["active", "=", false]],
        activeTest: false,
    },
};

// The breakdown card shows one of these at a time, chosen from a dropdown.
// Stage-wise and executive-wise answer the same question ("where is the
// revenue?") along different axes, so they share a slot rather than both
// occupying screen height permanently.
const BREAKDOWNS = [
    { id: "stage", label: "Stage-wise" },
    { id: "executive", label: "Executive-wise" },
];

// The pipeline board looks either backwards or forwards over six months.
const PIPELINE_VIEWS = [
    { id: "last", label: "Last 6 Months", key: "pipeline_last_months" },
    { id: "next", label: "Next 6 Months", key: "pipeline_next_months" },
];

// Columns for the executive-wise report. Declared once here rather than inline
// in the template so the table stays a data-driven component.
const EXEC_COLUMNS = [
    { key: "name", label: "Sales Executive", type: "text" },
    { key: "count", label: "Opportunities", type: "number" },
    { key: "amount", label: "Expected Revenue", type: "money" },
    { key: "won", label: "Sales Closed", type: "number" },
    { key: "conversion", label: "Conversion Ratio", type: "percent" },
];

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

// The breadcrumb restores props.state, but the browser Back button rebuilds the
// action from the URL as a brand-new controller with no exported state. Mirror
// the filter into sessionStorage so both routes come back to the same period.
const FILTER_KEY = "ft_sales_dashboard.filter";

function readStoredFilter() {
    try {
        return JSON.parse(browser.sessionStorage.getItem(FILTER_KEY) || "null");
    } catch {
        return null;
    }
}

function writeStoredFilter(filter) {
    try {
        browser.sessionStorage.setItem(FILTER_KEY, JSON.stringify(filter));
    } catch {
        // Storage unavailable/full: filters just won't persist.
    }
}

export class SalesDashboard extends Component {
    static template = "ft_sales_dashboard.SalesDashboard";
    static components = { KpiCard, ChartCard, FunnelChart, TableCard, MonthBoard };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.periods = PERIODS;
        this.execColumns = EXEC_COLUMNS;
        this.breakdowns = BREAKDOWNS;
        this.pipelineViews = PIPELINE_VIEWS;

        // props.state covers the breadcrumb; sessionStorage covers browser Back
        // (which rebuilds the action fresh). Either way we land on the period
        // the user last chose rather than the default.
        const restored = this.props.state || readStoredFilter();
        this.state = useState({
            period: restored?.period || "month",
            dateFrom: restored?.dateFrom ?? null,
            dateTo: restored?.dateTo ?? null,
            // Which axis the breakdown card shows, and which way the pipeline
            // board looks. Restored with the filter so returning via the
            // breadcrumb lands on the same view the user left.
            breakdown: restored?.breakdown || "stage",
            pipelineView: restored?.pipelineView || "last",
            data: null,
            loading: true,
        });

        useSetupAction({
            getLocalState: () => this._filter(),
        });

        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            // Only compute a range on a fresh open; a restored one already has
            // its dates (and recomputing would discard a custom range).
            if (!restored?.period) {
                this._applyPeriod("month");
            }
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

    _filter() {
        return {
            period: this.state.period,
            dateFrom: this.state.dateFrom,
            dateTo: this.state.dateTo,
            breakdown: this.state.breakdown,
            pipelineView: this.state.pipelineView,
        };
    }

    // View switches are presentation only — the payload already carries every
    // breakdown and both pipeline windows, so there is nothing to re-fetch.
    setBreakdown(id) {
        this.state.breakdown = id;
        writeStoredFilter(this._filter());
    }

    setPipelineView(id) {
        this.state.pipelineView = id;
        writeStoredFilter(this._filter());
    }

    get pipelineBoardKey() {
        const view = PIPELINE_VIEWS.find((v) => v.id === this.state.pipelineView);
        return (view || PIPELINE_VIEWS[0]).key;
    }

    get pipelineBoard() {
        return this.boards[this.pipelineBoardKey] || {};
    }

    get pipelineTitle() {
        const view = PIPELINE_VIEWS.find((v) => v.id === this.state.pipelineView);
        return `Opportunity Pipeline — ${(view || PIPELINE_VIEWS[0]).label}`;
    }

    async loadData() {
        // Every load reflects an applied filter, so this is the one choke point
        // where persisting it is always correct.
        writeStoredFilter(this._filter());
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

    // Drill-downs mirror _date_domain on the server, including WHICH date field
    // each figure is measured on — otherwise a drill-down opens a different set
    // of records from the one the KPI counted.

    // Pipeline figures are measured on Expected Closing (a Date, so no time
    // component: comparing a Date against "...23:59:59" matches nothing).
    _deadlineDomain() {
        const domain = [];
        if (this.state.dateFrom) {
            domain.push(["date_deadline", ">=", this.state.dateFrom]);
        }
        if (this.state.dateTo) {
            domain.push(["date_deadline", "<=", this.state.dateTo]);
        }
        return domain;
    }

    // Outcome figures are measured on Closed Date (a Datetime).
    _closedDomain() {
        const domain = [];
        if (this.state.dateFrom) {
            domain.push(["date_closed", ">=", this.state.dateFrom + " 00:00:00"]);
        }
        if (this.state.dateTo) {
            domain.push(["date_closed", "<=", this.state.dateTo + " 23:59:59"]);
        }
        return domain;
    }

    openOpportunities() {
        this._openLeads(
            [["type", "=", "opportunity"], ...this._deadlineDomain()],
            "Opportunities"
        );
    }

    openPipeline() {
        this._openLeads(
            [
                ["type", "=", "opportunity"],
                ["active", "=", true],
                ["stage_id.is_won", "=", false],
                ...this._deadlineDomain(),
            ],
            "Open Pipeline"
        );
    }

    openWon() {
        this._openLeads(
            [
                ["type", "=", "opportunity"],
                ["active", "=", true],
                ["stage_id.is_won", "=", true],
                ...this._closedDomain(),
            ],
            "Won Opportunities"
        );
    }

    openLost() {
        // Lost records are archived, so the action must opt into inactive ones
        // or the list comes back empty.
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Lost Opportunities",
            res_model: "crm.lead",
            views: [[false, "list"], [false, "form"]],
            domain: [
                ["type", "=", "opportunity"],
                ["active", "=", false],
                ...this._closedDomain(),
            ],
            context: { active_test: false },
            target: "current",
        });
    }

    // Click a funnel stage -> open exactly the opportunities it counts:
    // that stage, opportunity type, active, within the selected period
    // (same filter as _chart_funnel on the server).
    openStage(stage) {
        const domain = [
            ["type", "=", "opportunity"],
            ["active", "=", true],
            ["stage_id", "=", stage.stageId || false],
            ...this._deadlineDomain(),
        ];
        this._openLeads(domain, stage.label || "Opportunities");
    }

    // Click an executive row -> their opportunities for the same period.
    openExecutive(row) {
        this._openLeads(
            [
                ["type", "=", "opportunity"],
                ["user_id", "=", row.user_id || false],
                ...this._deadlineDomain(),
            ],
            row.name || "Opportunities"
        );
    }

    // Click a month card -> that month's opportunities for that board. The
    // board's own date field is used (Expected Closing for pipeline, Closed
    // Date for won/lost), so the list matches the number on the card.
    openBoardMonth(boardKey, month) {
        const spec = BOARD_DOMAINS[boardKey];
        const board = this.boards[boardKey] || {};
        const field = board.date_field || "date_deadline";
        // month.key is YYYY-MM; bound with a half-open range so the last day of
        // the month is included whether the field is a Date or a Datetime.
        const [y, m] = month.key.split("-").map(Number);
        const next = m === 12 ? `${y + 1}-01-01` : `${y}-${String(m + 1).padStart(2, "0")}-01`;

        this.action.doAction({
            type: "ir.actions.act_window",
            name: `${spec.name} — ${month.label}`,
            res_model: "crm.lead",
            views: [[false, "list"], [false, "form"]],
            domain: [
                ["type", "=", "opportunity"],
                ...spec.domain,
                [field, ">=", `${month.key}-01`],
                [field, "<", next],
            ],
            context: spec.activeTest === false ? { active_test: false } : {},
            target: "current",
        });
    }

    // Click an opportunity inside a month card -> open that record.
    openLead(lead) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: lead.name,
            res_model: "crm.lead",
            res_id: lead.id,
            views: [[false, "form"]],
            // Lost leads are archived; without this the form refuses to open.
            context: { active_test: false },
            target: "current",
        });
    }

    get kpis() {
        return this.state.data?.kpis || {};
    }
    get charts() {
        return this.state.data?.charts || {};
    }
    get boards() {
        return this.state.data?.boards || {};
    }
    get executives() {
        return this.state.data?.executives || [];
    }
}

registry.category("actions").add("ft_sales_dashboard", SalesDashboard);
