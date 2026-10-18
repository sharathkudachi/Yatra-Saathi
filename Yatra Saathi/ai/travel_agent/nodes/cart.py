# travel_agent/nodes/cart.py
"""CART: build the cart proposal and stop at CONFIRMATION_REQUIRED.

The agent never books or pays. When running against the backend, the backend's
`POST /cart/items` + `POST /booking-requests` are the only things that actually
create a cart or a confirmation -- this node's own total/cap check is only a
local fallback for standalone/offline runs (see `budget_check.py`). Activity
(POI) lines are never sent to the backend: they are informational-only and the
backend's schema does not accept them as bookable (approved decision).
"""
from decimal import Decimal
from typing import Any, Dict, List

from backend_client import BackendRefusal
from travel_agent.events import EventLog
from travel_agent.messages import message
from travel_agent.nodes.options import chosen_summary
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
    client, session_id = state.get("backend_client"), state.get("session_id")
    cur, cap = state["currency"], state["budget_cap"]
    lines = build_cart_lines(state)

    if client is not None:
        offer_refs = [state["selected_outbound"]["offer_ref"], state["selected_return"]["offer_ref"],
                      state["selected_hotel"]["offer_ref"]]
        try:
            # A re-plan replaces the previous choice: clear what is already in the cart first.
            previous = (client.get_context(session_id).get("cart") or {}).get("item_group_ids") or []
            for group_id in previous:
                client.remove_cart_item_group(session_id, group_id)
            cart_result = client.add_cart_items(session_id, offer_refs)
            booking_request = client.request_booking(session_id)
        except BackendRefusal as exc:
            log.add("ACTION_REFUSED", "cart", "Cart refused by the backend.", reason=exc.message,
                    error_code="over_budget" if exc.code == "SPEND_CAP_EXCEEDED" else "constraint_infeasible",
                    result={"code": exc.code})
            return {"events": log.events, "failure": exc.message, "error_code": "over_budget",
                    "within_budget": exc.code != "SPEND_CAP_EXCEEDED", "cart": None, "current_step": "cart"}
        total = Decimal(cart_result["total_minor"]) / 100 if isinstance(cart_result.get("total_minor"), int) \
            else Decimal(str(cart_result.get("total", "0")))
        backend_lines = [l for l in lines if l["entity_type"] != "poi"]
        cart = {"lines": backend_lines, "total": total, "budget_cap": cap, "remaining": cap - total,
                "currency": cur, "within_cap": True, "confirmation_id": booking_request["confirmation_id"]}
        log.add("CART_CREATED", "cart", f"Cart prepared with {len(lines)} line(s).",
                result={"total": total, "budget_cap": cap, "remaining": cap - total, "currency": cur})
        log.add("CONFIRMATION_REQUIRED", "confirmation_gate",
                "User confirmation is required before booking/payment.",
                result={"total": total, "budget_cap": cap, "remaining": cap - total, "currency": cur,
                        "confirmation_id": booking_request["confirmation_id"],
                        "expires_at": booking_request["expires_at"]})
    else:
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
    recap = chosen_summary(state)
    if recap:
        text = (f"{text}\n\nYour choice:\n{recap}\n\nNot quite right? Say “cheaper”, “better hotel”, "
                f"“other hotels”, pick another option (1–3) or give new dates, and I'll re-plan.")
    return {"events": log.events, "cart": cart, "plan": plan, "status": "awaiting_confirmation",
            "confirmation_required": True, "message": text, "current_step": "confirmation_gate"}


def route_after_cart(state: Dict[str, Any]) -> str:
    return "fail" if state.get("failure") else "end"
