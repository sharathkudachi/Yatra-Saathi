# travel_agent/nodes/flight_search.py
"""FLIGHT SEARCH: outbound and return legs, one visible tool call each."""
from datetime import date, timedelta
from typing import Any, Dict

from travel_agent.events import EventLog
from travel_agent.nodes.common import TOOL_ERRORS, failure_update, no_options_code
from travel_agent.state import set_step
from travel_agent.tool_planner import provenance
from travel_agent.tools.budget_tools import format_money
from travel_agent.tools.flight_tools import (flight_offer, nearby_flight_dates, search_flights,
                                             search_flights_via_backend, select_flight)


def _summary(fare: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("fare_id", "flight_number", "airline", "origin_iata", "destination_iata",
            "departs_at", "cabin_class", "fare_class", "unit_price", "currency")
    return {k: fare[k] for k in keys}


def _flight_suggestions(state, client, session_id, origin, destination, days, is_return) -> list:
    """For each suggested date: the cheapest bookable flight (airline, times, price per person),
    what it does to the stay, and the reply that re-plans with it."""
    out = []
    start, end = date.fromisoformat(state["start_date"]), date.fromisoformat(state["end_date"])
    cur = state["currency"]
    for day in days[:3]:
        try:
            if client is not None:
                found = search_flights_via_backend(client, session_id, origin, destination, day,
                                                   state["travellers"], cur, state.get("fx_rates"),
                                                   now=state.get("now"))
            else:
                found = search_flights(origin, destination, day, state["travellers"], cur, now=state.get("now"))
        except Exception:
            continue
        fare = select_flight(found["options"], 0)
        if fare is None:
            continue
        d = date.fromisoformat(day)
        if is_return:
            nights, reply, label = (d - start).days, f"return on {d.day} {d.strftime('%b %Y')}", f"Return {_pretty(day)}"
        else:
            nights = (end - start).days
            new_end = d + timedelta(days=nights)
            reply = f"leave on {d.day} {d.strftime('%b %Y')} and return on {new_end.day} {new_end.strftime('%b %Y')}"
            label = f"Leave {_pretty(day)}"
        stay = f"{nights}-night stay" + ("" if nights == (end - start).days else f" instead of {(end - start).days}")
        detail = (f"{fare['airline']} {fare['flight_number']} on {d.strftime('%a')} {_pretty(day)}, "
                  f"{str(fare['departs_at'])[11:16]} → {str(fare['arrives_at'])[11:16]}, "
                  f"{format_money(fare['unit_price'], cur)} per person ({stay})")
        out.append({"date": day, "label": label, "reply": reply, "detail": detail, "nights": nights,
                    "airline": str(fare["airline"]), "flight_number": str(fare["flight_number"]),
                    "departs_at": str(fare["departs_at"]), "arrives_at": str(fare["arrives_at"]),
                    "price_per_person": f"{fare['unit_price']:.2f}", "currency": cur})
    return out


def _pretty(day: str) -> str:
    d = date.fromisoformat(day)
    return f"{d.day} {d.strftime('%b %Y')}"


def flight_search_node(state: Dict[str, Any]) -> Dict[str, Any]:
    log = EventLog(state)
    plan = set_step(state["plan"], "flight_search", "in_progress")
    level = state.get("strategy_level", 0)
    client, session_id = state.get("backend_client"), state.get("session_id")
    legs = (
        ("outbound", state["origin_city_id"], state["destination_city_id"], state["start_date"]),
        ("return", state["destination_city_id"], state["origin_city_id"], state["end_date"]),
    )
    updates: Dict[str, Any] = {}
    for leg, origin, destination, travel_date in legs:
        args = {"leg": leg, "origin_city_id": origin, "destination_city_id": destination,
                "date": travel_date, "seats": state["travellers"], "currency": state["currency"],
                **provenance(state, f"search_flights:{leg}")}
        log.add("TOOL_CALL", "flight_search", f"Searching {leg} flights", arguments=args)
        try:
            if client is not None:
                tool_call_id = client.tool_call(session_id, "search_flights", args)
                search = search_flights_via_backend(client, session_id, origin, destination, travel_date,
                                                    state["travellers"], state["currency"], state.get("fx_rates"),
                                                    now=state.get("now"))
            else:
                tool_call_id = None
                search = search_flights(origin, destination, travel_date, state["travellers"],
                                        state["currency"], now=state.get("now"))
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
            is_return = leg == "return"
            try:
                if is_return:
                    first_valid_return = (date.fromisoformat(state["start_date"]) + timedelta(days=1)).isoformat()
                    others = nearby_flight_dates(
                        client, session_id, origin, destination, travel_date, state["today"],
                        state["travellers"], state["currency"], rates=state.get("fx_rates"),
                        not_before=travel_date)
                    if not others:
                        others = nearby_flight_dates(
                            client, session_id, origin, destination, travel_date, state["today"],
                            state["travellers"], state["currency"], rates=state.get("fx_rates"),
                            not_before=first_valid_return)
                else:
                    others = nearby_flight_dates(
                        client, session_id, origin, destination, travel_date, state["today"],
                        state["travellers"], state["currency"], rates=state.get("fx_rates"))
            except Exception:  # only a hint for the message; never turn it into a crash
                others = []
            # Say exactly which flight runs next (airline, times, price) and what it does to the
            # stay, and hand the frontend one-tap replies for each suggested date.
            suggestions = _flight_suggestions(state, client, session_id, origin, destination, others, is_return)
            if suggestions:
                first = suggestions[0]
                later = first["date"] > travel_date
                label = ("Next scheduled return flight" if later else "Nearest return flight after departure") if is_return \
                    else ("Next scheduled departure" if later else "Nearest earlier departure")
                reason += f" {label}: {first['detail']}."
                if len(suggestions) > 1:
                    reason += " Also available: " + "; ".join(s["detail"] for s in suggestions[1:]) + "."
                reason += " Tap a date or reply with one, and I'll re-plan."
            elif others:
                reason += f" Flights on this route run on {', '.join(_pretty(d) for d in others)}. Reply with a date to re-plan."
            else:
                reason += " There are no bookable flights on a valid date for this route; try another city."
            return {**failure_update(log, plan, "flight_search", reason, code), "date_suggestions": suggestions}

        if client is not None:
            # The backend re-validates and prices this fare authoritatively; only
            # its answer (not this node's own numbers) is ever trusted downstream.
            offer_result = client.submit_results(session_id, tool_call_id,
                                                 offers=[flight_offer(chosen, state["travellers"])])
            if not offer_result["accepted"]:
                reason = offer_result["rejected"][0]["message"] if offer_result["rejected"] else \
                    "the backend rejected this fare"
                return failure_update(log, plan, "flight_search", reason, "sold_out")
            chosen = {**chosen, "offer_ref": offer_result["accepted"][0]["offer_ref"]}

        updates[f"{leg}_options"] = search["options"]
        updates[f"selected_{leg}"] = chosen

    return {**updates, "events": log.events, "plan": set_step(plan, "flight_search", "done"),
            "current_step": "flight_search"}
