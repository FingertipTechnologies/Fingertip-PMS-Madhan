"""SalesDataCollector — turns filters into a compact, aggregated payload.

Design rules (see module docstring):
* Runs as the *current user* (``env``). All ``search``/``read_group`` calls
  therefore honour CRM/Sales record rules automatically — a user only ever
  analyses data they may see.
* Aggregates via ``read_group`` instead of shipping raw records, so the payload
  stays small regardless of database size.
* Every section is defensive: a failing section logs a warning and is skipped
  rather than breaking the whole analysis.
"""
from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)

# Cap list-style sections so payloads stay bounded on huge databases.
TOP_N = 10


class SalesDataCollector:
    def __init__(self, env, filters: dict, date_from=None, date_to=None):
        self.env = env
        self.filters = filters or {}
        self.date_from = date_from
        self.date_to = date_to

    # ------------------------------------------------------------------
    # Domain helpers
    # ------------------------------------------------------------------
    def _lead_domain(self, extra=None, date_field="create_date"):
        domain = [("type", "in", ("lead", "opportunity"))]
        if self.date_from:
            domain.append((date_field, ">=", f"{self.date_from} 00:00:00"))
        if self.date_to:
            domain.append((date_field, "<=", f"{self.date_to} 23:59:59"))
        f = self.filters
        if f.get("team_id") and f["team_id"] != "all":
            domain.append(("team_id", "=", int(f["team_id"])))
        if f.get("user_id") and f["user_id"] != "all":
            domain.append(("user_id", "=", int(f["user_id"])))
        if f.get("partner_id") and f["partner_id"] != "all":
            domain.append(("partner_id", "=", int(f["partner_id"])))
        if f.get("stage_id") and f["stage_id"] not in ("all", "lost"):
            domain.append(("stage_id", "=", int(f["stage_id"])))
        return domain + (extra or [])

    def _order_domain(self, extra=None):
        domain = []
        if self.date_from:
            domain.append(("date_order", ">=", f"{self.date_from} 00:00:00"))
        if self.date_to:
            domain.append(("date_order", "<=", f"{self.date_to} 23:59:59"))
        f = self.filters
        if f.get("team_id") and f["team_id"] != "all":
            domain.append(("team_id", "=", int(f["team_id"])))
        if f.get("user_id") and f["user_id"] != "all":
            domain.append(("user_id", "=", int(f["user_id"])))
        if f.get("partner_id") and f["partner_id"] != "all":
            domain.append(("partner_id", "=", int(f["partner_id"])))
        return domain + (extra or [])

    # ------------------------------------------------------------------
    # Drill-downs
    # ------------------------------------------------------------------
    def drilldowns(self) -> dict:
        """Clickable record lists behind the KPI tiles.

        Built from the same domain helpers that produce the numbers, so a tile
        and the list it opens can never disagree. Keys are offered to the model,
        which tags a KPI with one; unknown/absent keys simply aren't clickable.
        """
        dd = {
            "leads": {
                "res_model": "crm.lead",
                "name": "Leads",
                "domain": self._lead_domain([("type", "=", "lead")]),
            },
            "opportunities": {
                "res_model": "crm.lead",
                "name": "Opportunities",
                "domain": self._lead_domain([("type", "=", "opportunity")]),
            },
            "won_deals": {
                "res_model": "crm.lead",
                "name": "Won Deals",
                "domain": self._lead_domain([("stage_id.is_won", "=", True)]),
            },
            "open_pipeline": {
                "res_model": "crm.lead",
                "name": "Open Pipeline",
                "domain": self._lead_domain([("type", "=", "opportunity"),
                                             ("active", "=", True),
                                             ("stage_id.is_won", "=", False)]),
            },
            # Lost leads are archived, so the list must opt into inactive records
            # or it would open empty.
            "lost_deals": {
                "res_model": "crm.lead",
                "name": "Lost Deals",
                "domain": self._lead_domain([("active", "=", False),
                                             ("probability", "=", 0)]),
                "context": {"active_test": False},
            },
        }
        if "sale.order" in self.env:
            dd["quotations"] = {
                "res_model": "sale.order",
                "name": "Quotations",
                "domain": self._order_domain([("state", "in", ["draft", "sent"])]),
            }
            dd["sales_orders"] = {
                "res_model": "sale.order",
                "name": "Sales Orders",
                "domain": self._order_domain([("state", "in", ["sale", "done"])]),
            }
        return dd

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def collect(self) -> dict:
        payload = {
            "date_range": {"from": self.date_from, "to": self.date_to},
            "filters": self._filters_readable(),
        }
        for key, fn in (
            ("summary", self._summary),
            ("pipeline", self._pipeline),
            ("salespersons", self._salespersons),
            ("customers", self._customers),
            ("sales_orders", self._sales_orders),
            ("quotations", self._quotations),
            ("products", self._products),
            ("lost", self._lost),
            ("activities", self._activities),
            ("kpis", self._kpis),
        ):
            try:
                payload[key] = fn()
            except Exception as exc:  # pragma: no cover - defensive
                _logger.warning("AI insights: section '%s' failed: %s", key, exc)
                payload[key] = {"error": "unavailable"}
        return payload

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------
    def _filters_readable(self):
        f = self.filters
        return {
            "date_filter": f.get("date_filter"),
            "team": f.get("team_label", "All Teams"),
            "salesperson": f.get("user_label", "All Salespersons"),
            "customer": f.get("partner_label", "All Customers"),
            "stage": f.get("stage_label", "All Stages"),
            "purpose": f.get("purpose_label"),
        }

    def _summary(self):
        Lead = self.env["crm.lead"]
        leads = Lead.search_count(self._lead_domain([("type", "=", "lead")]))
        opps = Lead.search_count(self._lead_domain([("type", "=", "opportunity")]))
        won = Lead.search_count(
            self._lead_domain([("stage_id.is_won", "=", True)])
        )
        lost = Lead.search_count(
            self._lead_domain([("active", "=", False), ("probability", "=", 0)])
        )
        open_rev = self._sum(
            Lead.read_group(
                self._lead_domain(
                    [("active", "=", True), ("stage_id.is_won", "=", False)]
                ),
                ["expected_revenue:sum"],
                [],
            ),
            "expected_revenue",
        )
        return {
            "leads": leads,
            "opportunities": opps,
            "won": won,
            "lost": lost,
            "open_pipeline_value": round(open_rev, 2),
        }

    def _pipeline(self):
        Lead = self.env["crm.lead"]
        rows = Lead.read_group(
            self._lead_domain([("active", "=", True)]),
            ["expected_revenue:sum", "probability:avg"],
            ["stage_id"],
            lazy=False,
        )
        stages = []
        for g in rows:
            stage = g.get("stage_id")
            stages.append(
                {
                    "stage": stage[1] if stage else "Undefined",
                    "count": g["__count"],
                    "value": round(g.get("expected_revenue") or 0.0, 2),
                    "avg_probability": round(g.get("probability") or 0.0, 1),
                }
            )
        return {"by_stage": stages}

    def _salespersons(self):
        Lead = self.env["crm.lead"]
        rows = Lead.read_group(
            self._lead_domain([("active", "=", True)]),
            ["expected_revenue:sum"],
            ["user_id"],
            lazy=False,
            orderby="expected_revenue desc",
            limit=TOP_N,
        )
        out = []
        for g in rows:
            user = g.get("user_id")
            if not user:
                continue
            won = Lead.search_count(
                self._lead_domain(
                    [("user_id", "=", user[0]), ("stage_id.is_won", "=", True)]
                )
            )
            out.append(
                {
                    "salesperson": user[1],
                    "open_opportunities": g["__count"],
                    "open_value": round(g.get("expected_revenue") or 0.0, 2),
                    "won_deals": won,
                }
            )
        return out

    def _customers(self):
        Lead = self.env["crm.lead"]
        rows = Lead.read_group(
            self._lead_domain([("active", "=", True), ("partner_id", "!=", False)]),
            ["expected_revenue:sum"],
            ["partner_id"],
            lazy=False,
            orderby="expected_revenue desc",
            limit=TOP_N,
        )
        return [
            {
                "customer": g["partner_id"][1],
                "open_opportunities": g["__count"],
                "open_value": round(g.get("expected_revenue") or 0.0, 2),
            }
            for g in rows
            if g.get("partner_id")
        ]

    def _sales_orders(self):
        Order = self.env["sale.order"]
        confirmed = self._order_domain([("state", "in", ("sale", "done"))])
        rows = Order.read_group(confirmed, ["amount_total:sum"], [], lazy=False)
        total = self._sum(rows, "amount_total")
        count = rows[0]["__count"] if rows else 0
        return {
            "confirmed_orders": count,
            "confirmed_value": round(total, 2),
            "avg_order_value": round(total / count, 2) if count else 0.0,
        }

    def _quotations(self):
        Order = self.env["sale.order"]
        draft = self._order_domain([("state", "in", ("draft", "sent"))])
        rows = Order.read_group(draft, ["amount_total:sum"], [], lazy=False)
        q_count = rows[0]["__count"] if rows else 0
        q_value = self._sum(rows, "amount_total")
        confirmed = Order.search_count(
            self._order_domain([("state", "in", ("sale", "done"))])
        )
        total_q = q_count + confirmed
        acceptance = round(confirmed / total_q * 100, 1) if total_q else 0.0
        return {
            "open_quotations": q_count,
            "open_quotation_value": round(q_value, 2),
            "acceptance_rate_pct": acceptance,
        }

    def _products(self):
        Line = self.env["sale.order.line"]
        domain = [("order_id.state", "in", ("sale", "done"))]
        if self.date_from:
            domain.append(("order_id.date_order", ">=", f"{self.date_from} 00:00:00"))
        if self.date_to:
            domain.append(("order_id.date_order", "<=", f"{self.date_to} 23:59:59"))
        rows = Line.read_group(
            domain,
            ["price_subtotal:sum"],
            ["product_id"],
            lazy=False,
            orderby="price_subtotal desc",
            limit=TOP_N,
        )
        return [
            {
                "product": g["product_id"][1] if g.get("product_id") else "Undefined",
                "revenue": round(g.get("price_subtotal") or 0.0, 2),
            }
            for g in rows
        ]

    def _lost(self):
        Lead = self.env["crm.lead"]
        rows = Lead.read_group(
            self._lead_domain([("active", "=", False), ("probability", "=", 0)]),
            ["expected_revenue:sum"],
            ["lost_reason_id"],
            lazy=False,
            orderby="__count desc",
            limit=TOP_N,
        )
        return [
            {
                "reason": g["lost_reason_id"][1]
                if g.get("lost_reason_id")
                else "Unspecified",
                "count": g["__count"],
                "lost_value": round(g.get("expected_revenue") or 0.0, 2),
            }
            for g in rows
        ]

    def _activities(self):
        Act = self.env["mail.activity"]
        try:
            lead_model = self.env["ir.model"]._get("crm.lead").id
            total = Act.search_count([("res_model_id", "=", lead_model)])
            overdue = Act.search_count(
                [("res_model_id", "=", lead_model), ("date_deadline", "<", _today(self.env))]
            )
        except Exception:
            return {"open_activities": 0, "overdue_activities": 0}
        return {"open_activities": total, "overdue_activities": overdue}

    def _kpis(self):
        Lead = self.env["crm.lead"]
        won = Lead.search_count(self._lead_domain([("stage_id.is_won", "=", True)]))
        lost = Lead.search_count(
            self._lead_domain([("active", "=", False), ("probability", "=", 0)])
        )
        decided = won + lost
        win_rate = round(won / decided * 100, 1) if decided else 0.0
        # Average sales cycle from day_close (days between create and close).
        cycle_rows = Lead.read_group(
            self._lead_domain([("stage_id.is_won", "=", True), ("day_close", ">", 0)]),
            ["day_close:avg"],
            [],
        )
        avg_cycle = round(cycle_rows[0].get("day_close") or 0.0, 1) if cycle_rows else 0.0
        won_rows = Lead.read_group(
            self._lead_domain([("stage_id.is_won", "=", True)]),
            ["expected_revenue:sum"],
            [],
        )
        won_value = self._sum(won_rows, "expected_revenue")
        avg_deal = round(won_value / won, 2) if won else 0.0
        return {
            "win_rate_pct": win_rate,
            "avg_sales_cycle_days": avg_cycle,
            "avg_deal_size": avg_deal,
            "won_value": round(won_value, 2),
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _sum(groups, field):
        return sum(g.get(field) or 0.0 for g in groups)


def _today(env):
    from odoo import fields

    return fields.Date.context_today(env["mail.activity"])
