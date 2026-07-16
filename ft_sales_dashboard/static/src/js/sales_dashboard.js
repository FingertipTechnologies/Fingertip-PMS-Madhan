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
    static components = { KpiCard, ChartCard, FunnelChart };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.periods = PERIODS;

        // props.state covers the breadcrumb; sessionStorage covers browser Back
        // (which rebuilds the action fresh). Either way we land on the period
        // the user last chose rather than the default.
        const restored = this.props.state || readStoredFilter();
        this.state = useState({
            period: restored?.period || "month",
            dateFrom: restored?.dateFrom ?? null,
            dateTo: restored?.dateTo ?? null,
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
        };
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

    // Selected period, mirroring _date_domain on the server so a drill-down
    // opens exactly the records its KPI counted.
    _periodDomain() {
        const domain = [];
        if (this.state.dateFrom) {
            domain.push(["create_date", ">=", this.state.dateFrom + " 00:00:00"]);
        }
        if (this.state.dateTo) {
            domain.push(["create_date", "<=", this.state.dateTo + " 23:59:59"]);
        }
        return domain;
    }

    openOpportunities() {
        this._openLeads(
            [["type", "=", "opportunity"], ...this._periodDomain()],
            "Opportunities"
        );
    }
    openWon() {
        this._openLeads(
            [
                ["type", "=", "opportunity"],
                ["stage_id.is_won", "=", true],
                ...this._periodDomain(),
            ],
            "Won Opportunities"
        );
    }

    // Click a funnel stage -> open exactly the opportunities it counts:
    // that stage, opportunity type, active, within the selected period
    // (same filter as _chart_funnel on the server).
    openStage(stage) {
        const domain = [
            ["type", "=", "opportunity"],
            ["active", "=", true],
            ["stage_id", "=", stage.stageId || false],
            ...this._periodDomain(),
        ];
        this._openLeads(domain, stage.label || "Opportunities");
    }

    get kpis() {
        return this.state.data?.kpis || {};
    }
    get charts() {
        return this.state.data?.charts || {};
    }
}

registry.category("actions").add("ft_sales_dashboard", SalesDashboard);
