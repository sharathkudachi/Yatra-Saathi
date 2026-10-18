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
from travel_agent.extraction import parse_goal
from travel_agent.llm import generate_json
from travel_agent.nodes.common import TOOL_ERRORS
from travel_agent.state import MAX_NIGHTS, MAX_TRAVELLERS
from travel_agent.tools.budget_tools import to_money
from travel_agent.tools.city_tools import resolve_city
from travel_agent.tools.db import query_db

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


def intake_node(state: Dict[str, Any]) -> Dict[str, Any]:
    log = EventLog(state)
    today = date.fromisoformat(state["today"])
    goal = state.get("goal", "")

    try:
        currencies = {r["iso4217"] for r in query_db("SELECT iso4217 FROM currencies")}
        parsed = parse_goal(goal, today, currencies)
    except TOOL_ERRORS as exc:
        log.add("AGENT_FAILED", "intake", "Could not read reference data.", reason=str(exc))
        return {"events": log.events, "failure": f"reference data unavailable: {exc}",
                "error_code": None, "current_step": "intake"}

    sources = {key: "text" for key in parsed}
    for key, value in _llm_fields(goal, today).items():
        if key not in parsed:
            parsed[key] = value
            sources[key] = "llm"

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
        issues.append(f"The start date {start} is in the past.")
        start = None
    if start and end and not (0 < (end - start).days <= MAX_NIGHTS):
        issues.append(f"The return date must be 1 to {MAX_NIGHTS} nights after the start date.")
        end = None

    # Cities resolve to real cities.city_id values or are rejected.
    origin = resolve_city(fields["origin_name"]) if fields["origin_name"] else None
    destination = resolve_city(fields["destination_name"]) if fields["destination_name"] else None
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
        budget_cap, currency = to_money(parsed["budget_amount"]), parsed["budget_currency"]
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
    return {**requirements, "nights": nights, "events": log.events, "missing_fields": missing,
            "input_issues": issues, "clarification_required": bool(missing),
            "current_step": "intake", "status": "planning"}


def route_after_intake(state: Dict[str, Any]) -> str:
    if state.get("failure"):
        return "fail"
    return "clarify" if state.get("missing_fields") else "planner"
