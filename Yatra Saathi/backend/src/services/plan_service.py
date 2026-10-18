"""Plan submission, step lifecycle, and re-planning (sections 12, 13)."""
from __future__ import annotations

import json
from typing import Optional

from src.contracts.codes import RefusalError
from src.core.clock import Clock
from src.db.repositories import sessions as sessions_repo
from src.db.unit_of_work import transaction
from src.services import audit_service


def submit_plan(
    conn, clock: Clock, session_id: str, *, agent_run_id: str, steps: list[dict],
    reason_code: Optional[str] = None, caused_by_event_id: Optional[str] = None,
    reason: Optional[str] = None,
) -> int:
    session = sessions_repo.get(conn, session_id)
    if session is None:
        raise ValueError(f"unknown session: {session_id}")

    current = json.loads(session.plan_steps_json)
    new_version = (len(current) and _plan_version_of(current)) or 0
    new_version += 1

    plan_payload = {"version": new_version, "steps": steps}
    with transaction(conn):
        sessions_repo.update_plan(conn, session_id, plan_steps_json=json.dumps(plan_payload),
                                   current_step=0, updated_at=clock.existing())

        audit_service.append(
            conn, session_id=session_id, event_type="PLAN_CREATED", actor="agent",
            agent_run_id=agent_run_id, occurred_at=clock.utc(), outcome="success",
            input_data={"steps": steps}, result_data={"plan_version": new_version},
            plan_version=new_version, reason_code=reason_code, reason=reason,
            caused_by_event_id=caused_by_event_id,
        )
        if reason_code is not None:
            audit_service.append(
                conn, session_id=session_id, event_type="REPLAN", actor="agent",
                agent_run_id=agent_run_id, occurred_at=clock.utc(), outcome="info",
                input_data={"reason_code": reason_code, "reason": reason},
                result_data={"plan_version": new_version},
                plan_version=new_version, caused_by_event_id=caused_by_event_id,
            )
    return new_version


def _plan_version_of(plan_steps: object) -> int:
    if isinstance(plan_steps, dict):
        return int(plan_steps.get("version", 0))
    return 0


def record_step_event(
    conn, clock: Clock, session_id: str, step_id: str, *, agent_run_id: str,
    event: str, note: Optional[str] = None,
) -> None:
    if event not in ("started", "completed", "failed"):
        raise ValueError(f"unknown plan step event: {event!r}")
    event_type = {
        "started": "PLAN_STEP_STARTED",
        "completed": "PLAN_STEP_COMPLETED",
        "failed": "PLAN_STEP_COMPLETED",
    }[event]
    outcome = "failed" if event == "failed" else "success"
    audit_service.append(
        conn, session_id=session_id, event_type=event_type, actor="agent",
        agent_run_id=agent_run_id, occurred_at=clock.utc(), outcome=outcome,
        input_data={"step_id": step_id, "note": note},
        result_data={"event": event},
        step_id=step_id,
        reason_code="STEP_FAILED" if event == "failed" else None,
        reason=note if event == "failed" else None,
    )


def replan(
    conn, clock: Clock, session_id: str, *, agent_run_id: str, reason_code: str,
    reason: str, caused_by_event_id: Optional[str], replan_limit: int,
) -> int:
    session = sessions_repo.get(conn, session_id)
    if session is None:
        raise ValueError(f"unknown session: {session_id}")
    if session.replan_count >= replan_limit:
        with transaction(conn):
            audit_service.append(
                conn, session_id=session_id, event_type="ACTION_REFUSED", actor="agent",
                agent_run_id=agent_run_id, occurred_at=clock.utc(), outcome="refused",
                input_data={"reason_code": reason_code}, result_data={},
                reason_code="REPLAN_LIMIT_REACHED",
                reason=f"replan limit {replan_limit} reached",
                caused_by_event_id=caused_by_event_id,
            )
        raise RefusalError("REPLAN_LIMIT_REACHED", f"replan limit {replan_limit} reached")

    with transaction(conn):
        new_count = sessions_repo.increment_replan(conn, session_id, updated_at=clock.existing())
        audit_service.append(
            conn, session_id=session_id, event_type="REPLAN", actor="agent",
            agent_run_id=agent_run_id, occurred_at=clock.utc(), outcome="info",
            input_data={"reason_code": reason_code, "reason": reason},
            result_data={"replan_count": new_count}, caused_by_event_id=caused_by_event_id,
        )
    return new_count
