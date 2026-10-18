# travel_agent/nodes/common.py
"""Small helpers shared by the search nodes."""
import sqlite3
from typing import Any, Dict

from travel_agent.state import set_step

# Errors a data tool may raise; nodes turn these into a structured failure instead of crashing.
TOOL_ERRORS = (sqlite3.Error, OSError, ValueError, KeyError, TypeError)


def no_options_code(search: Dict[str, Any]) -> str:
    """Map an empty search to an enums.json error_code."""
    if search["found"] == 0:
        return "constraint_infeasible"
    if search["excluded"].get("currency_mismatch", 0) == search["found"]:
        return "currency_mismatch"
    return "sold_out"


def failure_update(log, plan, step: str, reason: str, error_code: str | None) -> Dict[str, Any]:
    return {
        "events": log.events,
        "plan": set_step(plan, step, "failed"),
        "failure": reason,
        "error_code": error_code,
        "current_step": step,
    }
