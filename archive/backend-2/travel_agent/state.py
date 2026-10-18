# travel_agent/state.py
"""LangGraph state for the travel agent, plus the agent's fixed policy constants.

Status and error-code values are taken verbatim from data/enums.json
(agent_status, error_code) so they map 1:1 onto agent_sessions columns.
"""
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional, TypedDict

MAX_REPLANS = 3
DEFAULT_CURRENCY = "INR"
DEFAULT_LANGUAGE = "en-IN"
MAX_NIGHTS = 30
MAX_TRAVELLERS = 9

AgentStatus = Literal["planning", "awaiting_input", "awaiting_confirmation",
                      "executing", "paused", "completed", "failed"]
ErrorCode = Literal["hold_expired", "sold_out", "over_budget", "invalid_id",
                    "currency_mismatch", "idempotency_conflict",
                    "constraint_infeasible", "low_confidence"]

# What each replan level changes (levels are cumulative).
REPLAN_STRATEGIES = {
    1: "Switch to the lowest-priced available room.",
    2: "Keep only free activities.",
    3: "Drop paid extras: cheapest fare in any cabin, no activities.",
}


class TravelAgentState(TypedDict, total=False):
    # Supplied by the caller (Developer 1). Opaque to the agent.
    session_id: Optional[str]
    goal: str
    language: str
    today: str                          # ISO date; injectable for tests

    # Requirements
    origin_city_id: Optional[str]
    origin_name: Optional[str]
    destination_city_id: Optional[str]
    destination_name: Optional[str]
    start_date: Optional[str]
    end_date: Optional[str]
    travellers: Optional[int]
    nights: Optional[int]               # stated trip length, used to derive end_date
    budget_cap: Optional[Decimal]
    caller_budget_cap: Optional[Decimal]  # cap from Developer 1 (e.g. agent_sessions.spend_cap); can only lower

    currency: str
    missing_fields: List[str]
    input_issues: List[str]

    # Clarification
    clarification_required: bool
    clarification_question: Optional[str]

    # Visible plan
    plan: List[Dict[str, Any]]
    plan_version: int
    current_step: str

    # Search results and selections
    outbound_options: List[Dict[str, Any]]
    return_options: List[Dict[str, Any]]
    hotel_options: List[Dict[str, Any]]
    activity_options: List[Dict[str, Any]]
    selected_outbound: Optional[Dict[str, Any]]
    selected_return: Optional[Dict[str, Any]]
    selected_hotel: Optional[Dict[str, Any]]
    selected_activities: List[Dict[str, Any]]

    # Budget
    cost_breakdown: Dict[str, Decimal]
    total_cost: Optional[Decimal]
    remaining_budget: Optional[Decimal]
    within_budget: bool

    # Replanning / failure
    strategy_level: int
    replan_count: int
    failure: Optional[str]
    error_code: Optional[str]

    # Output
    cart: Optional[Dict[str, Any]]
    confirmation_required: bool
    events: List[Dict[str, Any]]
    status: str
    message: str


PLAN_TEMPLATE = [
    ("understand", "Understand your travel requirements"),
    ("flight_search", "Search flights (outbound and return)"),
    ("hotel_search", "Search hotels for every night of the stay"),
    ("activity_search", "Search activities at the destination"),
    ("budget_check", "Check the total against your hard spend cap"),
    ("replan", f"If over budget, search cheaper alternatives (max {MAX_REPLANS} times)"),
    ("cart", "Prepare the cart"),
    ("confirmation", "Ask for your confirmation"),
    ("booking", "Book only after you confirm (handled by the booking service)"),
]


def new_plan() -> List[Dict[str, Any]]:
    return [{"index": i, "key": key, "description": text, "status": "pending"}
            for i, (key, text) in enumerate(PLAN_TEMPLATE, start=1)]


def set_step(plan: List[Dict[str, Any]], key: str, status: str) -> List[Dict[str, Any]]:
    """Return a copy of the plan with one step's status changed."""
    return [dict(step, status=status) if step["key"] == key else dict(step) for step in plan]
