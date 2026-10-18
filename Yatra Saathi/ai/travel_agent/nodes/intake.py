# travel_agent/nodes/intake.py
"""INTAKE: extract and validate trip requirements.

Field priority: new text (rules, then LLM for gaps) > values carried over from a
previous clarification turn. The spend cap never comes from the LLM, and a cap
supplied by the caller can only lower the cap stated in text, never raise it.
"""
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List

from travel_agent.events import EventLog
from travel_agent.extraction import find_flight_time, find_preference, parse_goal, pick_option, wants_other_hotels
from travel_agent.llm import generate_json
from travel_agent.nodes.common import TOOL_ERRORS
from travel_agent.state import MAX_NIGHTS, MAX_TRAVELLERS
from travel_agent.tools.budget_tools import to_money
from travel_agent.tools.city_tools import load_cities_via_backend, resolve_city
from travel_agent.tools.db import query_db
from travel_agent.tools.fx_tools import can_convert, convert, load_rates_via_backend

_REQUIRED = ["origin", "destination", "start_date", "end_date", "travellers", "budget_cap"]


def _llm_fields(goal: str, today: date) -> Dict[str, Any]:
    data = generate_json("intake", goal=goal, today=today.isoformat()) or {}
    mapping = {"origin_city": "origin_name", "destination_city": "destination_name",
               "start_date": "start_date", "end_date": "end_date",
               "nights": "nights", "travellers": "travellers"}
    return {ours: data[theirs] for theirs, ours in mapping.items() if data.get(theirs) not in (None, "")}


def _as_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _day(d: date) -> str:
    return f"{d.day} {d.strftime('%b %Y')}"


def intake_node(state: Dict[str, Any]) -> Dict[str, Any]:
    log = EventLog(state)
    today = date.fromisoformat(state["today"])
    goal = state.get("goal", "")
    client = state.get("backend_client")

    try:
        if client is not None:
            # Through the backend's catalog -- no local database access. The
            # backend's catalog has no dedicated currencies route; INR covers
            # every approved demo scenario, so it's the supported set here.
            cities = load_cities_via_backend(client, state["session_id"])
            # The backend converts local prices at its demo rates, so any currency it has a
            # rate for is plannable; the same rates let this agent convert identically.
            rates = load_rates_via_backend(client, state["session_id"])
            currencies = set(rates)
        else:
            cities = None
            rates = None
            currencies = {r["iso4217"] for r in query_db("SELECT iso4217 FROM currencies")}
        parsed = parse_goal(goal, today, currencies, cities=cities)
    except TOOL_ERRORS as exc:
        log.add("AGENT_FAILED", "intake", "Could not read reference data.", reason=str(exc))
        return {"events": log.events, "failure": f"reference data unavailable: {exc}",
                "error_code": None, "current_step": "intake"}

    sources = {key: "text" for key in parsed}
    for key, value in _llm_fields(goal, today).items():
        if key not in parsed:
            parsed[key] = value
            sources[key] = "llm"
    # The LLM sometimes echoes the one city in the message into the other role too
    # ("my departure city is X" -> origin X *and* destination X). Trust the text.
    for key, other in (("origin_name", "destination_name"), ("destination_name", "origin_name")):
        if (sources.get(key) == "llm" and parsed.get(other)
                and str(parsed[key]).strip().lower() == str(parsed[other]).strip().lower()):
            del parsed[key]
            del sources[key]

    fields: Dict[str, Any] = {k: state.get(k) for k in
                              ("origin_name", "destination_name", "start_date", "end_date", "travellers")}
    fields.update({k: v for k, v in parsed.items() if k in fields})
    issues: List[str] = []

    # Dates: a stated length fills in the end date.
    start = _as_date(fields["start_date"]) if fields["start_date"] else None
    nights = parsed.get("nights") or state.get("nights")
    if start and not parsed.get("end_date") and nights:
        fields["end_date"] = (start + timedelta(days=int(nights))).isoformat()
    end = _as_date(fields["end_date"]) if fields["end_date"] else None
    if fields["start_date"] and start is None:
        issues.append(f"'{fields['start_date']}' is not a valid date.")
    if start and start < today:
        issues.append(f"The departure date {_day(start)} is in the past.")
        start = None
    if start and end and end <= start:
        issues.append(f"The return date {_day(end)} must be after the departure date {_day(start)}.")
        end = None
    elif start and end and (end - start).days > MAX_NIGHTS:
        issues.append(f"The return date {_day(end)} is more than {MAX_NIGHTS} nights after "
                      f"the departure date {_day(start)}.")
        end = None

    # Cities resolve to real cities.city_id values or are rejected.
    origin = resolve_city(fields["origin_name"], cities) if fields["origin_name"] else None
    destination = resolve_city(fields["destination_name"], cities) if fields["destination_name"] else None
    for label, name, city in (("departure", fields["origin_name"], origin),
                              ("destination", fields["destination_name"], destination)):
        if name and city is None:
            issues.append(f"I don't have {label} city '{name}' in my data.")
    if origin and destination and origin["city_id"] == destination["city_id"]:
        issues.append("The departure and destination cities are the same.")
        destination = None

    travellers = fields["travellers"]
    try:
        travellers = int(travellers) if travellers is not None else None
    except (TypeError, ValueError):
        travellers = None
    if travellers is not None and not 1 <= travellers <= MAX_TRAVELLERS:
        issues.append(f"I can plan for 1 to {MAX_TRAVELLERS} travellers.")
        travellers = None

    # Spend cap: deterministic only.
    budget_cap: Decimal | None = state.get("budget_cap")
    currency = state.get("currency") or "INR"
    if parsed.get("budget_amount"):
        stated, stated_currency = to_money(parsed["budget_amount"]), parsed["budget_currency"] or currency
        if rates and state.get("currency") and stated_currency != currency:
            # The session's currency is the trip currency (cart, cap and booking all use it);
            # a budget typed in another currency is converted into it, not swapped in.
            budget_cap = convert(stated, stated_currency, currency, rates) if can_convert(
                rates, stated_currency, currency) else None
            if budget_cap is None:
                issues.append(f"I can't convert {stated_currency} into {currency}.")
        else:
            budget_cap, currency = stated, stated_currency
    caller_cap = state.get("caller_budget_cap")
    if caller_cap is not None:
        budget_cap = min(budget_cap, caller_cap) if budget_cap is not None else caller_cap
    if budget_cap is not None and budget_cap <= 0:
        issues.append("The budget must be greater than zero.")
        budget_cap = None
    if currency not in currencies:
        issues.append(f"Unsupported currency {currency}.")
        budget_cap = None

    values = {"origin": origin, "destination": destination, "start_date": start,
              "end_date": end, "travellers": travellers, "budget_cap": budget_cap}
    missing = [name for name in _REQUIRED if values[name] is None]

    requirements = {
        "origin_city_id": origin["city_id"] if origin else None,
        "origin_name": origin["name"] if origin else fields["origin_name"],
        "destination_city_id": destination["city_id"] if destination else None,
        "destination_name": destination["name"] if destination else fields["destination_name"],
        "start_date": start.isoformat() if start else None,
        "end_date": end.isoformat() if end else None,
        "travellers": travellers,
        "budget_cap": budget_cap,
        "currency": currency,
    }
    log.add("REQUIREMENTS_EXTRACTED", "intake", "Extracted trip requirements from the request.",
            arguments={"goal": goal}, result={"requirements": requirements, "field_sources": sources,
                                              "missing_fields": missing, "issues": issues})
    # Live app: the user may be choosing one of last turn's packages, or asking for different ones.
    pending = state.get("pending_packages") or []
    chosen = pick_option(goal, pending) if state.get("offer_options") and not missing else None
    preference = find_preference(goal) or state.get("preference")
    exclude = list(state.get("exclude_hotels") or [])
    if wants_other_hotels(goal):
        exclude += [p["hotel"]["hotel_id"] for p in pending if p.get("hotel", {}).get("hotel_id")]
    return {**requirements, "nights": nights, "fx_rates": rates, "events": log.events, "missing_fields": missing,
            "chosen_package": chosen, "preference": preference, "exclude_hotels": exclude,
            "flight_time": find_flight_time(goal) or state.get("flight_time"),
            "input_issues": issues, "clarification_required": bool(missing),
            "current_step": "intake", "status": "planning"}


def route_after_intake(state: Dict[str, Any]) -> str:
    if state.get("failure"):
        return "fail"
    if state.get("missing_fields"):
        return "clarify"
    return "choose" if state.get("chosen_package") else "planner"
