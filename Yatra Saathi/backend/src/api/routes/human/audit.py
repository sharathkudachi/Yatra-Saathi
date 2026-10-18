"""GET /api/v1/sessions/{sid}/audit and .../audit/verify (section 10)."""
from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends

from src.api.deps import CurrentUser, get_conn, get_current_user, require_session_owner
from src.contracts.envelope import ok
from src.db.repositories import audit as audit_repo
from src.services import replay_service

router = APIRouter()


def _event_view(event: audit_repo.AuditEvent) -> dict:
    return {
        "event_id": event.event_id, "seq": event.seq, "event_type": event.event_type,
        "occurred_at": event.occurred_at, "actor": event.actor, "actor_user_id": event.actor_user_id,
        "agent_run_id": event.agent_run_id, "outcome": event.outcome, "reason_code": event.reason_code,
        "reason": event.reason, "input": json.loads(event.input_json), "result": json.loads(event.result_json),
        "caused_by_event_id": event.caused_by_event_id, "cart_id": event.cart_id,
        "confirmation_id": event.confirmation_id, "booking_id": event.booking_id,
        "prev_hash": event.prev_hash, "hash": event.hash,
    }


@router.get("/sessions/{session_id}/audit")
def get_audit(session_id: str, user: CurrentUser = Depends(get_current_user),
              conn: sqlite3.Connection = Depends(get_conn)):
    require_session_owner(conn, session_id, user)
    events = audit_repo.list_for_session(conn, session_id)
    return ok({"events": [_event_view(e) for e in events]})


@router.get("/sessions/{session_id}/audit/verify")
def verify_audit(session_id: str, user: CurrentUser = Depends(get_current_user),
                  conn: sqlite3.Connection = Depends(get_conn)):
    require_session_owner(conn, session_id, user)
    result = replay_service.replay_and_verify(conn, session_id)
    return ok({"ok": result.ok, "chain_ok": result.chain_ok, "seq_gapless": result.seq_gapless,
               "replay_matches": result.replay_matches, "issues": result.issues})
