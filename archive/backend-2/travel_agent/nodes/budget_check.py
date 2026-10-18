# travel_agent/nodes/budget_check.py
"""BUDGET CHECK: deterministic hard-cap enforcement. Emits ACTION_REFUSED when over."""
from decimal import Decimal
from typing import Any, Dict

from travel_agent.events import EventLog
from travel_agent.state import MAX_REPLANS, set_step
from travel_agent.tools.budget_tools import check_budget, format_money, line_total


def cost_breakdown(state: Dict[str, Any]) -> Dict[str, Decimal]:
    """Category totals computed from the same unit prices the cart will use."""
    travellers = state["travellers"]
    hotel = state["selected_hotel"]
    return {
        "flights": line_total(state["selected_outbound"]["unit_price"], travellers)
                   + line_total(state["selected_return"]["unit_price"], travellers),
        "hotel": sum((line_total(n["price"], hotel["rooms"]) for n in hotel["nightly"]), Decimal("0.00")),
        "activities": sum((line_total(a["unit_price"], travellers)
                           for a in state.get("selected_activities", [])), Decimal("0.00")),
    }


def budget_check_node(state: Dict[str, Any]) -> Dict[str, Any]:
    log = EventLog(state)
    result = check_budget(cost_breakdown(state), state["budget_cap"], state["currency"])
    log.add("BUDGET_CHECK", "budget_check", "Budget evaluation completed",
            result={"total_cost": result.total_cost, "budget_cap": result.budget_cap,
                    "remaining_budget": result.remaining_budget,
                    "within_budget": result.within_budget, "breakdown": result.breakdown,
                    "currency": result.currency, "strategy_level": state.get("strategy_level", 0)})
    updates = {"cost_breakdown": result.breakdown, "total_cost": result.total_cost,
               "remaining_budget": result.remaining_budget, "within_budget": result.within_budget,
               "current_step": "budget_check"}
    if result.within_budget:
        return {**updates, "events": log.events, "error_code": None,
                "plan": set_step(state["plan"], "budget_check", "done")}

    cur = result.currency
    reason = (f"Total cost {format_money(result.total_cost, cur)} exceeds budget cap "
              f"{format_money(result.budget_cap, cur)} by {format_money(result.over_by, cur)}.")
    log.add("ACTION_REFUSED", "budget_check", "Itinerary exceeds hard spend cap.", reason=reason,
            error_code="over_budget",
            result={"total_cost": result.total_cost, "budget_cap": result.budget_cap,
                    "over_by": result.over_by, "replans_left": MAX_REPLANS - state.get("replan_count", 0)})
    return {**updates, "events": log.events, "error_code": "over_budget",
            "plan": set_step(state["plan"], "budget_check", "failed")}


def route_after_budget(state: Dict[str, Any]) -> str:
    if state.get("within_budget"):
        return "cart"
    return "replan" if state.get("replan_count", 0) < MAX_REPLANS else "fail"
