# travel_agent/nodes/budget_check.py
"""BUDGET CHECK: deterministic hard-cap enforcement. Emits ACTION_REFUSED when over.

When running against the backend, the check that actually gates anything is the
backend's own (with real 12% tax and the real hard cap) via `POST /budget-checks`;
the local `check_budget` below is only ever a same-shape fallback for standalone/offline
runs and for `route_after_budget`'s decision when there is no backend to ask.
"""
from decimal import Decimal
from typing import Any, Dict

from travel_agent.events import EventLog
from travel_agent.state import MAX_REPLANS, set_step
from travel_agent.tool_planner import provenance
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


def _offer_refs(state: Dict[str, Any]) -> list:
    """Flight and hotel offer_refs only -- activities are informational-only
    and never part of what the backend prices or gates (approved decision)."""
    return [state["selected_outbound"]["offer_ref"], state["selected_return"]["offer_ref"],
            state["selected_hotel"]["offer_ref"]]


def budget_check_node(state: Dict[str, Any]) -> Dict[str, Any]:
    log = EventLog(state)
    client, session_id = state.get("backend_client"), state.get("session_id")

    if client is not None:
        # The check_budget tool call (requested by the model when it planned the tools), then the
        # authoritative check: the backend's own tax + hard cap, re-derived from live prices.
        tool_call_id = client.tool_call(session_id, "check_budget", {
            "cap": f"{state['budget_cap']:.2f}", "currency": state["currency"], **provenance(state, "check_budget")})
        advisory = client.budget_check(session_id, _offer_refs(state))
        client.submit_results(session_id, tool_call_id, offers=[])
        within_budget = advisory["passed"]
        total_cost, cap, remaining = (Decimal(advisory["total"]), Decimal(advisory["effective_cap"]),
                                      Decimal(advisory["remaining"]))
        breakdown = {"flights_and_hotel": Decimal(advisory["subtotal"]), "tax": Decimal(advisory["tax"])}
        currency = state["currency"]
    else:
        result = check_budget(cost_breakdown(state), state["budget_cap"], state["currency"])
        within_budget, total_cost, cap = result.within_budget, result.total_cost, result.budget_cap
        remaining, breakdown, currency = result.remaining_budget, result.breakdown, result.currency

    log.add("BUDGET_CHECK", "budget_check", "Budget evaluation completed",
            result={"total_cost": total_cost, "budget_cap": cap, "remaining_budget": remaining,
                    "within_budget": within_budget, "breakdown": breakdown, "currency": currency,
                    "strategy_level": state.get("strategy_level", 0)})
    updates = {"cost_breakdown": breakdown, "total_cost": total_cost, "remaining_budget": remaining,
               "within_budget": within_budget, "current_step": "budget_check"}
    if within_budget:
        return {**updates, "events": log.events, "error_code": None,
                "plan": set_step(state["plan"], "budget_check", "done")}

    over_by = max(total_cost - cap, Decimal("0.00"))
    reason = (f"Total cost {format_money(total_cost, currency)} exceeds budget cap "
              f"{format_money(cap, currency)} by {format_money(over_by, currency)}.")
    log.add("ACTION_REFUSED", "budget_check", "Itinerary exceeds hard spend cap.", reason=reason,
            error_code="over_budget",
            result={"total_cost": total_cost, "budget_cap": cap, "over_by": over_by,
                    "replans_left": MAX_REPLANS - state.get("replan_count", 0)})
    return {**updates, "events": log.events, "error_code": "over_budget",
            "plan": set_step(state["plan"], "budget_check", "failed")}


def route_after_budget(state: Dict[str, Any]) -> str:
    if state.get("within_budget"):
        return "cart"
    return "replan" if state.get("replan_count", 0) < MAX_REPLANS else "fail"
