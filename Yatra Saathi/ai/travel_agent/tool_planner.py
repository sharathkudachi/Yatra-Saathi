# travel_agent/tool_planner.py
"""The model decides which tools to call, via LLM function calling.

After the plan is published, the model is given the trip requirements and three tool
definitions (search_flights, search_hotels, check_budget) and returns function calls. Each
call's arguments are validated against the extracted requirements -- cities, dates and
travellers must match exactly -- and only then executed by the workflow nodes; a call the
model got wrong (or didn't make) is replaced by the workflow's own, and the audit trail says
which was which (`requested_by`). The spend cap itself is never delegated to the model: the
backend's budget check is what enforces it.

Without an LLM (tests, offline demo) the workflow issues the same calls itself.
"""
import json
import os
from typing import Any, Dict, List, Optional

from travel_agent.llm import DEFAULT_MODEL, _client, llm_enabled

TOOLS = [
    {"type": "function", "function": {
        "name": "search_flights",
        "description": "Search scheduled flights with bookable fares between two cities on one date.",
        "parameters": {"type": "object", "properties": {
            "leg": {"type": "string", "enum": ["outbound", "return"]},
            "origin_city": {"type": "string"}, "destination_city": {"type": "string"},
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "travellers": {"type": "integer", "minimum": 1}},
            "required": ["leg", "origin_city", "destination_city", "date", "travellers"]}}},
    {"type": "function", "function": {
        "name": "search_hotels",
        "description": "Search hotel rooms available for every night of a stay in one city.",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string"}, "check_in": {"type": "string", "description": "YYYY-MM-DD"},
            "check_out": {"type": "string", "description": "YYYY-MM-DD"}, "travellers": {"type": "integer", "minimum": 1}},
            "required": ["city", "check_in", "check_out", "travellers"]}}},
    {"type": "function", "function": {
        "name": "check_budget",
        "description": "Check candidate flight+hotel combinations (tax included) against the traveller's hard spend cap.",
        "parameters": {"type": "object", "properties": {
            "cap": {"type": "string", "description": "the hard spend cap, as a decimal string"},
            "currency": {"type": "string"}},
            "required": ["cap", "currency"]}}},
]

SYSTEM = ("You are the planning agent of a travel concierge. Call the tools needed to plan this trip: "
          "both flight legs, the hotel stay and the budget check. Use exactly the requirements given; "
          "do not invent values. Call every needed tool in this one reply.")


def expected_calls(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The calls the plan needs, keyed by slot, with the only acceptable arguments."""
    t = state["travellers"]
    return {
        "search_flights:outbound": {"leg": "outbound", "origin_city": state["origin_name"],
                                    "destination_city": state["destination_name"], "date": state["start_date"], "travellers": t},
        "search_flights:return": {"leg": "return", "origin_city": state["destination_name"],
                                  "destination_city": state["origin_name"], "date": state["end_date"], "travellers": t},
        "search_hotels": {"city": state["destination_name"], "check_in": state["start_date"],
                          "check_out": state["end_date"], "travellers": t},
        "check_budget": {"cap": f"{state['budget_cap']:.2f}", "currency": state["currency"]},
    }


def _norm(v: Any) -> str:
    return str(v).strip().lower()


MAX_ROUNDS = 5


def _args(call) -> Dict[str, Any]:
    try:
        value = json.loads(call.function.arguments or "{}")
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _slot(name: str, args: Dict[str, Any]) -> str:
    return f"search_flights:{args.get('leg', '')}" if name == "search_flights" else name


def plan_tool_calls(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """{slot: {"arguments": ..., "requested_by": "llm_function_call" | "workflow", ...}}."""
    expected = expected_calls(state)
    plan = {slot: {"arguments": args, "requested_by": "workflow"} for slot, args in expected.items()}
    if not llm_enabled():
        return plan
    model = os.environ.get("TRAVEL_AGENT_LLM_MODEL", DEFAULT_MODEL)
    requirements = {"origin_city": state["origin_name"], "destination_city": state["destination_name"],
                    "start_date": state["start_date"], "end_date": state["end_date"],
                    "travellers": state["travellers"], "spend_cap": f"{state['budget_cap']:.2f}",
                    "currency": state["currency"]}
    messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM},
                                      {"role": "user", "content": "Trip requirements: " + json.dumps(requirements)}]
    calls: list = []
    try:
        client = _client()
        # Function-calling loop: the model requests tools, gets each call acknowledged, and continues
        # until it has asked for everything it needs (or stops calling tools).
        for round_ in range(MAX_ROUNDS):
            response = client.chat.completions.create(
                model=model, temperature=0, tools=TOOLS, tool_choice="required" if round_ == 0 else "auto",
                messages=messages)
            message = response.choices[0].message
            batch = message.tool_calls or []
            if not batch:
                break
            calls += batch
            messages.append({"role": "assistant", "content": message.content or "", "tool_calls": [
                {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in batch]})
            for c in batch:
                messages.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(
                    {"status": "accepted", "note": "queued; results are returned to the planner"})})
            if {_slot(c.function.name, _args(c)) for c in calls} >= set(expected):
                break
    except Exception:  # network, quota, model errors: keep what the model managed; the workflow does the rest
        pass
    for call in calls:
        try:
            args = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            continue
        slot = _slot(call.function.name, args)
        if slot not in expected:
            continue
        # Accept the model's call only when its arguments match the requirements exactly.
        mismatched = [k for k, v in expected[slot].items() if _norm(args.get(k)) != _norm(v)]
        if mismatched:
            plan[slot].update({"requested_by": "workflow", "llm_arguments_rejected": {k: str(args.get(k)) for k in mismatched}})
        else:
            plan[slot] = {"arguments": expected[slot], "requested_by": "llm_function_call", "model": model,
                          "function_call_id": getattr(call, "id", None)}
    return plan


def provenance(state: Dict[str, Any], slot: str) -> Dict[str, Any]:
    """Audit fields for one tool call: who requested it (model or workflow)."""
    entry = (state.get("tool_plan") or {}).get(slot) or {"requested_by": "workflow"}
    return {k: v for k, v in entry.items() if k != "arguments"}


def summary(plan: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"slot": slot, **{k: v for k, v in entry.items() if k != "arguments"}} for slot, entry in plan.items()]
