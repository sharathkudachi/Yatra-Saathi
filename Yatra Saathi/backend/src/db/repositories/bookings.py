"""Repository for `bookings`, `booking_items`, `payments` (existing tables).

Writes here happen only inside the final booking transaction (section 8.5).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class BookingLine:
    entity_type: str
    entity_id: str
    inventory_id: str
    title: str
    for_date: str
    units: int
    unit_price: str
    line_total: str
    currency: str


def get_by_session_confirmed(conn: sqlite3.Connection, session_id: str) -> Optional[dict]:
    row = conn.execute(
        """SELECT b.* FROM bookings b
           JOIN agent_confirmations c ON c.consumed_by_booking_id = b.booking_id
           WHERE c.session_id = ? AND c.status = 'consumed'""",
        (session_id,),
    ).fetchone()
    return dict(row) if row else None


def insert_booking(conn: sqlite3.Connection, *, booking_id: str, user_id: str, trip_id: Optional[str],
                    booking_reference: str, total_amount: str, currency: str, tax_amount: str,
                    idempotency_key: str, created_at: str) -> None:
    conn.execute(
        """INSERT INTO bookings (
             booking_id, user_id, trip_id, itinerary_id, booking_reference, channel,
             total_amount, currency, tax_amount, idempotency_key, status, confirmed_at,
             cancelled_at, cancellation_reason, created_at, updated_at
           ) VALUES (?, ?, ?, NULL, ?, 'agent', ?, ?, ?, ?, 'confirmed', ?, NULL, NULL, ?, ?)""",
        (booking_id, user_id, trip_id, booking_reference, total_amount, currency, tax_amount,
         idempotency_key, created_at, created_at, created_at),
    )


def insert_booking_item(conn: sqlite3.Connection, *, booking_item_id: str, booking_id: str,
                         line: BookingLine, updated_at: str) -> None:
    conn.execute(
        """INSERT INTO booking_items (
             booking_item_id, booking_id, entity_type, entity_id, inventory_id, title,
             for_date, units, unit_price, line_total, currency, status, compensated_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', NULL, ?)""",
        (booking_item_id, booking_id, line.entity_type, line.entity_id, line.inventory_id,
         line.title, line.for_date, line.units, line.unit_price, line.line_total, line.currency,
         updated_at),
    )


def insert_payment(conn: sqlite3.Connection, *, payment_id: str, booking_id: str, amount: str,
                    currency: str, gateway_reference: str, idempotency_key: str,
                    created_at: str) -> None:
    conn.execute(
        """INSERT INTO payments (
             payment_id, booking_id, method, status, authorised_amount, captured_amount,
             refunded_amount, currency, gateway_reference, idempotency_key, failure_code,
             authorised_at, captured_at, created_at, updated_at
           ) VALUES (?, ?, 'mock', 'captured', ?, ?, '0.00', ?, ?, ?, NULL, ?, ?, ?, ?)""",
        (payment_id, booking_id, amount, amount, currency, gateway_reference, idempotency_key,
         created_at, created_at, created_at, created_at),
    )


def get_by_idempotency_key(conn: sqlite3.Connection, idempotency_key: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM bookings WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
    return dict(row) if row else None
