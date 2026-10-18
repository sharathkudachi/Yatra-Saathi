"""Session lifecycle (section 11) and cap-snapshot creation (section 6/10)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from src.contracts.codes import RefusalError
from src.core import fx, money
from src.core.clock import Clock
from src.core.ids import new_id
from src.db.repositories import audit as audit_repo
from src.db.repositories import sessions as sessions_repo
from src.db.repositories import trips as trips_repo
from src.db.unit_of_work import transaction
from src.services import audit_service

# Table from section 11. Keys are the "from" status; values are allowed "to" statuses.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "planning": {"executing"},
    "executing": {"awaiting_input", "awaiting_confirmation", "paused"},
    "awaiting_input": {"executing", "paused"},
    "awaiting_confirmation": {"awaiting_input", "executing", "completed", "failed", "paused"},
    "paused": {"planning", "executing", "awaiting_input", "awaiting_confirmation"},
    "completed": set(),
    "failed": set(),
}


@dataclass(frozen=True)
class CapSnapshot:
    spend_cap_minor: int
    budget_total_minor: Optional[int]
    effective_cap_minor: int
    cap_source: str  # "budget" | "session_cap_only"


def compute_cap_snapshot(conn, session_id: str) -> CapSnapshot:
    """Effective cap = MIN(session-created spend_cap, live spend_cap, live budget total),
    per the approved cap-immutability rule (section 6)."""
    session = sessions_repo.get(conn, session_id)
    if session is None:
        raise ValueError(f"unknown session: {session_id}")
    created_cap_minor = _created_cap_minor(conn, session_id)
    live_cap_minor = money.to_minor(session.spend_cap)
    budget_minor = None
    if session.trip_id:
        trip = trips_repo.get_trip(conn, session.trip_id)
        if trip:
            budget = trips_repo.get_budget_for_trip(conn, trip.trip_id)
            if budget:
                budget_minor = money.to_minor(budget.total_amount)
    candidates = [c for c in (created_cap_minor, live_cap_minor, budget_minor) if c is not None]
    effective = min(candidates)
    source = "budget" if (budget_minor is not None and effective == budget_minor) else "session_cap_only"
    return CapSnapshot(spend_cap_minor=live_cap_minor, budget_total_minor=budget_minor,
                        effective_cap_minor=effective, cap_source=source)


def _created_cap_minor(conn, session_id: str) -> Optional[int]:
    events = audit_repo.list_for_session(conn, session_id)
    for ev in events:
        if ev.event_type == "SESSION_CREATED":
            result = json.loads(ev.result_json)
            return result.get("effective_cap_minor")
    return None


def create_session(
    conn,
    clock: Clock,
    *,
    user_id: str,
    trip_id: Optional[str],
    goal_text: str,
    goal_language: str,
    constraints: dict,
    spend_cap: str,
    currency: str,
    tax_rate_bp: int,
    replan_limit: int,
    requires_confirmation: bool = True,
) -> sessions_repo.Session:
    if conn.execute("SELECT 1 FROM currencies WHERE iso4217 = ?", (currency,)).fetchone() is None:
        raise RefusalError("MALFORMED_ITEM", f"unknown currency: {currency}")
    if not fx.supported(currency):
        raise RefusalError("MALFORMED_ITEM", f"no exchange rate for currency: {currency}")
    budget_minor = None
    category_caps_available = False
    if trip_id:
        trip = trips_repo.get_trip(conn, trip_id)
        if trip is None:
            raise RefusalError("MALFORMED_ITEM", f"unknown trip: {trip_id}")
        budget = trips_repo.get_budget_for_trip(conn, trip_id)
        if budget:
            if budget.currency != currency:
                raise RefusalError("CURRENCY_MISMATCH",
                                    "session currency does not match the trip's budget currency")
            budget_minor = money.to_minor(budget.total_amount)
            category_caps_available = bool(budget.accommodation_cap)

    spend_cap_minor = money.to_minor(spend_cap)
    effective_cap_minor = min(c for c in (spend_cap_minor, budget_minor) if c is not None)
    cap_source = "budget" if (budget_minor is not None and effective_cap_minor == budget_minor) else "session_cap_only"

    session_id = new_id("agt")
    with transaction(conn):
        now = clock.existing()
        sessions_repo.insert(
            conn, session_id=session_id, user_id=user_id, trip_id=trip_id, goal_text=goal_text,
            goal_language=goal_language, constraints_json=json.dumps(constraints), plan_steps_json="[]",
            spend_cap=spend_cap, currency=currency, requires_confirmation=requires_confirmation,
            created_at=now,
        )
        audit_service.append(
            conn, session_id=session_id, event_type="SESSION_CREATED", actor="system",
            occurred_at=clock.utc(), outcome="success",
            input_data={"user_id": user_id, "trip_id": trip_id, "goal_text": goal_text},
            result_data={
                "spend_cap": spend_cap, "spend_cap_minor": spend_cap_minor,
                "budget_total_minor": budget_minor, "effective_cap_minor": effective_cap_minor,
                "cap_source": cap_source, "currency": currency, "tax_rate_bp": tax_rate_bp,
                "replan_limit": replan_limit, "category_caps_available": category_caps_available,
            },
        )
    return sessions_repo.get(conn, session_id)


def assert_transition_allowed(from_status: str, to_status: str) -> None:
    if to_status not in ALLOWED_TRANSITIONS.get(from_status, set()):
        raise RefusalError("INVALID_STATE",
                            f"cannot transition session from {from_status!r} to {to_status!r}")


def transition(conn, clock: Clock, session_id: str, to_status: str, *,
               last_error_code: Optional[str] = None) -> sessions_repo.Session:
    session = sessions_repo.get(conn, session_id)
    if session is None:
        raise ValueError(f"unknown session: {session_id}")
    assert_transition_allowed(session.status, to_status)
    sessions_repo.update_status(conn, session_id, status=to_status, updated_at=clock.existing(),
                                 last_error_code=last_error_code)
    return sessions_repo.get(conn, session_id)
