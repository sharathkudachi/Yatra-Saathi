# travel_agent/contracts.py
"""PROPOSED shared contracts — NOT FINAL until Developer 1 reviews them.

Kept inside travel_agent/ (not backend/contracts/) so nothing shared changes
before agreement. Fields marked "Requires Developer 1 confirmation" are
placeholders for identifiers/formats Developer 1 owns.
Money is Decimal and serialises to an exact string in JSON mode.
"""
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel

from travel_agent.state import AgentStatus, ErrorCode


class TripRequirements(BaseModel):
    origin_city_id: Optional[str] = None       # cities.city_id
    origin_name: Optional[str] = None
    destination_city_id: Optional[str] = None
    destination_name: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    travellers: Optional[int] = None
    budget_cap: Optional[Decimal] = None       # Requires Developer 1 confirmation: source of truth for the cap.
    currency: str = "INR"
    language: str = "en-IN"                    # BCP-47


class PlanStep(BaseModel):
    index: int
    key: str
    description: str
    status: Literal["pending", "in_progress", "done", "skipped", "failed"]


class AgentEvent(BaseModel):
    seq: int                                   # order within one run (agent-assigned)
    type: str
    step: str
    message: str
    timestamp: str                             # ISO-8601 with offset
    session_id: Optional[str] = None           # Requires Developer 1 confirmation.
    arguments: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None
    error_code: Optional[ErrorCode] = None
    # event_id: Requires Developer 1 confirmation (assigned by the audit store).


class CartLine(BaseModel):
    """Mirrors booking_items."""
    entity_type: Literal["flight_fare", "room_type", "poi"]
    entity_id: str
    inventory_id: Optional[str] = None
    title: str
    for_date: Optional[date] = None
    units: int
    unit_price: Decimal
    line_total: Decimal
    currency: str


class TravelCart(BaseModel):
    lines: List[CartLine]
    total: Decimal
    budget_cap: Decimal
    remaining: Decimal
    currency: str
    within_cap: bool
    # cart_id: Requires Developer 1 confirmation (does Developer 1 persist carts?).


class AgentResult(BaseModel):
    status: AgentStatus
    message: str
    language: str
    session_id: Optional[str] = None           # Requires Developer 1 confirmation.
    requirements: TripRequirements
    plan: List[PlanStep] = []
    plan_version: int = 0
    replan_count: int = 0
    cart: Optional[TravelCart] = None
    total_cost: Optional[Decimal] = None
    remaining_budget: Optional[Decimal] = None
    confirmation_required: bool = False
    clarification_required: bool = False
    clarification_question: Optional[str] = None
    missing_fields: List[str] = []
    error_code: Optional[ErrorCode] = None
    failure_reason: Optional[str] = None
    events: List[AgentEvent] = []
    engine: str = "langgraph"                  # "fallback" only when langgraph is not installed
    # Choosing between packages (live app): what to remember for the user's next message.
    packages: List[Dict[str, Any]] = []        # offered this turn (JSON-safe)
    chosen_package: Optional[Dict[str, Any]] = None
    preference: Optional[str] = None
    exclude_hotels: List[str] = []
    flight_time: Optional[str] = None
    tool_plan: Dict[str, Any] = {}             # tool calls the model requested (function calling)


def to_agent_result(state: Dict[str, Any], engine: str) -> AgentResult:
    requirements = TripRequirements(**{k: state.get(k) for k in TripRequirements.model_fields
                                       if state.get(k) is not None})
    status = state.get("status", "failed")
    return AgentResult(
        status=status,
        message=state.get("message", ""),
        language=state.get("language", "en-IN"),
        session_id=state.get("session_id"),
        requirements=requirements,
        plan=state.get("plan", []),
        plan_version=state.get("plan_version", 0),
        replan_count=state.get("replan_count", 0),
        cart=state.get("cart") if status == "awaiting_confirmation" else None,
        total_cost=state.get("total_cost"),
        remaining_budget=state.get("remaining_budget"),
        confirmation_required=status == "awaiting_confirmation",
        clarification_required=status == "awaiting_input",
        clarification_question=state.get("clarification_question") if status == "awaiting_input" else None,
        missing_fields=state.get("missing_fields", []),
        error_code=state.get("error_code") if status == "failed" else None,
        failure_reason=state.get("failure") if status == "failed" else None,
        events=state.get("events", []),
        engine=engine,
        packages=state.get("packages") or [],
        chosen_package=state.get("chosen_package"),
        preference=state.get("preference"),
        exclude_hotels=state.get("exclude_hotels") or [],
        flight_time=state.get("flight_time"),
        tool_plan=state.get("tool_plan") or {},
    )
