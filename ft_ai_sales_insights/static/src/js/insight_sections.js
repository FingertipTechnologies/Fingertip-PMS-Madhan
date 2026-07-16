/** @odoo-module **/

import { Component } from "@odoo/owl";

/**
 * A single KPI chip. props.kpi = { label, value, trend, status }.
 */
export class InsightKpi extends Component {
    static template = "ft_ai_sales_insights.InsightKpi";
    static props = { kpi: { type: Object } };

    get trendIcon() {
        return {
            up: "fa-arrow-up",
            down: "fa-arrow-down",
            flat: "fa-minus",
        }[this.props.kpi.trend] || "fa-minus";
    }
    get statusClass() {
        return `aisi_status--${this.props.kpi.status || "good"}`;
    }
}

/**
 * A tonal insight section. props.section = { title, icon, tone, body, items }.
 */
export class InsightSection extends Component {
    static template = "ft_ai_sales_insights.InsightSection";
    static props = { section: { type: Object } };

    get toneClass() {
        return `aisi_section--${this.props.section.tone || "info"}`;
    }
    get items() {
        return this.props.section.items || [];
    }
}
