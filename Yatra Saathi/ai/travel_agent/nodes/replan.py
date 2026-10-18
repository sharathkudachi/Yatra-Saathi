# travel_agent/nodes/replan.py
"""REPLAN: move to the next cheaper strategy and search again. The cap never changes."""
from typing import Any, Dict

from travel_agent.events import EventLog
from travel_agent.llm import generate_text
from travel_agent.state import MAX_REPLANS, REPLAN_STRATEGIES, set_step
from travel_agent.tools.budget_tools import format_money

_RESEARCH_STEPS = ("flight_search", "hotel_search", "activity_search", "budget_check")


def replan_node(state: Dict[str, Any]) -> Dict[str, Any]:
    log = EventLog(state)
    count = state.get("replan_count", 0) + 1
    if count > MAX_REPLANS:  # routing prevents this; kept as a second guard against loops
        return {"events": log.events, "failure": "maximum replans reached", "error_code": "over_budget"}

    level = min(state.get("strategy_level", 0) + 1, max(REPLAN_STRATEGIES))
    cur = state["currency"]
    client, session_id = state.get("backend_client"), state.get("session_id")
    if state.get("replan_reason"):
        # A non-budget failure (e.g. the chosen option sold out before booking): search again.
        reason, code = state["replan_reason"], state.get("replan_code") or "SOLD_OUT"
        strategy = "Search again for flights and rooms that are available now, and offer fresh options."
        explanation = f"{reason} {strategy}"
    else:
        strategy, code = REPLAN_STRATEGIES[level], "SPEND_CAP_EXCEEDED"
        over_by = state["total_cost"] - state["budget_cap"]
        reason = (f"Total {format_money(state['total_cost'], cur)} exceeds cap "
                  f"{format_money(state['budget_cap'], cur)} by {format_money(over_by, cur)}.")
        explanation = generate_text("replan", language=state.get("language", "en-IN"),
                                    total=format_money(state["total_cost"], cur),
                                    budget=format_money(state["budget_cap"], cur),
                                    over_by=format_money(over_by, cur), strategy=strategy) or f"{reason} {strategy}"
    if client is not None:
        client.replan(session_id, code, reason)

    plan = set_step(state["plan"], "replan", "in_progress")
    for step in _RESEARCH_STEPS:
        plan = set_step(plan, step, "pending")
    version = state.get("plan_version", 1) + 1
    log.add("REPLAN", "replan", "Searching for lower-cost alternatives.", reason=reason,
            arguments={"replan_count": count, "max_replans": MAX_REPLANS, "strategy_level": level},
            result={"strategy": strategy, "explanation": explanation})
    log.add("PLAN_UPDATED", "replan", f"Plan updated to version {version}.",
            result={"plan": plan, "plan_version": version})
    return {"events": log.events, "plan": plan, "plan_version": version, "replan_count": count,
            "strategy_level": level, "current_step": "replan",
            # a re-plan starts over from fresh searches: last turn's choice no longer applies
            "replan_reason": None, "chosen_package": None, "pending_packages": []}
