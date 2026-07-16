"""PromptBuilder — assembles the message list sent to the AI.

No prompt text is hardcoded here. The master prompt and the per-purpose prompt
are passed in (they come from editable DB records). This class only *composes*
them with the aggregated data payload and a strict response contract.
"""
from __future__ import annotations

import json

# The structured shape we ask the model to return. The OWL dashboard renders
# these keys; anything missing simply doesn't render. ``raw_text`` is a
# fallback the UI shows verbatim when JSON parsing fails.
RESPONSE_CONTRACT = """
Return a SINGLE valid JSON object (no markdown fences, no prose) with this shape:
{
  "executive_summary": "2-4 sentence markdown summary",
  "overall_score": 0-100 integer,
  "score_label": "short qualitative label, e.g. 'Healthy', 'At Risk'",
  "kpis": [{"label": "", "value": "", "trend": "up|down|flat", "status": "good|warning|bad"}],
  "sections": [{"title": "", "icon": "fa-... (FontAwesome)", "tone": "info|success|warning|danger", "body": "markdown", "items": ["bullet", ...]}],
  "top_opportunities": [{"name": "", "amount": "", "probability": "", "note": ""}],
  "at_risk_deals": [{"name": "", "amount": "", "reason": ""}],
  "salesperson_performance": [{"name": "", "highlight": "", "coaching": ""}],
  "recommended_actions": [{"priority": "high|medium|low", "action": ""}],
  "immediate_priorities": ["", ...],
  "forecast": {"amount": "", "confidence": "high|medium|low", "note": ""},
  "warnings": ["", ...]
}
Only include keys that are relevant to the requested purpose; omit the rest.
Base every statement on the supplied DATA. Never invent numbers.
"""


class PromptBuilder:
    def __init__(self, master_prompt: str, purpose_prompt: str, currency: str = ""):
        self.master_prompt = (master_prompt or "").strip()
        self.purpose_prompt = (purpose_prompt or "").strip()
        self.currency = currency

    def build(self, payload: dict, filters_label: str = "") -> list[dict]:
        """Return the OpenAI-style ``messages`` list."""
        system = "\n\n".join(
            part
            for part in (self.master_prompt, RESPONSE_CONTRACT.strip())
            if part
        )
        cur = f"\nAll monetary values are in {self.currency}." if self.currency else ""
        user = (
            f"{self.purpose_prompt}\n"
            f"{('Applied filters: ' + filters_label) if filters_label else ''}"
            f"{cur}\n\n"
            f"DATA (aggregated):\n```json\n"
            f"{json.dumps(payload, default=str, ensure_ascii=False, indent=2)}\n```"
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
