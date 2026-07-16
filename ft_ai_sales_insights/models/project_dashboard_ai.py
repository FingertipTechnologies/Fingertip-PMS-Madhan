"""AI Summary for the Project Dashboard — lives entirely in this module.

Extends ``ft.project.dashboard`` (from ft_project_dashboard) with the AI-summary
RPC used by the "AI Summary" button that this module injects into that
dashboard's UI. Keeping it here means all AI code stays inside
ft_ai_sales_insights; ft_project_dashboard carries no AI logic.

It:
* scopes work to a period (week/month presets);
* aggregates project-wise and resource-wise completed vs pending work and
  estimated/used hours from *timesheets* (account.analytic.line.date);
* aggregates accounts / opportunities / activities by *expected close date*
  (crm.lead.date_deadline);
* sends the compact summary to whichever provider ``ft.ai.insights.config``
  is set to (OpenAI, Ollama, …) and returns structured text.
"""
import json
import logging
import time
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.ft_ai_sales_insights.services.ai_service import AIService
from odoo.addons.ft_ai_sales_insights.services.providers.base import AIProviderError

_logger = logging.getLogger(__name__)

TOP_N = 15
DONE_STATE = "1_done"
CLOSED_TASK_STATES = ("1_done", "1_canceled")

AI_PERIODS = [
    ("this_week", "This Week"),
    ("last_week", "Last Week"),
    ("last_2_weeks", "Last 2 Weeks"),
    ("this_month", "This Month"),
    ("last_month", "Last Month"),
    ("last_2_months", "Last 2 Months"),
    ("last_3_months", "Last 3 Months"),
]

PROJECT_SYSTEM_PROMPT = """You are an experienced Delivery Director and PMO lead. \
You analyse project execution data (timesheets, tasks, estimates) and CRM \
account activity, and produce a concise, data-backed status summary for \
management.

Rules:
- Base every statement strictly on the supplied DATA. Never invent numbers or names.
- Be specific and quantify (hours, counts, % over/under estimate).
- Flag over-runs (used > estimated), stalled work, and pending backlogs.
- Keep it executive and actionable."""

RESPONSE_CONTRACT = """
Return a SINGLE valid JSON object (no markdown fences) with this shape:
{
  "headline": "2-3 sentence overall status",
  "sections": [
    {"title": "Project-wise Summary", "icon": "fa-folder-open", "tone": "info|success|warning|danger",
     "body": "markdown analysis", "items": ["short bullet per notable project", ...]},
    {"title": "Resource-wise Summary", "icon": "fa-users", "tone": "...",
     "body": "", "items": ["short bullet per notable resource", ...]},
    {"title": "Accounts, Opportunities & Activities", "icon": "fa-handshake-o", "tone": "...",
     "body": "", "items": ["", ...]}
  ],
  "recommended_actions": ["", ...],
  "warnings": ["", ...]
}
Only include sections supported by the DATA.
"""


class FtProjectDashboardAi(models.TransientModel):
    _inherit = "ft.project.dashboard"

    # ------------------------------------------------------------------
    # RPC entry points (called by the injected AI Summary panel)
    # ------------------------------------------------------------------
    @api.model
    def get_ai_period_options(self):
        cfg = self.env["ft.ai.insights.config"].sudo()._get_singleton()
        return {
            "periods": [{"key": k, "label": l} for k, l in AI_PERIODS],
            "configured": bool(cfg._resolve_api_key()) or cfg.provider == "ollama",
            "provider": cfg.provider,
            "model": cfg.model,
        }

    @api.model
    def get_ai_summary(self, period="this_month"):
        cfg = self.env["ft.ai.insights.config"].sudo()._get_singleton()
        if not (cfg._resolve_api_key() or cfg.provider == "ollama"):
            raise UserError(
                "No AI provider is configured. Set it under "
                "AI Insights > Configuration > Settings (or use Ollama, which "
                "needs no key)."
            )

        date_from, date_to = self._ai_date_range(period)
        payload = self._ai_collect(date_from, date_to)

        messages = [
            {"role": "system", "content": PROJECT_SYSTEM_PROMPT + "\n" + RESPONSE_CONTRACT},
            {
                "role": "user",
                "content": (
                    f"Period: {dict(AI_PERIODS).get(period, period)} "
                    f"({date_from} to {date_to}). "
                    f"All hours are timesheet hours; monetary values in "
                    f"{self.env.company.currency_id.name or ''}.\n\n"
                    f"DATA (aggregated):\n```json\n"
                    f"{json.dumps(payload, default=str, ensure_ascii=False, indent=2)}\n```"
                ),
            },
        ]

        service = AIService(
            cfg.provider,
            api_key=cfg._resolve_api_key(),
            base_url=cfg.api_base_url,
            model=cfg.model,
            timeout=cfg.request_timeout,
        )
        started = time.monotonic()
        log_vals = {
            "name": f"Project AI Summary — {dict(AI_PERIODS).get(period, period)}",
            "provider": cfg.provider,
            "model": cfg.model,
            "filters_json": json.dumps({"period": period, "from": str(date_from), "to": str(date_to)}),
            "payload_json": json.dumps(payload, default=str) if cfg.debug_mode else False,
        }
        try:
            result = service.generate(
                messages,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
                json_mode=True,
            )
        except AIProviderError as exc:
            self.env["ft.ai.insights.log"].sudo().create({
                **log_vals, "status": "error", "error_message": str(exc),
                "duration_ms": int((time.monotonic() - started) * 1000),
            })
            raise UserError(str(exc)) from exc

        duration_ms = int((time.monotonic() - started) * 1000)
        structured, raw_text = self._parse_json(result.text)
        log = self.env["ft.ai.insights.log"].sudo().create({
            **log_vals,
            "response": result.text,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "duration_ms": duration_ms,
            "status": "success",
        })
        return {
            "summary": structured,
            "raw_text": raw_text,
            "meta": {
                "log_id": log.id,
                "provider": cfg.provider,
                "model": result.model or cfg.model,
                "tokens": result.total_tokens,
                "duration_ms": duration_ms,
                "period": dict(AI_PERIODS).get(period, period),
                "date_range": {"from": str(date_from), "to": str(date_to)},
            },
            "data": payload if cfg.debug_mode else None,
        }

    # ------------------------------------------------------------------
    # Date range
    # ------------------------------------------------------------------
    @api.model
    def _ai_date_range(self, period):
        today = fields.Date.context_today(self)
        if period == "this_week":
            start = today - timedelta(days=today.weekday())
            return start, today
        if period == "last_week":
            start = today - timedelta(days=today.weekday() + 7)
            return start, start + timedelta(days=6)
        if period == "last_2_weeks":
            return today - timedelta(days=14), today
        if period == "this_month":
            return today.replace(day=1), today
        if period == "last_month":
            first_this = today.replace(day=1)
            last_prev = first_this - timedelta(days=1)
            return last_prev.replace(day=1), last_prev
        if period == "last_2_months":
            return (today - relativedelta(months=2)).replace(day=1), today
        if period == "last_3_months":
            return (today - relativedelta(months=3)).replace(day=1), today
        return today.replace(day=1), today

    # ------------------------------------------------------------------
    # Data collection (aggregated; runs as current user -> record rules)
    # ------------------------------------------------------------------
    def _ai_collect(self, date_from, date_to):
        return {
            "period": {"from": str(date_from), "to": str(date_to)},
            "projects": self._ai_projects(date_from, date_to),
            "resources": self._ai_resources(date_from, date_to),
            "accounts": self._ai_accounts(date_from, date_to),
        }

    def _ai_ts_domain(self, date_from, date_to, extra=None):
        return [
            ("project_id", "!=", False),
            ("date", ">=", date_from),
            ("date", "<=", date_to),
        ] + (extra or [])

    def _ai_projects(self, date_from, date_to):
        AAL = self.env["account.analytic.line"]
        Task = self.env["project.task"]
        used = {}
        for g in AAL.read_group(
            self._ai_ts_domain(date_from, date_to), ["unit_amount:sum"],
            ["project_id"], lazy=False, orderby="unit_amount desc", limit=TOP_N,
        ):
            if g.get("project_id"):
                used[g["project_id"][0]] = {
                    "project": g["project_id"][1],
                    "used_hours": round(g.get("unit_amount") or 0.0, 2),
                }
        if not used:
            return []
        proj_ids = list(used)
        for g in Task.read_group(
            [("project_id", "in", proj_ids)], ["estimated:sum"],
            ["project_id"], lazy=False,
        ):
            if g.get("project_id"):
                used[g["project_id"][0]]["estimated_hours"] = round(
                    g.get("estimated") or 0.0, 2
                )
        rows = []
        for pid in proj_ids:
            rec = used[pid]
            rec.setdefault("estimated_hours", 0.0)
            rec["completed_tasks"] = Task.search_count(
                [("project_id", "=", pid), ("state", "=", DONE_STATE)]
            )
            rec["pending_tasks"] = Task.search_count(
                [("project_id", "=", pid), ("state", "not in", CLOSED_TASK_STATES)]
            )
            rows.append(rec)
        return rows

    def _ai_resources(self, date_from, date_to):
        AAL = self.env["account.analytic.line"]
        Task = self.env["project.task"]
        Emp = self.env["hr.employee"]
        used = {}
        for g in AAL.read_group(
            self._ai_ts_domain(date_from, date_to, [("employee_id", "!=", False)]),
            ["unit_amount:sum"], ["employee_id"], lazy=False,
            orderby="unit_amount desc", limit=TOP_N,
        ):
            if g.get("employee_id"):
                used[g["employee_id"][0]] = {
                    "resource": g["employee_id"][1],
                    "used_hours": round(g.get("unit_amount") or 0.0, 2),
                }
        if not used:
            return []
        emps = Emp.browse(list(used))
        user_by_emp = {e.id: e.user_id.id for e in emps if e.user_id}
        rows = []
        for eid, rec in used.items():
            uid = user_by_emp.get(eid)
            if uid:
                rec["completed_tasks"] = Task.search_count(
                    [("user_ids", "in", [uid]), ("state", "=", DONE_STATE)]
                )
                rec["pending_tasks"] = Task.search_count(
                    [("user_ids", "in", [uid]), ("state", "not in", CLOSED_TASK_STATES)]
                )
            else:
                rec["completed_tasks"] = rec["pending_tasks"] = 0
            rows.append(rec)
        return rows

    def _ai_accounts(self, date_from, date_to):
        if "crm.lead" not in self.env:
            return {"available": False}
        Lead = self.env["crm.lead"]
        base = [
            ("type", "=", "opportunity"),
            ("date_deadline", ">=", date_from),
            ("date_deadline", "<=", date_to),
        ]
        by_stage = []
        total_count = total_value = 0
        for g in Lead.read_group(
            base, ["expected_revenue:sum"], ["stage_id"], lazy=False
        ):
            cnt = g["__count"]
            val = round(g.get("expected_revenue") or 0.0, 2)
            total_count += cnt
            total_value += val
            by_stage.append({
                "stage": g["stage_id"][1] if g.get("stage_id") else "Undefined",
                "count": cnt,
                "expected_revenue": val,
            })
        activities = 0
        try:
            lead_model = self.env["ir.model"]._get("crm.lead").id
            activities = self.env["mail.activity"].search_count([
                ("res_model_id", "=", lead_model),
                ("date_deadline", ">=", date_from),
                ("date_deadline", "<=", date_to),
            ])
        except Exception:  # pragma: no cover - defensive
            pass
        return {
            "available": True,
            "opportunities": total_count,
            "expected_revenue": round(total_value, 2),
            "by_stage": by_stage,
            "activities_due": activities,
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_json(text):
        if not text:
            return None, None
        try:
            return json.loads(text), None
        except (ValueError, TypeError):
            cleaned = text.strip()
            if "```" in cleaned:
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            s, e = cleaned.find("{"), cleaned.rfind("}")
            if s != -1 and e > s:
                try:
                    return json.loads(cleaned[s : e + 1]), None
                except (ValueError, TypeError):
                    pass
            return None, text
