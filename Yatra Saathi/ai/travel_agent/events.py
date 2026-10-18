# travel_agent/events.py
"""Structured, machine-readable audit events. The agent only produces them;
persisting them is Developer 1's audit layer."""
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

EVENT_TYPES = {
    "REQUIREMENTS_EXTRACTED", "CLARIFICATION_REQUIRED", "PLAN_CREATED", "PLAN_UPDATED",
    "TOOL_CALL", "TOOL_RESULT", "BUDGET_CHECK", "ACTION_REFUSED", "REPLAN",
    "CART_CREATED", "CONFIRMATION_REQUIRED", "AGENT_FAILED",
}


def jsonable(value: Any) -> Any:
    """Decimals become exact strings so money never turns into a float downstream."""
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


class EventLog:
    """Accumulates events for one node and returns the full, ordered list."""

    def __init__(self, state: Dict[str, Any]):
        self._events: List[Dict[str, Any]] = list(state.get("events", []))
        self._session_id = state.get("session_id")

    def add(self, type_: str, step: str, message: str, *, arguments: Optional[dict] = None,
            result: Optional[dict] = None, reason: Optional[str] = None,
            error_code: Optional[str] = None) -> None:
        if type_ not in EVENT_TYPES:
            raise ValueError(f"unknown event type {type_}")
        self._events.append({
            "seq": len(self._events) + 1,
            "type": type_,
            "step": step,
            "message": message,
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "session_id": self._session_id,
            "arguments": jsonable(arguments),
            "result": jsonable(result),
            "reason": reason,
            "error_code": error_code,
        })

    @property
    def events(self) -> List[Dict[str, Any]]:
        return self._events
