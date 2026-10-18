# travel_agent/nodes/fail.py
"""FAIL: terminal user-facing failure (no availability, tool error, replans exhausted)."""
from typing import Any, Dict

from backend_client import BackendRefusal
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
        if state.get("backend_client") is not None:
            # The cap is the trip brief's budget; a budget typed in chat can only lower it.
            reason += " To allow more, raise the budget in your trip brief and send your request again."
    reason = reason or "unknown error"
    log.add("AGENT_FAILED", state.get("current_step") or "agent", "No itinerary could be prepared.",
            reason=reason, error_code=error_code)
    user_message = message(state.get("language", "en-IN"), "failed", reason=reason)
    client, session_id = state.get("backend_client"), state.get("session_id")
    if client is not None:
        client.run_outcome(session_id, "failed", reason)
        # run-outcome is informational and the backend does not allow executing -> failed,
        # so on its own it leaves the session stuck in 'executing'. Surfacing the failure as
        # a clarification moves it to awaiting_input: the user sees why and can try again.
        try:
            client.clarification(session_id, user_message, suggestions=state.get("date_suggestions") or None)
        except BackendRefusal:
            pass  # session already left 'executing' (e.g. declined confirmation); nothing to unstick
    plan = [dict(s, status="skipped") if s["status"] in ("pending", "in_progress") else s
            for s in state.get("plan", [])]
    return {"events": log.events, "plan": plan, "failure": reason, "error_code": error_code,
            "status": "failed", "cart": None, "confirmation_required": False,
            "message": user_message}
