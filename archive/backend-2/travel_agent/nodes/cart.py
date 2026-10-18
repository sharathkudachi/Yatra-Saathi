# travel_agent/nodes/cart.py
"""CART: build the cart proposal and stop at CONFIRMATION_REQUIRED.

The agent never books or pays. The cart total is recomputed from its own lines
and re-checked against the cap as a final guard, independent of earlier nodes.
"""
from decimal import Decimal
from typing import Any, Dict, List

from travel_agent.events import EventLog
from travel_agent.messages import message
from travel_agent.state import set_step
from travel_agent.tools.budget_tools import HardCapViolation, assert_within_cap, format_money, line_total


def _line(entity_type, entity_id, inventory_id, title, for_date, units, unit_price, currency) -> Dict[str, Any]:
    """Shaped like booking_items so the booking service can map it 1:1."""
    return {"entity_type": entity_type, "entity_id": entity_id, "inventory_id": inventory_id,
            "title": title, "for_date": for_date, "units": units, "unit_price": unit_price,
            "line_total": line_total(unit_price, units), "currency": currency}


def build_cart_lines(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    travellers, cur = state["travellers"], state["currency"]
    lines = []
    for leg in ("outbound", "return"):
        fare = state[f"selected_{leg}"]
        lines.append(_line("flight_fare", fare["fare_id"], fare["inventory_id"],
                           f"{fare['flight_number']} {fare['origin_iata']}→{fare['destination_iata']} "
                           f"({fare['cabin_class']}, {fare['fare_class']})",
                           fare["for_date"], travellers, fare["unit_price"], cur))
    hotel = state["selected_hotel"]
    for night in hotel["nightly"]:
        lines.append(_line("room_type", hotel["room_type_id"], night["inventory_id"],
                           f"{hotel['room_name']} @ {hotel['hotel_name']}",
                           night["for_date"], hotel["rooms"], night["price"], cur))
    for activity in state.get("selected_activities", []):
        lines.append(_line("poi", activity["poi_id"], None, activity["title"], None,
                           travellers, activity["unit_price"], cur))
    return lines


def cart_node(state: Dict[str, Any]) -> Dict[str, Any]:
    log = EventLog(state)
    cur, cap = state["currency"], state["budget_cap"]
    lines = build_cart_lines(state)
    total = sum((line["line_total"] for line in lines), Decimal("0.00"))
    try:
        assert_within_cap(total, cap)
    except HardCapViolation as exc:
        log.add("ACTION_REFUSED", "cart", "Cart refused: total exceeds hard spend cap.",
                reason=str(exc), error_code="over_budget", result={"total_cost": total, "budget_cap": cap})
        return {"events": log.events, "failure": str(exc), "error_code": "over_budget",
                "within_budget": False, "cart": None, "current_step": "cart"}

    cart = {"lines": lines, "total": total, "budget_cap": cap, "remaining": cap - total,
            "currency": cur, "within_cap": True}
    log.add("CART_CREATED", "cart", f"Cart prepared with {len(lines)} line(s).",
            result={"total": total, "budget_cap": cap, "remaining": cap - total, "currency": cur,
                    "lines": [{k: line[k] for k in ("entity_type", "entity_id", "title", "units", "line_total")}
                              for line in lines]})
    log.add("CONFIRMATION_REQUIRED", "confirmation_gate",
            "User confirmation is required before booking/payment.",
            result={"total": total, "budget_cap": cap, "remaining": cap - total, "currency": cur})
    plan = set_step(set_step(state["plan"], "replan", "done" if state.get("replan_count") else "skipped"),
                    "cart", "done")
    plan = set_step(plan, "confirmation", "in_progress")
    text = message(state.get("language", "en-IN"), "cart_ready", total=format_money(total, cur),
                   cap=format_money(cap, cur), remaining=format_money(cap - total, cur))
    return {"events": log.events, "cart": cart, "plan": plan, "status": "awaiting_confirmation",
            "confirmation_required": True, "message": text, "current_step": "confirmation_gate"}


def route_after_cart(state: Dict[str, Any]) -> str:
    return "fail" if state.get("failure") else "end"
