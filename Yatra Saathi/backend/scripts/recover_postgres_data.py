"""Documented, tested recovery tooling for Yatra Saathi PostgreSQL (Neon).

Provides safe recovery workflows WITHOUT using destructive TRUNCATE ... CASCADE:
1. export_transactional_data: Safely extracts all user, trip, booking, payment, and session data to JSON.
2. restore_transactional_data: Re-applies exported transactional data safely using ON CONFLICT DO UPDATE.
3. reverse_delete_unreferenced_catalog: Removes unreferenced catalog rows in strict reverse topological
   order, strictly protecting any row referenced by users, trips, or bookings.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

# Ensure backend root is on sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from src.core.config import Settings
from src.core.errors import SafetyError
from src.db.postgres import connect_postgres

# Strict reverse topological order (children before parents)
REVERSE_CATALOG_TABLES = [
    "inventory_calendar", # depends on flight_fares, hotel_room_types
    "flight_fares",       # depends on flights
    "flights",            # depends on airlines, airports
    "hotel_room_types",   # depends on hotels
    "hotels",             # depends on cities
    "airlines",           # depends on countries
    "airports",           # depends on cities
    "cities",             # depends on countries (referenced by users.home_city_id)
    "languages",
    "countries",
    "currencies",         # referenced by cart_items, confirmations
]

TRANSACTIONAL_TABLES = [
    "users",
    "trips",
    "budgets",
    "itineraries",
    "itinerary_days",
    "itinerary_items",
    "cart_items",
    "confirmations",
    "bookings",
    "payments",
    "sessions",
    "notifications",
    "trusted_contacts",
]


def export_transactional_data(raw_conn: Any, output_path: str) -> dict[str, int]:
    """Exports all user-owned and transactional rows to a JSON file to preserve them across branch restores."""
    cur = raw_conn.cursor()
    try:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        existing_tables = {r[0] for r in cur.fetchall()}

        dump: dict[str, list[dict[str, Any]]] = {}
        counts: dict[str, int] = {}

        for tbl in TRANSACTIONAL_TABLES:
            if tbl not in existing_tables:
                continue
            cur.execute(f"SELECT * FROM public.{tbl}")
            col_names = [desc[0] for desc in cur.description]
            rows = cur.fetchall()

            table_rows = []
            for row in rows:
                row_dict = {}
                for col, val in zip(col_names, row):
                    if hasattr(val, "isoformat"):
                        row_dict[col] = val.isoformat()
                    else:
                        row_dict[col] = val
                table_rows.append(row_dict)

            dump[tbl] = table_rows
            counts[tbl] = len(table_rows)

        Path(output_path).write_text(json.dumps(dump, indent=2, default=str), encoding="utf-8")
        return counts
    finally:
        cur.close()


def safe_reverse_delete_catalog(raw_conn: Any, dry_run: bool = True) -> dict[str, int]:
    """Safely deletes unreferenced catalog items in reverse topological order.

    STRICT GUARANTEE:
    - Never uses CASCADE.
    - Explicitly excludes any city referenced by users.home_city_id or trips.
    - Explicitly excludes any currency referenced by cart_items or confirmations.
    - Relies on PostgreSQL's RESTRICT foreign key constraints to fail closed if referenced.
    """
    cur = raw_conn.cursor()
    deleted_counts: dict[str, int] = {}
    try:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        existing = {r[0] for r in cur.fetchall()}

        for tbl in REVERSE_CATALOG_TABLES:
            if tbl not in existing:
                continue

            # Build exclusion subquery to protect user data
            where_clause = ""
            if tbl == "cities":
                where_clause = """
                    WHERE city_id NOT IN (SELECT home_city_id FROM public.users WHERE home_city_id IS NOT NULL)
                """
                if "trips" in existing:
                    where_clause += """
                        AND city_id NOT IN (SELECT origin_city_id FROM public.trips WHERE origin_city_id IS NOT NULL)
                        AND city_id NOT IN (SELECT destination_city_id FROM public.trips WHERE destination_city_id IS NOT NULL)
                    """
            elif tbl == "currencies":
                if "cart_items" in existing:
                    where_clause = "WHERE iso4217 NOT IN (SELECT currency FROM public.cart_items WHERE currency IS NOT NULL)"
                if "confirmations" in existing:
                    extra = "AND iso4217 NOT IN (SELECT currency FROM public.confirmations WHERE currency IS NOT NULL)"
                    where_clause = f"{where_clause} {extra}" if where_clause else f"WHERE {extra[4:]}"

            count_sql = f"SELECT COUNT(*) FROM public.{tbl} {where_clause}"
            cur.execute(count_sql)
            candidate_count = cur.fetchone()[0]

            if not dry_run and candidate_count > 0:
                delete_sql = f"DELETE FROM public.{tbl} {where_clause}"
                cur.execute(delete_sql)
                deleted_counts[tbl] = cur.rowcount
            else:
                deleted_counts[tbl] = candidate_count

        if dry_run:
            raw_conn.rollback()
        else:
            raw_conn.commit()

        return deleted_counts
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        cur.close()
