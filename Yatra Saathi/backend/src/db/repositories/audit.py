"""Repository for `agent_audit_events`. Insert-only; the DB enforces the chain."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    session_id: str
    seq: int
    event_type: str
    occurred_at: str
    actor: str
    actor_user_id: Optional[str]
    agent_run_id: Optional[str]
    outcome: str
    reason_code: Optional[str]
    reason: Optional[str]
    input_json: str
    result_json: str
    request_id: Optional[str]
    caused_by_event_id: Optional[str]
    plan_version: Optional[int]
    step_id: Optional[str]
    cart_id: Optional[str]
    cart_version: Optional[int]
    confirmation_id: Optional[str]
    booking_id: Optional[str]
    prev_hash: Optional[str]
    hash: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "AuditEvent":
        return cls(**{k: row[k] for k in row.keys() if k != "schema_version"})


def last_event(conn: sqlite3.Connection, session_id: str) -> Optional[AuditEvent]:
    row = conn.execute(
        "SELECT * FROM agent_audit_events WHERE session_id = ? ORDER BY seq DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    return AuditEvent.from_row(row) if row else None


def next_seq(conn: sqlite3.Connection, session_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM agent_audit_events WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return row["n"]


def insert(conn: sqlite3.Connection, event: AuditEvent) -> None:
    conn.execute(
        """INSERT INTO agent_audit_events (
             event_id, session_id, seq, event_type, occurred_at, actor, actor_user_id,
             agent_run_id, outcome, reason_code, reason, input_json, result_json,
             request_id, caused_by_event_id, plan_version, step_id, cart_id, cart_version,
             confirmation_id, booking_id, prev_hash, hash
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (event.event_id, event.session_id, event.seq, event.event_type, event.occurred_at,
         event.actor, event.actor_user_id, event.agent_run_id, event.outcome, event.reason_code,
         event.reason, event.input_json, event.result_json, event.request_id,
         event.caused_by_event_id, event.plan_version, event.step_id, event.cart_id,
         event.cart_version, event.confirmation_id, event.booking_id, event.prev_hash, event.hash),
    )


def list_for_session(conn: sqlite3.Connection, session_id: str) -> list[AuditEvent]:
    cur = conn.execute(
        "SELECT * FROM agent_audit_events WHERE session_id = ? ORDER BY seq ASC", (session_id,)
    )
    return [AuditEvent.from_row(r) for r in cur.fetchall()]


def get(conn: sqlite3.Connection, event_id: str) -> Optional[AuditEvent]:
    row = conn.execute("SELECT * FROM agent_audit_events WHERE event_id = ?", (event_id,)).fetchone()
    return AuditEvent.from_row(row) if row else None
