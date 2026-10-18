# travel_agent/nodes/planner.py
"""PLANNER: publish the visible plan before any tool is called."""
from typing import Any, Dict

from travel_agent.events import EventLog
from travel_agent.llm import generate_text
from travel_agent.messages import message
from travel_agent.state import MAX_REPLANS, new_plan, set_step
from travel_agent.tools.budget_tools import format_money
from travel_agent.tool_planner import plan_tool_calls, summary as tool_summary


def planner_node(state: Dict[str, Any]) -> Dict[str, Any]:
    log = EventLog(state)
    language = state.get("language", "en-IN")
    plan = set_step(new_plan(), "understand", "done")
    budget = format_money(state["budget_cap"], state["currency"])
    explanation = generate_text(
        "planner", language=language, origin=state["origin_name"],
        destination=state["destination_name"], start_date=state["start_date"],
        end_date=state["end_date"], travellers=state["travellers"], budget=budget,
        steps="\n".join(f"{s['index']}. {s['description']}" for s in plan),
    ) or message(language, "plan_created")
    client = state.get("backend_client")
    if client is not None:
        client.submit_plan(state["session_id"], plan)
    # The model chooses the tool calls (LLM function calling); arguments are validated
    # against the requirements before any tool runs (see tool_planner.py).
    tool_plan = plan_tool_calls(state)
    log.add("PLAN_CREATED", "planner", "Plan created and shown before execution.",
            result={"plan": plan, "plan_version": 1, "max_replans": MAX_REPLANS,
                    "explanation": explanation, "tool_calls": tool_summary(tool_plan)})
    return {"events": log.events, "plan": plan, "plan_version": 1, "strategy_level": 0, "tool_plan": tool_plan,
            "replan_count": 0, "current_step": "planner", "status": "planning",
            "message": explanation}
