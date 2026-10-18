"""Shared test fixtures. Tests never write the original database.

Database tests need APS_DB_ORIGINAL_PATH (path to the original APS-01.db). They copy it
into a temporary directory with the approved working-copy mechanism and work only there.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

from src.core.config import Settings
from src.core.hashing import file_sha256
from src.db.migrations.runner import apply_migrations
from src.db.working_copy_guard import make_working_copy

RECORDED_ORIGINAL_SHA256 = "ecc58821ccb7f7d19a23bac157e95ba84521238b40ba52ad568d7932675cae0a"

EXPECTED_EXISTING_ROW_COUNTS = {
    "currencies": 25, "inventory_calendar": 15030, "languages": 26, "countries": 30,
    "airlines": 30, "cities": 60, "eval_nl_search_set": 100, "hotels": 300, "users": 1200,
    "airports": 80, "flights": 4000, "hotel_room_types": 1200, "trips": 600,
    "agent_sessions": 712, "budgets": 600, "flight_fares": 8002, "itineraries": 803,
    "itinerary_items": 8583, "bookings": 2008, "holds": 509, "payments": 2008,
    "booking_items": 2690,
}

LEGACY_AGENT_ROW_COUNTS = {
    "agent_carts": 171, "agent_confirmations": 171, "agent_conversations": 1614,
    "agent_events": 5737, "agent_plans": 704, "agent_replan_history": 62,
    "agent_runtime_state": 620, "agent_tool_results": 757, "agent_transactions": 12,
}


def original_path() -> str:
    path = os.environ.get("APS_DB_ORIGINAL_PATH")
    if not path:
        raise RuntimeError("Set APS_DB_ORIGINAL_PATH to the original APS-01.db to run database tests")
    return path


def assert_original_untouched() -> None:
    actual = file_sha256(original_path())
    if actual != RECORDED_ORIGINAL_SHA256:
        raise AssertionError(f"ORIGINAL DATABASE CHANGED: {actual} != {RECORDED_ORIGINAL_SHA256}")


def settings_for(db_path: str, original: str | None = None, sha: str | None = None, **extra) -> Settings:
    env = {
        "APS_DB_PATH": db_path,
        "APS_DB_ORIGINAL_PATH": original if original is not None else original_path(),
        "APS_DB_ORIGINAL_SHA256": sha if sha is not None else RECORDED_ORIGINAL_SHA256,
    }
    env.update(extra)
    return Settings.from_env(env)


def find_flight_offer(conn, *, currency: str = "INR", min_units: int = 1) -> dict:
    row = conn.execute(
        """SELECT ff.fare_id, ff.flight_id, ic.inventory_id, ic.for_date, ic.price
           FROM flight_fares ff
           JOIN inventory_calendar ic ON ic.entity_type='flight_fare' AND ic.entity_id=ff.fare_id
           WHERE ic.currency = ? AND (ic.total_units - ic.booked_units - ic.held_units) >= ?
             AND ff.status = 'active'
           ORDER BY ic.for_date LIMIT 1""",
        (currency, min_units),
    ).fetchone()
    if row is None:
        raise AssertionError("no usable flight fixture found in the working copy")
    return dict(row)


def find_hotel_offer(conn, *, currency: str = "INR", nights: int = 2, min_rooms: int = 1) -> dict:
    room_types = conn.execute(
        "SELECT room_type_id, hotel_id, max_adults, max_children, max_occupancy "
        "FROM hotel_room_types WHERE status = 'active'"
    ).fetchall()
    for rt in room_types:
        rows = conn.execute(
            """SELECT inventory_id, for_date, price, min_stay_nights, closed_to_arrival
               FROM inventory_calendar
               WHERE entity_type = 'room_type' AND entity_id = ? AND currency = ?
                 AND (total_units - booked_units - held_units) >= ?
               ORDER BY for_date""",
            (rt["room_type_id"], currency, min_rooms),
        ).fetchall()
        for i in range(len(rows) - nights + 1):
            window = rows[i:i + nights]
            dates = [d["for_date"] for d in window]
            from datetime import date as _date
            consecutive = all(
                (_date.fromisoformat(dates[j + 1]) - _date.fromisoformat(dates[j])).days == 1
                for j in range(len(dates) - 1)
            )
            if not consecutive:
                continue
            if window[0]["closed_to_arrival"]:
                continue
            if any(w["min_stay_nights"] > nights for w in window):
                continue
            return {"room_type_id": rt["room_type_id"], "hotel_id": rt["hotel_id"],
                    "max_adults": rt["max_adults"], "max_children": rt["max_children"],
                    "max_occupancy": rt["max_occupancy"],
                    "nights": [dict(w) for w in window]}
    raise AssertionError("no usable hotel fixture found in the working copy")


def insert_trip_and_budget(conn, *, user_id: str, start_date: str, end_date: str, party_size: int,
                            adults: int, children: int, currency: str, budget_total: str,
                            alert_threshold_pct: int = 80) -> tuple[str, str]:
    from src.core.ids import new_id
    trip_id = new_id("trp")
    now = "2026-01-01T00:00:00+05:30"
    conn.execute(
        """INSERT INTO trips (trip_id, owner_user_id, title, origin_city_id, destination_city_id,
             start_date, end_date, party_size, adults, children, trip_type, is_group_trip, status,
             home_currency, notes, created_at, updated_at)
           VALUES (?, ?, 'Test trip', NULL,
                   (SELECT city_id FROM cities LIMIT 1), ?, ?, ?, ?, ?, 'leisure', 0, 'planning',
                   ?, 'TEST FIXTURE', ?, ?)""",
        (trip_id, user_id, start_date, end_date, party_size, adults, children, currency, now, now),
    )
    budget_id = new_id("bud")
    total = float(budget_total)
    conn.execute(
        """INSERT INTO budgets (budget_id, trip_id, total_amount, currency, accommodation_cap,
             transport_cap, food_cap, activities_cap, misc_cap, alert_threshold_pct,
             created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (budget_id, trip_id, budget_total, currency,
         f"{total * 0.36:.2f}", f"{total * 0.18:.2f}", f"{total * 0.18:.2f}",
         f"{total * 0.135:.2f}", f"{total * 0.045:.2f}", alert_threshold_pct, now, now),
    )
    return trip_id, budget_id


class WorkingCopy:
    """A temporary, stamped (and optionally migrated) working copy of the original."""

    def __init__(self, migrate: bool = True):
        self.dir = tempfile.mkdtemp(prefix="t4wc-")
        self.path = os.path.join(self.dir, "aps01_working.db")
        make_working_copy(original_path(), RECORDED_ORIGINAL_SHA256, self.path)
        self.settings = settings_for(self.path)
        if migrate:
            apply_migrations(self.settings)

    def raw(self, readonly: bool = False) -> sqlite3.Connection:
        mode = "ro" if readonly else "rw"
        conn = sqlite3.connect(Path(self.path).resolve().as_uri() + f"?mode={mode}", uri=True,
                               isolation_level=None)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def cleanup(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)
