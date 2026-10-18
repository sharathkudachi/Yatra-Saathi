# travel_agent/nodes/fail.py
"""FAIL: terminal user-facing failure (no availability, tool error, replans exhausted)."""
from typing import Any, Dict

from travel_agent.events import EventLog
from travel_agent.messages import message
from travel_agent.state import MAX_REPLANS
from travel_agent.tools.budget_tools import format_money


def fail_node(state: Dict[str, Any]) -> Dict[str, Any]:
    log = EventLog(state)
    reason = state.get("failure")
    error_code = state.get("error_code")
    if not reason and state.get("within_budget") is False:
        cur = state["currency"]
        reason = (f"Still over budget after {MAX_REPLANS} replans: lowest total found "
                  f"{format_money(state['total_cost'], cur)} vs cap {format_money(state['budget_cap'], cur)}.")
        error_code = "over_budget"
    reason = reason or "unknown error"
    log.add("AGENT_FAILED", state.get("current_step") or "agent", "No itinerary could be prepared.",
            reason=reason, error_code=error_code)
    plan = [dict(s, status="skipped") if s["status"] in ("pending", "in_progress") else s
            for s in state.get("plan", [])]
    return {"events": log.events, "plan": plan, "failure": reason, "error_code": error_code,
            "status": "failed", "cart": None, "confirmation_required": False,
            "message": message(state.get("language", "en-IN"), "failed", reason=reason)}
