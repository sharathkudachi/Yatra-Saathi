"""Explicit, sanitized catalog seeder for PostgreSQL (Neon / Cloud).

Transfers ONLY the static public reference catalog tables from local SQLite to PostgreSQL:
- cities, airports, airlines, flights, flight_fares
- hotels, hotel_room_types, inventory_calendar
- currencies, countries, languages

EXPLICITLY EXCLUDES all user data, booking records, payments, itineraries, and agent histories:
- NEVER touches users, trips, budgets, bookings, payments, holds, or agent_* tables.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

# Ensure the backend root directory is on sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from dotenv import load_dotenv

for candidate in [Path(__file__).parent.parent / ".env.backend", Path(".env.backend"), Path("backend/.env.backend")]:
    if candidate.exists():
        load_dotenv(candidate)
        break
load_dotenv()

from src.core.config import Settings
from src.db.postgres import connect_postgres
from src.db.postgres_schema import init_postgres_schema

CATALOG_TABLES = [
    "currencies",
    "countries",
    "languages",
    "cities",
    "airports",
    "airlines",
    "hotels",
    "hotel_room_types",
    "flights",
    "flight_fares",
    "inventory_calendar",
]


def seed_catalog(sqlite_path: str, pg_url: str, batch_size: int = 500) -> dict[str, int]:
    if not os.path.isfile(sqlite_path):
        raise FileNotFoundError(f"Source SQLite database not found: {sqlite_path}")

    print(f"[Seed Catalog] Opening source SQLite database (read-only): {sqlite_path}")
    src_conn = sqlite3.connect(Path(sqlite_path).resolve().as_uri() + "?mode=ro", uri=True)

    print(f"[Seed Catalog] Connecting to PostgreSQL...")
    pg_conn = connect_postgres(pg_url, use_pool=False)

    counts = {}
    try:
        # 1. Ensure schema exists
        init_postgres_schema(pg_conn)

        # 2. Transfer each catalog table
        for table in CATALOG_TABLES:
            # Check row count in source
            total = src_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"[Seed Catalog] Transferring '{table}' ({total} rows)...")

            # Fetch all rows from source
            cur = src_conn.execute(f"SELECT * FROM {table}")
            cols = [d[0] for d in cur.description]
            col_names = ", ".join(cols)
            placeholders = ", ".join(["%s"] * len(cols))
            insert_sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

            inserted = 0
            while True:
                rows = cur.fetchmany(batch_size)
                if not rows:
                    break
                pg_cur = pg_conn._raw_conn.cursor()
                pg_cur.executemany(insert_sql, rows)
                pg_cur.close()
                inserted += len(rows)

            pg_conn.commit()
            counts[table] = inserted
            print(f"[Seed Catalog] Successfully transferred {inserted} rows into '{table}'.")

    finally:
        src_conn.close()
        pg_conn.close()

    print("[Seed Catalog] Catalog seed complete.")
    return counts


def main():
    settings = Settings.from_env()
    if not settings.database_url:
        print("[Seed Catalog] ERROR: DATABASE_URL environment variable is required.", file=sys.stderr)
        sys.exit(1)

    sqlite_source = settings.db_path or settings.original_db_path
    if not sqlite_source:
        print("[Seed Catalog] ERROR: APS_DB_PATH or APS_DB_ORIGINAL_PATH is required as source.", file=sys.stderr)
        sys.exit(1)

    seed_catalog(sqlite_source, settings.database_url)


if __name__ == "__main__":
    main()
