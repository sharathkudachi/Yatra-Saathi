"""Hard spend-cap enforcement and category (advisory-only) warnings (section 8).

`evaluate` is a pure computation (no audit write). `run_gate` is the pattern
every mutating call site uses: compute the check, and if it fails, write the
failing BUDGET_CHECK *and* ACTION_REFUSED together in their own transaction
(so the refusal survives even though nothing else is written), then raise.
If it passes, the BUDGET_CHECK success event is written as part of the
caller's own in-progress transaction, alongside the change it is gating.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.contracts.codes import RefusalError
from src.core import money
from src.core.clock import Clock
from src.db.repositories import sessions as sessions_repo
from src.db.repositories import trips as trips_repo
from src.db.unit_of_work import transaction
from src.services import audit_service, session_service

CHECKPOINTS = ("advisory", "cart_add", "lock", "final")


@dataclass(frozen=True)
class BudgetCheckResult:
    checkpoint: str
    subtotal_minor: int
    tax_minor: int
    total_minor: int
    committed_minor: int
    effective_cap_minor: int
    remaining_minor: int
    passed: bool
    category_warnings: list[dict]
    cap_source: str


def category_warnings(conn, session: sessions_repo.Session, category_minor: dict[str, int]) -> list[dict]:
    warnings: list[dict] = []
    if not session.trip_id:
        return warnings
    budget = trips_repo.get_budget_for_trip(conn, session.trip_id)
    if budget is None:
        return warnings
    caps = {"transport": budget.transport_cap, "accommodation": budget.accommodation_cap}
    for category, spent_minor in category_minor.items():
        cap_text = caps.get(category)
        if not cap_text:
            continue
        cap_minor = money.to_minor(cap_text)
        threshold_minor = (cap_minor * budget.alert_threshold_pct) // 100
        if spent_minor > cap_minor:
            warnings.append({"category": category, "level": "exceeded", "spent_minor": spent_minor,
                              "cap_minor": cap_minor})
        elif spent_minor >= threshold_minor:
            warnings.append({"category": category, "level": "warning", "spent_minor": spent_minor,
                              "cap_minor": cap_minor})
    return warnings


def evaluate(
    conn, session_id: str, *, checkpoint: str, subtotal_minor: int, tax_minor: int,
    total_minor: int, category_minor: Optional[dict[str, int]] = None,
) -> BudgetCheckResult:
    if checkpoint not in CHECKPOINTS:
        raise ValueError(f"unknown checkpoint: {checkpoint!r}")
    session = sessions_repo.get(conn, session_id)
    if session is None:
        raise ValueError(f"unknown session: {session_id}")

    cap = session_service.compute_cap_snapshot(conn, session_id)
    committed_minor = money.to_minor(sessions_repo.committed_total(conn, session_id))
    passed = (committed_minor + total_minor) <= cap.effective_cap_minor
    remaining_minor = cap.effective_cap_minor - committed_minor - total_minor
    warnings = category_warnings(conn, session, category_minor or {})

    return BudgetCheckResult(
        checkpoint=checkpoint, subtotal_minor=subtotal_minor, tax_minor=tax_minor,
        total_minor=total_minor, committed_minor=committed_minor,
        effective_cap_minor=cap.effective_cap_minor, remaining_minor=remaining_minor,
        passed=passed, category_warnings=warnings, cap_source=cap.cap_source,
    )


def record(
    conn, clock: Clock, session_id: str, result: BudgetCheckResult, *, actor: str = "agent",
    actor_user_id: Optional[str] = None, agent_run_id: Optional[str] = None,
    caused_by_event_id: Optional[str] = None, confirmation_id: Optional[str] = None,
    cart_id: Optional[str] = None,
) -> None:
    audit_service.append(
        conn, session_id=session_id, event_type="BUDGET_CHECK",
        actor=actor, actor_user_id=actor_user_id, agent_run_id=agent_run_id,
        occurred_at=clock.utc(), outcome="success" if result.passed else "refused",
        input_data={"checkpoint": result.checkpoint, "subtotal_minor": result.subtotal_minor,
                     "tax_minor": result.tax_minor, "total_minor": result.total_minor},
        result_data={"committed_minor": result.committed_minor,
                      "effective_cap_minor": result.effective_cap_minor,
                      "remaining_minor": result.remaining_minor, "passed": result.passed,
                      "category_warnings": result.category_warnings, "cap_source": result.cap_source},
        reason_code="SPEND_CAP_EXCEEDED" if not result.passed else None,
        reason=("committed + total exceeds the effective cap" if not result.passed else None),
        caused_by_event_id=caused_by_event_id, confirmation_id=confirmation_id, cart_id=cart_id,
    )


def run_gate(
    conn, clock: Clock, session_id: str, *, checkpoint: str, subtotal_minor: int, tax_minor: int,
    total_minor: int, category_minor: Optional[dict[str, int]] = None, actor: str = "agent",
    actor_user_id: Optional[str] = None, agent_run_id: Optional[str] = None,
    caused_by_event_id: Optional[str] = None,
) -> BudgetCheckResult:
    """Evaluate the cap; on failure, persist the refusal in its own transaction
    and raise. On success, the caller records the passing BUDGET_CHECK itself
    as part of the transaction it is about to commit (see `record`)."""
    result = evaluate(conn, session_id, checkpoint=checkpoint, subtotal_minor=subtotal_minor,
                       tax_minor=tax_minor, total_minor=total_minor, category_minor=category_minor)
    if not result.passed:
        with transaction(conn):
            record(conn, clock, session_id, result, actor=actor, actor_user_id=actor_user_id,
                   agent_run_id=agent_run_id, caused_by_event_id=caused_by_event_id)
            audit_service.append(
                conn, session_id=session_id, event_type="ACTION_REFUSED", actor=actor,
                actor_user_id=actor_user_id, agent_run_id=agent_run_id, occurred_at=clock.utc(),
                outcome="refused",
                input_data={"checkpoint": checkpoint, "total_minor": total_minor},
                result_data={"effective_cap_minor": result.effective_cap_minor,
                              "committed_minor": result.committed_minor},
                reason_code="SPEND_CAP_EXCEEDED",
                reason=(f"committed {result.committed_minor} + total {total_minor} exceeds "
                        f"effective cap {result.effective_cap_minor}"),
                caused_by_event_id=caused_by_event_id,
            )
        raise RefusalError(
            "SPEND_CAP_EXCEEDED",
            f"committed {result.committed_minor} + total {total_minor} exceeds effective cap "
            f"{result.effective_cap_minor}",
            committed_minor=result.committed_minor, total_minor=total_minor,
            effective_cap_minor=result.effective_cap_minor,
        )
    return result
