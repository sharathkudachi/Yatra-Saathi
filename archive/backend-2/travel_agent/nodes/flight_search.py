# travel_agent/nodes/flight_search.py
"""FLIGHT SEARCH: outbound and return legs, one visible tool call each."""
from typing import Any, Dict

from travel_agent.events import EventLog
from travel_agent.nodes.common import TOOL_ERRORS, failure_update, no_options_code
from travel_agent.state import set_step
from travel_agent.tools.flight_tools import search_flights, select_flight


def _summary(fare: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("fare_id", "flight_number", "airline", "origin_iata", "destination_iata",
            "departs_at", "cabin_class", "fare_class", "unit_price", "currency")
    return {k: fare[k] for k in keys}


def flight_search_node(state: Dict[str, Any]) -> Dict[str, Any]:
    log = EventLog(state)
    plan = set_step(state["plan"], "flight_search", "in_progress")
    level = state.get("strategy_level", 0)
    legs = (
        ("outbound", state["origin_city_id"], state["destination_city_id"], state["start_date"]),
        ("return", state["destination_city_id"], state["origin_city_id"], state["end_date"]),
    )
    updates: Dict[str, Any] = {}
    for leg, origin, destination, travel_date in legs:
        args = {"leg": leg, "origin_city_id": origin, "destination_city_id": destination,
                "date": travel_date, "seats": state["travellers"], "currency": state["currency"]}
        log.add("TOOL_CALL", "flight_search", f"Searching {leg} flights", arguments=args)
        try:
            search = search_flights(origin, destination, travel_date, state["travellers"], state["currency"])
        except TOOL_ERRORS as exc:
            log.add("TOOL_RESULT", "flight_search", "Flight search failed.", reason=str(exc))
            return failure_update(log, plan, "flight_search", f"flight search failed: {exc}", None)

        chosen = select_flight(search["options"], level)
        log.add("TOOL_RESULT", "flight_search", f"{len(search['options'])} {leg} fare(s) available",
                result={"available": len(search["options"]), "excluded": search["excluded"],
                        "selected": _summary(chosen) if chosen else None})
        if chosen is None:
            code = no_options_code(search)
            reason = f"No bookable {leg} flight on {travel_date} for {state['travellers']} traveller(s)."
            return failure_update(log, plan, "flight_search", reason, code)
        updates[f"{leg}_options"] = search["options"]
        updates[f"selected_{leg}"] = chosen

    return {**updates, "events": log.events, "plan": set_step(plan, "flight_search", "done"),
            "current_step": "flight_search"}
