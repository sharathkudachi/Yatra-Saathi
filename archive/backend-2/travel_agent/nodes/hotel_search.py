# travel_agent/nodes/hotel_search.py
"""HOTEL SEARCH: room types bookable for every night of the stay."""
from typing import Any, Dict

from travel_agent.events import EventLog
from travel_agent.nodes.common import TOOL_ERRORS, failure_update, no_options_code
from travel_agent.state import set_step
from travel_agent.tools.hotel_tools import search_hotels, select_hotel


def _summary(option: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("room_type_id", "hotel_name", "room_name", "star_rating", "guest_score",
            "rooms", "nights", "total_price", "currency")
    return {k: option[k] for k in keys}


def hotel_search_node(state: Dict[str, Any]) -> Dict[str, Any]:
    log = EventLog(state)
    plan = set_step(state["plan"], "hotel_search", "in_progress")
    args = {"city_id": state["destination_city_id"], "check_in": state["start_date"],
            "check_out": state["end_date"], "travellers": state["travellers"],
            "currency": state["currency"]}
    log.add("TOOL_CALL", "hotel_search", "Searching hotels", arguments=args)
    try:
        search = search_hotels(state["destination_city_id"], state["start_date"], state["end_date"],
                               state["travellers"], state["currency"])
    except TOOL_ERRORS as exc:
        log.add("TOOL_RESULT", "hotel_search", "Hotel search failed.", reason=str(exc))
        return failure_update(log, plan, "hotel_search", f"hotel search failed: {exc}", None)

    chosen = select_hotel(search["options"], state.get("strategy_level", 0))
    log.add("TOOL_RESULT", "hotel_search", f"{len(search['options'])} room option(s) available",
            result={"available": len(search["options"]), "excluded": search["excluded"],
                    "selected": _summary(chosen) if chosen else None})
    if chosen is None:
        reason = (f"No room in {state['destination_name']} is available for every night "
                  f"{state['start_date']} to {state['end_date']}.")
        return failure_update(log, plan, "hotel_search", reason, no_options_code(search))

    return {"events": log.events, "plan": set_step(plan, "hotel_search", "done"),
            "hotel_options": search["options"], "selected_hotel": chosen,
            "current_step": "hotel_search"}
