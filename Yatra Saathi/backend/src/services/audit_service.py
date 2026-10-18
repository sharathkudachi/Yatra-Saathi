"""Append-only, hash-chained audit trail (section 10). Written only here.

hash = SHA-256(prev_hash_text + canonical_json(all other columns)).
`prev_hash_text` is the empty string for the first event of a session (seq=1,
prev_hash is NULL in the DB). This exact scheme is also used by
`replay_service` to verify the chain, so keep the two in lock-step.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from src.core.enums import ACTORS, EVENT_TYPES, OUTCOMES
from src.core.hashing import canonical_json, sha256_hex
from src.core.ids import new_id
from src.db.repositories import audit as audit_repo

# Fixed field order for the hashed payload (order is irrelevant to the hash
# itself since canonical_json sorts keys, but keeping one order everywhere
# makes the code easy to audit).
HASHED_FIELDS = (
    "event_id", "session_id", "seq", "event_type", "occurred_at", "actor",
    "actor_user_id", "agent_run_id", "outcome", "reason_code", "reason",
    "input_json", "result_json", "request_id", "caused_by_event_id",
    "plan_version", "step_id", "cart_id", "cart_version", "confirmation_id",
    "booking_id",
)


def _hashable_payload(fields: dict) -> str:
    return canonical_json({k: fields[k] for k in HASHED_FIELDS})


def compute_hash(prev_hash: Optional[str], fields: dict) -> str:
    return sha256_hex((prev_hash or "") + _hashable_payload(fields))


def append(
    conn,
    *,
    session_id: str,
    event_type: str,
    actor: str,
    occurred_at: str,
    outcome: str,
    input_data: dict,
    result_data: dict,
    actor_user_id: Optional[str] = None,
    agent_run_id: Optional[str] = None,
    reason_code: Optional[str] = None,
    reason: Optional[str] = None,
    request_id: Optional[str] = None,
    caused_by_event_id: Optional[str] = None,
    plan_version: Optional[int] = None,
    step_id: Optional[str] = None,
    cart_id: Optional[str] = None,
    cart_version: Optional[int] = None,
    confirmation_id: Optional[str] = None,
    booking_id: Optional[str] = None,
) -> audit_repo.AuditEvent:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event type: {event_type!r}")
    if actor not in ACTORS:
        raise ValueError(f"unknown actor: {actor!r}")
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome: {outcome!r}")
    if (actor == "user") != (actor_user_id is not None):
        raise ValueError("actor_user_id must be set iff actor == 'user'")
    if (actor == "agent") != (agent_run_id is not None):
        raise ValueError("agent_run_id must be set iff actor == 'agent'")
    if (outcome in ("refused", "failed")) != (reason_code is not None):
        raise ValueError("reason_code must be set iff outcome is refused/failed")

    seq = audit_repo.next_seq(conn, session_id)
    prev = audit_repo.last_event(conn, session_id)
    prev_hash = prev.hash if prev else None

    fields = {
        "event_id": new_id("aud"),
        "session_id": session_id,
        "seq": seq,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "actor": actor,
        "actor_user_id": actor_user_id,
        "agent_run_id": agent_run_id,
        "outcome": outcome,
        "reason_code": reason_code,
        "reason": reason,
        "input_json": canonical_json(input_data),
        "result_json": canonical_json(result_data),
        "request_id": request_id,
        "caused_by_event_id": caused_by_event_id,
        "plan_version": plan_version,
        "step_id": step_id,
        "cart_id": cart_id,
        "cart_version": cart_version,
        "confirmation_id": confirmation_id,
        "booking_id": booking_id,
    }
    event_hash = compute_hash(prev_hash, fields)
    event = audit_repo.AuditEvent(prev_hash=prev_hash, hash=event_hash, **fields)
    audit_repo.insert(conn, event)
    return event


def write_fallback(fallback_path: str, event_fields: dict) -> None:
    """Local JSONL fallback used only when even the audit insert transaction fails.

    `/audit/verify` flags any session whose fallback file has entries not
    present in the database.
    """
    os.makedirs(os.path.dirname(fallback_path) or ".", exist_ok=True)
    with open(fallback_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event_fields, sort_keys=True) + "\n")
