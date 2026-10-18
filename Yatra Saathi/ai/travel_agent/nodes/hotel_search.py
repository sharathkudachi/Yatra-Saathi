# travel_agent/nodes/hotel_search.py
"""HOTEL SEARCH: room types bookable for every night of the stay."""
from typing import Any, Dict

from travel_agent.events import EventLog
from travel_agent.nodes.common import TOOL_ERRORS, failure_update, no_options_code
from travel_agent.state import set_step
from travel_agent.tool_planner import provenance
from travel_agent.tools.hotel_tools import hotel_offer, search_hotels, search_hotels_via_backend, select_hotel


def _summary(option: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("room_type_id", "hotel_name", "room_name", "star_rating", "guest_score",
            "rooms", "nights", "total_price", "currency")
    return {k: option[k] for k in keys}


def hotel_search_node(state: Dict[str, Any]) -> Dict[str, Any]:
    log = EventLog(state)
    plan = set_step(state["plan"], "hotel_search", "in_progress")
    client, session_id = state.get("backend_client"), state.get("session_id")
    args = {"city_id": state["destination_city_id"], "check_in": state["start_date"],
            "check_out": state["end_date"], "travellers": state["travellers"],
            "currency": state["currency"], **provenance(state, "search_hotels")}
    log.add("TOOL_CALL", "hotel_search", "Searching hotels", arguments=args)
    try:
        if client is not None:
            tool_call_id = client.tool_call(session_id, "search_hotels", args)
            search = search_hotels_via_backend(client, session_id, state["destination_city_id"],
                                               state["start_date"], state["end_date"],
                                               state["travellers"], state["currency"], state.get("fx_rates"))
        else:
            tool_call_id = None
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

    if client is not None:
        # The backend re-validates and prices this stay authoritatively; only its
        # answer (not this node's own numbers) is ever trusted downstream.
        offer_result = client.submit_results(session_id, tool_call_id, offers=[hotel_offer(chosen)])
        if not offer_result["accepted"]:
            reason = offer_result["rejected"][0]["message"] if offer_result["rejected"] else \
                "the backend rejected this room"
            return failure_update(log, plan, "hotel_search", reason, "sold_out")
        chosen = {**chosen, "offer_ref": offer_result["accepted"][0]["offer_ref"]}

    return {"events": log.events, "plan": set_step(plan, "hotel_search", "done"),
            "hotel_options": search["options"], "selected_hotel": chosen,
            "current_step": "hotel_search"}
