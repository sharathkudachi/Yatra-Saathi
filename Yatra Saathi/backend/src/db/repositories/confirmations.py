"""Repository for `agent_confirmations`."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Confirmation:
    confirmation_id: str
    session_id: str
    cart_id: str
    cart_version: int
    snapshot_hash: str
    snapshot_json: str
    currency: str
    subtotal_minor: int
    tax_minor: int
    total_minor: int
    effective_cap_minor: int
    status: str
    requested_at: str
    expires_at: str
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    closed_reason: Optional[str]
    consumed_at: Optional[str]
    consumed_by_booking_id: Optional[str]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Confirmation":
        return cls(**{k: row[k] for k in row.keys()})


def get(conn: sqlite3.Connection, confirmation_id: str) -> Optional[Confirmation]:
    row = conn.execute(
        "SELECT * FROM agent_confirmations WHERE confirmation_id = ?", (confirmation_id,)
    ).fetchone()
    return Confirmation.from_row(row) if row else None


def get_current(conn: sqlite3.Connection, session_id: str) -> Optional[Confirmation]:
    row = conn.execute(
        "SELECT * FROM agent_confirmations WHERE session_id = ? AND status = 'pending'",
        (session_id,),
    ).fetchone()
    return Confirmation.from_row(row) if row else None


def insert(conn: sqlite3.Connection, *, confirmation_id: str, session_id: str, cart_id: str,
           cart_version: int, snapshot_hash: str, snapshot_json: str, currency: str,
           subtotal_minor: int, tax_minor: int, total_minor: int, effective_cap_minor: int,
           requested_at: str, expires_at: str) -> None:
    conn.execute(
        """INSERT INTO agent_confirmations (
             confirmation_id, session_id, cart_id, cart_version, snapshot_hash, snapshot_json,
             currency, subtotal_minor, tax_minor, total_minor, effective_cap_minor, status,
             requested_at, expires_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
        (confirmation_id, session_id, cart_id, cart_version, snapshot_hash, snapshot_json,
         currency, subtotal_minor, tax_minor, total_minor, effective_cap_minor, requested_at,
         expires_at),
    )


def approve(conn: sqlite3.Connection, confirmation_id: str, *, decided_by_user_id: str,
            decided_at: str) -> None:
    conn.execute(
        """UPDATE agent_confirmations SET status = 'approved', decided_at = ?,
             decided_by_user_id = ? WHERE confirmation_id = ?""",
        (decided_at, decided_by_user_id, confirmation_id),
    )


def decline(conn: sqlite3.Connection, confirmation_id: str, *, decided_by_user_id: str,
            decided_at: str, decision_note: Optional[str]) -> None:
    conn.execute(
        """UPDATE agent_confirmations SET status = 'declined', decided_at = ?,
             decided_by_user_id = ?, decision_note = ? WHERE confirmation_id = ?""",
        (decided_at, decided_by_user_id, decision_note, confirmation_id),
    )


def close(conn: sqlite3.Connection, confirmation_id: str, *, status: str, closed_reason: str) -> None:
    """status in ('expired', 'invalidated')."""
    conn.execute(
        "UPDATE agent_confirmations SET status = ?, closed_reason = ? WHERE confirmation_id = ?",
        (status, closed_reason, confirmation_id),
    )


def consume(conn: sqlite3.Connection, confirmation_id: str, *, consumed_at: str, booking_id: str) -> None:
    conn.execute(
        """UPDATE agent_confirmations SET status = 'consumed', consumed_at = ?,
             consumed_by_booking_id = ? WHERE confirmation_id = ?""",
        (consumed_at, booking_id, confirmation_id),
    )
