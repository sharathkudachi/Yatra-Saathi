"""Repository for Phase 5 tables: booking_travellers, phase5_booking_events, trip_packs.

All writes must occur within the caller's transaction.
No reads bypass ownership — all ownership checks happen in the service layer.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Optional


# ============================================================
# booking_travellers
# ============================================================

@dataclass(frozen=True)
class BookingTraveller:
    traveller_id: str
    booking_id: str
    traveller_seq: int
    display_name: str
    traveller_role: str
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "BookingTraveller":
        return cls(**{k: row[k] for k in row.keys()})


def insert_traveller(
    conn: sqlite3.Connection,
    *,
    traveller_id: str,
    booking_id: str,
    traveller_seq: int,
    display_name: str,
    traveller_role: str,
    created_at: str,
) -> None:
    conn.execute(
        """INSERT INTO booking_travellers
           (traveller_id, booking_id, traveller_seq, display_name, traveller_role, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (traveller_id, booking_id, traveller_seq, display_name, traveller_role, created_at),
    )


def list_travellers(conn: sqlite3.Connection, booking_id: str) -> list[BookingTraveller]:
    rows = conn.execute(
        "SELECT * FROM booking_travellers WHERE booking_id = ? ORDER BY traveller_seq",
        (booking_id,),
    ).fetchall()
    return [BookingTraveller.from_row(r) for r in rows]


# ============================================================
# phase5_booking_events
# ============================================================

@dataclass(frozen=True)
class Phase5BookingEvent:
    event_id: str
    booking_id: str
    user_id: str
    event_type: str
    occurred_at: str
    actor: str
    prev_status: Optional[str]
    new_status: Optional[str]
    metadata_json: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Phase5BookingEvent":
        return cls(**{k: row[k] for k in row.keys()})


def insert_event(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    booking_id: str,
    user_id: str,
    event_type: str,
    occurred_at: str,
    actor: str = "system",
    prev_status: Optional[str] = None,
    new_status: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    conn.execute(
        """INSERT INTO phase5_booking_events
           (event_id, booking_id, user_id, event_type, occurred_at, actor,
            prev_status, new_status, metadata_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event_id, booking_id, user_id, event_type, occurred_at, actor,
            prev_status, new_status, json.dumps(metadata or {}),
        ),
    )


def list_events(conn: sqlite3.Connection, booking_id: str) -> list[Phase5BookingEvent]:
    rows = conn.execute(
        "SELECT * FROM phase5_booking_events WHERE booking_id = ? ORDER BY occurred_at",
        (booking_id,),
    ).fetchall()
    return [Phase5BookingEvent.from_row(r) for r in rows]


# ============================================================
# Extended bookings repository access
# ============================================================

def get_booking_with_ownership(
    conn: sqlite3.Connection, booking_id: str, user_id: str
) -> Optional[dict]:
    """Get a booking only if it belongs to user_id. Returns None if not found or not owned."""
    row = conn.execute(
        "SELECT * FROM bookings WHERE booking_id = ? AND user_id = ?",
        (booking_id, user_id),
    ).fetchone()
    return dict(row) if row else None


def get_booking_by_reference(conn: sqlite3.Connection, booking_reference: str, user_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM bookings WHERE booking_reference = ? AND user_id = ?",
        (booking_reference, user_id),
    ).fetchone()
    return dict(row) if row else None


def list_user_bookings(conn: sqlite3.Connection, user_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT b.*, t.title as trip_title,
               (SELECT cd.name FROM cities cd WHERE cd.city_id = t.destination_city_id) as destination,
               (SELECT co.name FROM cities co WHERE co.city_id = t.origin_city_id) as origin
           FROM bookings b
           LEFT JOIN trips t ON t.trip_id = b.trip_id
           WHERE b.user_id = ?
           ORDER BY b.created_at DESC""",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def cancel_booking(
    conn: sqlite3.Connection,
    booking_id: str,
    *,
    cancelled_at: str,
    cancellation_reason: Optional[str],
    updated_at: str,
) -> None:
    conn.execute(
        """UPDATE bookings SET status = 'cancelled', lifecycle_status = 'cancelled',
           cancelled_at = ?, cancellation_reason = ?, updated_at = ?
           WHERE booking_id = ?""",
        (cancelled_at, cancellation_reason, updated_at, booking_id),
    )


def update_lifecycle_status(
    conn: sqlite3.Connection,
    booking_id: str,
    lifecycle_status: str,
    updated_at: str,
) -> None:
    conn.execute(
        "UPDATE bookings SET lifecycle_status = ?, updated_at = ? WHERE booking_id = ?",
        (lifecycle_status, updated_at, booking_id),
    )


def get_booking_items_for_booking(conn: sqlite3.Connection, booking_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM booking_items WHERE booking_id = ? AND status = 'active' ORDER BY for_date",
        (booking_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ============================================================
# trip_packs
# ============================================================

@dataclass(frozen=True)
class TripPack:
    pack_id: str
    booking_id: str
    user_id: str
    pack_json: str
    pack_version: int
    is_demo: int
    demo_label: str
    generated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "TripPack":
        return cls(**{k: row[k] for k in row.keys()})


def get_trip_pack(conn: sqlite3.Connection, booking_id: str, user_id: str) -> Optional[TripPack]:
    row = conn.execute(
        "SELECT * FROM trip_packs WHERE booking_id = ? AND user_id = ?",
        (booking_id, user_id),
    ).fetchone()
    return TripPack.from_row(row) if row else None


def upsert_trip_pack(
    conn: sqlite3.Connection,
    *,
    pack_id: str,
    booking_id: str,
    user_id: str,
    pack_data: dict,
    generated_at: str,
) -> None:
    """Insert or replace the trip pack for a booking (one per booking)."""
    pack_json = json.dumps(pack_data, sort_keys=True, ensure_ascii=False)
    # Check if exists
    existing = conn.execute(
        "SELECT pack_id, pack_version FROM trip_packs WHERE booking_id = ?",
        (booking_id,),
    ).fetchone()
    if existing:
        new_version = existing["pack_version"] + 1
        conn.execute(
            """UPDATE trip_packs SET pack_json = ?, pack_version = ?, generated_at = ?
               WHERE booking_id = ?""",
            (pack_json, new_version, generated_at, booking_id),
        )
    else:
        conn.execute(
            """INSERT INTO trip_packs
               (pack_id, booking_id, user_id, pack_json, pack_version, is_demo, demo_label, generated_at)
               VALUES (?, ?, ?, ?, 1, 1, 'YATRA DEMO TRIP PACK', ?)""",
            (pack_id, booking_id, user_id, pack_json, generated_at),
        )
