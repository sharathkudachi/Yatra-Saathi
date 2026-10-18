"""Repository for `holds` (existing table). This backend only releases/expires
holds it created itself (idempotency_key prefix 'hidem_'), per the approved rule."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Hold:
    hold_id: str
    inventory_id: str
    user_id: str
    units: int
    idempotency_key: str
    created_at: str
    expires_at: str
    released_at: Optional[str]
    booking_id: Optional[str]
    status: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Hold":
        return cls(**{k: row[k] for k in row.keys()})


def get(conn: sqlite3.Connection, hold_id: str) -> Optional[Hold]:
    row = conn.execute("SELECT * FROM holds WHERE hold_id = ?", (hold_id,)).fetchone()
    return Hold.from_row(row) if row else None


def get_by_idempotency_key(conn: sqlite3.Connection, idempotency_key: str) -> Optional[Hold]:
    row = conn.execute("SELECT * FROM holds WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
    return Hold.from_row(row) if row else None


def insert(conn: sqlite3.Connection, *, hold_id: str, inventory_id: str, user_id: str, units: int,
           idempotency_key: str, created_at: str, expires_at: str) -> None:
    conn.execute(
        """INSERT INTO holds (hold_id, inventory_id, user_id, units, idempotency_key, created_at,
             expires_at, released_at, booking_id, status, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'active', ?)""",
        (hold_id, inventory_id, user_id, units, idempotency_key, created_at, expires_at, created_at),
    )
    conn.execute(
        "UPDATE inventory_calendar SET held_units = held_units + ? WHERE inventory_id = ?",
        (units, inventory_id),
    )


def release(conn: sqlite3.Connection, hold_id: str, *, released_at: str) -> None:
    hold = get(conn, hold_id)
    if hold is None or hold.status != "active":
        return
    conn.execute(
        "UPDATE holds SET status = 'released', released_at = ?, updated_at = ? WHERE hold_id = ?",
        (released_at, released_at, hold_id),
    )
    conn.execute(
        "UPDATE inventory_calendar SET held_units = held_units - ? WHERE inventory_id = ?",
        (hold.units, hold.inventory_id),
    )


def confirm(conn: sqlite3.Connection, hold_id: str, *, booking_id: str, updated_at: str) -> None:
    hold = get(conn, hold_id)
    if hold is None:
        return
    conn.execute(
        "UPDATE holds SET status = 'confirmed', booking_id = ?, updated_at = ? WHERE hold_id = ?",
        (booking_id, updated_at, hold_id),
    )
    conn.execute(
        "UPDATE inventory_calendar SET held_units = held_units - ?, booked_units = booked_units + ? "
        "WHERE inventory_id = ?",
        (hold.units, hold.units, hold.inventory_id),
    )


def expire(conn: sqlite3.Connection, hold_id: str, *, updated_at: str) -> None:
    hold = get(conn, hold_id)
    if hold is None or hold.status != "active":
        return
    conn.execute(
        "UPDATE holds SET status = 'expired', updated_at = ? WHERE hold_id = ?",
        (updated_at, hold_id),
    )
    conn.execute(
        "UPDATE inventory_calendar SET held_units = held_units - ? WHERE inventory_id = ?",
        (hold.units, hold.inventory_id),
    )
