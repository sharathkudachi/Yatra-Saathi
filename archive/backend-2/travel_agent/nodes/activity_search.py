# travel_agent/nodes/activity_search.py
"""ACTIVITY SEARCH: optional. No activities (or a tool error) is a warning, not a failure."""
from datetime import date
from typing import Any, Dict

from travel_agent.events import EventLog
from travel_agent.nodes.common import TOOL_ERRORS
from travel_agent.state import set_step
from travel_agent.tools.activity_tools import search_activities, select_activities

MAX_ACTIVITIES = 3


def activity_search_node(state: Dict[str, Any]) -> Dict[str, Any]:
    log = EventLog(state)
    plan = set_step(state["plan"], "activity_search", "in_progress")
    args = {"city_id": state["destination_city_id"], "currency": state["currency"]}
    log.add("TOOL_CALL", "activity_search", "Searching activities", arguments=args)
    try:
        search = search_activities(state["destination_city_id"], state["currency"])
    except TOOL_ERRORS as exc:
        log.add("TOOL_RESULT", "activity_search", "Activity search failed; continuing without activities.",
                reason=str(exc))
        return {"events": log.events, "plan": set_step(plan, "activity_search", "skipped"),
                "activity_options": [], "selected_activities": [], "current_step": "activity_search"}

    nights = (date.fromisoformat(state["end_date"]) - date.fromisoformat(state["start_date"])).days
    chosen = select_activities(search["options"], state.get("strategy_level", 0),
                               min(MAX_ACTIVITIES, max(nights, 1)))
    log.add("TOOL_RESULT", "activity_search", f"{len(search['options'])} activit(ies) found",
            result={"available": len(search["options"]), "excluded": search["excluded"],
                    "selected": [{"poi_id": a["poi_id"], "title": a["title"],
                                  "unit_price": a["unit_price"]} for a in chosen]})
    return {"events": log.events, "plan": set_step(plan, "activity_search", "done"),
            "activity_options": search["options"], "selected_activities": chosen,
            "current_step": "activity_search"}
