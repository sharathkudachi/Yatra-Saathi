"""Repository for `agent_sessions` (existing table).

Reads are unrestricted. Writes are limited to: creating a new session (via the
human `POST /sessions` route), and the specific field updates the approved
flows allow (status, current_step, plan_steps_json, replan_count,
last_error_code, confirmed_at, spend_committed, updated_at).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Session:
    session_id: str
    user_id: str
    trip_id: Optional[str]
    goal_text: str
    goal_language: str
    constraints_json: str
    plan_steps_json: str
    current_step: int
    spend_cap: str
    spend_committed: str
    currency: str
    requires_confirmation: bool
    confirmed_at: Optional[str]
    replan_count: int
    last_error_code: Optional[str]
    status: str
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Session":
        return cls(
            session_id=row["session_id"], user_id=row["user_id"], trip_id=row["trip_id"],
            goal_text=row["goal_text"], goal_language=row["goal_language"],
            constraints_json=row["constraints_json"], plan_steps_json=row["plan_steps_json"],
            current_step=row["current_step"], spend_cap=row["spend_cap"],
            spend_committed=row["spend_committed"], currency=row["currency"],
            requires_confirmation=bool(row["requires_confirmation"]),
            confirmed_at=row["confirmed_at"], replan_count=row["replan_count"],
            last_error_code=row["last_error_code"], status=row["status"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )


def get(conn: sqlite3.Connection, session_id: str) -> Optional[Session]:
    row = conn.execute("SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)).fetchone()
    return Session.from_row(row) if row else None


def get_for_update(conn: sqlite3.Connection, session_id: str) -> Optional[Session]:
    """Same as get(); named separately to mark call sites that read-then-write inside a transaction."""
    return get(conn, session_id)


def insert(conn: sqlite3.Connection, *, session_id: str, user_id: str, trip_id: Optional[str],
           goal_text: str, goal_language: str, constraints_json: str, plan_steps_json: str,
           spend_cap: str, currency: str, requires_confirmation: bool, created_at: str) -> None:
    conn.execute(
        """INSERT INTO agent_sessions (
             session_id, user_id, trip_id, goal_text, goal_language, constraints_json,
             plan_steps_json, current_step, spend_cap, spend_committed, currency,
             requires_confirmation, confirmed_at, replan_count, last_error_code, status,
             created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, '0.00', ?, ?, NULL, 0, NULL, 'planning', ?, ?)""",
        (session_id, user_id, trip_id, goal_text, goal_language, constraints_json,
         plan_steps_json, spend_cap, currency, int(requires_confirmation), created_at, created_at),
    )


def update_status(conn: sqlite3.Connection, session_id: str, *, status: str, updated_at: str,
                   last_error_code: Optional[str] = None) -> None:
    conn.execute(
        "UPDATE agent_sessions SET status = ?, last_error_code = ?, updated_at = ? WHERE session_id = ?",
        (status, last_error_code, updated_at, session_id),
    )


def update_plan(conn: sqlite3.Connection, session_id: str, *, plan_steps_json: str,
                 current_step: int, updated_at: str) -> None:
    conn.execute(
        "UPDATE agent_sessions SET plan_steps_json = ?, current_step = ?, updated_at = ? WHERE session_id = ?",
        (plan_steps_json, current_step, updated_at, session_id),
    )


def increment_replan(conn: sqlite3.Connection, session_id: str, *, updated_at: str) -> int:
    conn.execute(
        "UPDATE agent_sessions SET replan_count = replan_count + 1, updated_at = ? WHERE session_id = ?",
        (updated_at, session_id),
    )
    row = conn.execute("SELECT replan_count FROM agent_sessions WHERE session_id = ?", (session_id,)).fetchone()
    return row["replan_count"]


def set_confirmed_at(conn: sqlite3.Connection, session_id: str, *, confirmed_at: str, updated_at: str) -> None:
    conn.execute(
        "UPDATE agent_sessions SET confirmed_at = ?, updated_at = ? WHERE session_id = ?",
        (confirmed_at, updated_at, session_id),
    )


def set_completed(conn: sqlite3.Connection, session_id: str, *, spend_committed: str, updated_at: str) -> None:
    conn.execute(
        "UPDATE agent_sessions SET status = 'completed', spend_committed = ?, updated_at = ? WHERE session_id = ?",
        (spend_committed, updated_at, session_id),
    )


def committed_total(conn: sqlite3.Connection, session_id: str) -> str:
    """The session's consumed booking total (2-decimal text), read from the DB (section 8.3).

    One booking per session (approved decision), reached through the
    confirmation that consumed it, so this can never double-count.
    """
    row = conn.execute(
        """SELECT b.total_amount AS total
           FROM agent_confirmations c
           JOIN bookings b ON b.booking_id = c.consumed_by_booking_id
           WHERE c.session_id = ? AND c.status = 'consumed'""",
        (session_id,),
    ).fetchone()
    return row["total"] if row else "0.00"
