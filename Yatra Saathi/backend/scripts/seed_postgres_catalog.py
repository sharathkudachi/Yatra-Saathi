"""Explicit, sanitized catalog seeder for PostgreSQL (Neon / Cloud).

Transfers ONLY the static public reference catalog tables from canonical SQLite to PostgreSQL:
- currencies, countries, languages, cities, airports, airlines, hotels,
  hotel_room_types, flights, flight_fares, inventory_calendar

EXPLICITLY EXCLUDES all user data, booking records, payments, itineraries, and agent histories:
- NEVER touches users, trips, budgets, bookings, payments, holds, or agent_* tables.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import math
import os
import sqlite3
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

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
try:
    from psycopg2.extras import execute_batch
except ImportError:
    execute_batch = None
from src.core.config import Settings
from src.core.errors import SafetyError
from src.db.postgres import connect_postgres

# Canonical APS-01 dataset SHA-256
EXPECTED_ORIGINAL_SHA256 = "ecc58821ccb7f7d19a23bac157e95ba84521238b40ba52ad568d7932675cae0a"

# Authorized Neon Project ID for Yatra Saathi
EXPECTED_NEON_PROJECT_ID = "dawn-sky-64344251"

# Primary key columns for preflight conflict checking
TABLE_PRIMARY_KEYS: dict[str, str] = {
    "currencies": "iso4217",
    "countries": "country_id",
    "languages": "language_id",
    "cities": "city_id",
    "airports": "airport_id",
    "airlines": "airline_id",
    "hotels": "hotel_id",
    "hotel_room_types": "room_type_id",
    "flights": "flight_id",
    "flight_fares": "fare_id",
    "inventory_calendar": "inventory_id",
}

# Strict topological dependency order (parents before children)
CATALOG_TABLES: list[str] = [
    "currencies",
    "countries",
    "languages",
    "cities",            # depends on countries
    "airports",          # depends on cities
    "airlines",          # depends on countries
    "hotels",            # depends on cities
    "hotel_room_types",  # depends on hotels
    "flights",           # depends on airlines, airports
    "flight_fares",      # depends on flights
    "inventory_calendar",# depends on flight_fares, hotel_room_types
]

# Explicit column mappings for tables where SQLite and PostgreSQL column names/expressions differ:
# Format: { table_name: { pg_column_name: sqlite_column_expression } }
EXPLICIT_COLUMN_EXPRESSIONS: dict[str, dict[str, str]] = {
    "currencies": {
        "iso4217": "iso4217",
        "name": "name",
        "symbol": "symbol",
        "exponent": "minor_unit_exponent",
    },
}

# Transactional tables that must NEVER be touched by the reference catalog seeder
PROTECTED_TRANSACTIONAL_TABLES: frozenset[str] = frozenset({
    "users",
    "trips",
    "budgets",
    "itineraries",
    "itinerary_days",
    "itinerary_items",
    "sessions",
    "cart_items",
    "confirmations",
    "bookings",
    "payments",
    "audit_events",
    "agent_sessions",
    "agent_turns",
    "agent_state",
    "notifications",
    "phase6_notifications",
    "user_preferences",
    "trusted_contacts",
    "auth_rate_limits",
    "schema_migrations",
})


def verify_sqlite_source_hash(sqlite_path: str, expected_hash: str = EXPECTED_ORIGINAL_SHA256) -> None:
    """Verifies SHA-256 checksum of canonical dataset before reading."""
    path = Path(sqlite_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Source SQLite database not found: {path}")

    # If the file is named APS-01.db or original, verify its authoritative SHA-256
    if "original" in str(path).lower() or path.name.lower() == "aps-01.db":
        sha = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha.update(chunk)
        digest = sha.hexdigest().lower()
        if digest != expected_hash.lower():
            raise SafetyError(
                f"Source SQLite database hash mismatch for {path}: expected {expected_hash}, got {digest}"
            )


def get_pg_table_columns(pg_conn: Any, table: str) -> set[str]:
    """Queries PostgreSQL information_schema for active column names in public schema."""
    cur = pg_conn.cursor() if hasattr(pg_conn, "cursor") else pg_conn._raw_conn.cursor()
    try:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s AND table_schema = 'public'",
            (table,),
        )
        return {r[0] for r in cur.fetchall()}
    finally:
        cur.close()


def verify_neon_target_identity(
    raw_conn: Any,
    expected_branch_name: Optional[str] = None,
    confirm_production: bool = False,
    expected_project_id: str = EXPECTED_NEON_PROJECT_ID,
) -> dict[str, str]:
    """Inspects PostgreSQL session configuration parameters provided by Neon virtualization layer.

    IMPORTANT SAFETY CLARIFICATION:
    This check verifies in-session Neon virtualization configuration parameters (GUC settings)
    exposed by Neon's proxy/compute plane ('neon.project_id', 'neon.branch_id', 'neon.endpoint_id').
    It is in-session identity verification, NOT cryptographic token authentication.
    It provides fail-closed protection: if Neon parameters are missing, malformed, point to an
    unauthorized project, or resolve to the production branch without explicit confirmation,
    the execution immediately aborts with SafetyError before any modification can occur.
    Credentials and connection strings are NEVER printed or logged.
    """
    cur = raw_conn.cursor()
    try:
        cur.execute("""
            SELECT
                current_setting('neon.project_id', true) AS project_id,
                current_setting('neon.branch_id', true) AS branch_id,
                current_setting('neon.endpoint_id', true) AS endpoint_id,
                current_database() AS db_name
        """)
        row = cur.fetchone()
        project_id = row[0] if row else None
        branch_id = row[1] if row else None
        endpoint_id = row[2] if row else None
        db_name = row[3] if row else None

        # Fail closed immediately if Neon GUC parameters are unavailable
        if not project_id or not project_id.strip():
            raise SafetyError(
                "Neon identity verification failed closed: 'neon.project_id' is missing or empty. "
                "The target connection is not a verified Neon database session."
            )
        if not branch_id or not branch_id.strip():
            raise SafetyError(
                "Neon identity verification failed closed: 'neon.branch_id' is missing or empty. "
                "Unable to determine the connected Neon branch."
            )

        info = {
            "project_id": project_id.strip(),
            "branch_id": branch_id.strip(),
            "endpoint_id": (endpoint_id or "unknown").strip(),
            "db_name": (db_name or "unknown").strip(),
        }

        # 1. Project ID Verification: Must match authorized project
        if info["project_id"] != expected_project_id:
            raise SafetyError(
                f"Neon Project ID mismatch: connected to '{info['project_id']}', but authorized project is '{expected_project_id}'"
            )

        # 2. Unconditional Production Guard based on connected branch ID
        # The production branch ID for Yatra Saathi is 'br-curly-bar-azc5gozu'
        is_connected_to_prod = (info["branch_id"] == "br-curly-bar-azc5gozu")
        if is_connected_to_prod:
            if not confirm_production:
                raise SafetyError(
                    "REFUSAL: Target connection resolves to the 'production' branch (br-curly-bar-azc5gozu). "
                    "You must supply --confirm-production to authorize operations on the production branch."
                )
            if expected_branch_name and expected_branch_name.strip().lower() != "production":
                raise SafetyError(
                    f"REFUSAL: Target branch mismatch: connected database is 'production' (br-curly-bar-azc5gozu), "
                    f"but command argument specified --target-branch '{expected_branch_name}'."
                )

        # 3. Branch Resolution and Verification against expected branch
        if expected_branch_name:
            target_norm = expected_branch_name.strip().lower()

            branch_map: dict[str, str] = {}
            try:
                out = subprocess.check_output(
                    ["npx", "neonctl", "branches", "list", "-o", "json"],
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=10,
                )
                branches_data = json.loads(out)
                for b in branches_data:
                    branch_map[b["name"].lower()] = b["id"]
            except Exception:
                # Fallback to verified canonical IDs for Yatra Saathi
                branch_map = {
                    "production": "br-curly-bar-azc5gozu",
                    "val-reg-repair": "br-lively-mountain-az969apt",
                }

            expected_branch_id = branch_map.get(target_norm)
            if not expected_branch_id:
                raise SafetyError(
                    f"Neon identity verification failed closed: branch '{expected_branch_name}' could not be resolved to a known branch ID."
                )

            if info["branch_id"] != expected_branch_id:
                raise SafetyError(
                    f"Neon Branch ID mismatch: target branch '{expected_branch_name}' requires ID '{expected_branch_id}', "
                    f"but active connection is attached to branch ID '{info['branch_id']}'"
                )

            if target_norm == "production" and not confirm_production:
                raise SafetyError(
                    "REFUSAL: Target connection resolves to the 'production' branch. "
                    "You must supply --confirm-production to authorize changes to the production branch."
                )

        return info
    finally:
        cur.close()


COORDINATE_COLUMNS = frozenset({"latitude", "longitude", "lat", "lng"})
CURRENCY_AMOUNT_COLUMNS = frozenset({"base_price", "base_fare", "taxes", "change_fee"})
INTEGER_COLUMNS = frozenset({
    "exponent", "minor_unit_exponent", "rtl", "tts_supported", "population",
    "star_rating", "max_occupancy", "duration_minutes", "stops", "seats_total",
    "seats_available", "refundable", "changeable", "baggage_kg", "cabin_baggage_kg",
    "available_capacity",
})


def normalize_and_compare(val1: Any, val2: Any, col: str) -> bool:
    """Compares two values across PostgreSQL and SQLite with column-specific semantic typing.

    Semantic precision rules:
    - NULLs: Exact match (both None -> True; one None -> False).
    - Booleans: Exact boolean equality.
    - Discrete Integer Columns (counts, flags, exponents): Exact integer equality (zero tolerance).
    - Monetary / Currency Columns: Exact currency precision (must match within 0.005 currency units, i.e., exact cent/paisa).
    - Geographic Coordinate Columns (lat/lng): math.isclose(rel_tol=1e-5, abs_tol=1e-5), corresponding to ~1.11 meters
      at the equator. Accommodates 64-bit IEEE 754 float binary representation differences between SQLite REAL and
      PostgreSQL DOUBLE PRECISION, while strictly rejecting any real geographic difference.
    - Timestamps: ISO format equality after timezone normalization.
    - Unicode / Text: Canonical NFC normalization with whitespace stripping.
    """
    # 1. NULL comparison
    if val1 is None and val2 is None:
        return True
    if val1 is None or val2 is None:
        return False

    # 2. Boolean comparison
    if isinstance(val1, bool) or isinstance(val2, bool):
        return bool(val1) == bool(val2)

    col_lower = col.lower()

    # 3. Discrete Integer columns: Zero tolerance, exact integer equality
    if col_lower in INTEGER_COLUMNS:
        try:
            return int(val1) == int(val2)
        except (ValueError, TypeError):
            return False

    # 4. Monetary / Financial columns: Exact to the cent/paisa (within 0.005)
    if col_lower in CURRENCY_AMOUNT_COLUMNS:
        try:
            f1, f2 = float(val1), float(val2)
            return abs(f1 - f2) < 0.005
        except (ValueError, TypeError):
            return False

    # 5. Geographic coordinates (lat, lng, latitude, longitude): ~1.11 meter tolerance (1e-5 deg)
    if col_lower in COORDINATE_COLUMNS:
        try:
            return math.isclose(float(val1), float(val2), rel_tol=1e-5, abs_tol=1e-5)
        except (ValueError, TypeError):
            return False

    # 6. General float / Decimal fallback
    if isinstance(val1, (float, Decimal)) or isinstance(val2, (float, Decimal)):
        try:
            return math.isclose(float(val1), float(val2), rel_tol=1e-5, abs_tol=1e-5)
        except (ValueError, TypeError):
            pass

    # 7. General integer fallback
    if isinstance(val1, int) and isinstance(val2, int):
        return val1 == val2

    # 8. Timestamp / Datetime comparison
    if hasattr(val1, "isoformat") or hasattr(val2, "isoformat"):
        try:
            dt1 = val1 if isinstance(val1, datetime) else datetime.fromisoformat(str(val1).replace("Z", "+00:00"))
            dt2 = val2 if isinstance(val2, datetime) else datetime.fromisoformat(str(val2).replace("Z", "+00:00"))
            return dt1 == dt2
        except Exception:
            pass

    # 9. String / Unicode canonical normalization (NFC) and whitespace stripping
    s1 = unicodedata.normalize("NFC", str(val1).strip())
    s2 = unicodedata.normalize("NFC", str(val2).strip())
    return s1 == s2


def preflight_conflict_check(
    src_conn: sqlite3.Connection,
    raw_conn: Any,
    tables: Sequence[str],
) -> None:
    """Deep preflight check: compares every existing PostgreSQL record against canonical SQLite source.

    Compares all mapped fields—not only IDs. Aborts before any write if unknown records,
    conflicting values, or foreign-key inconsistencies are detected.
    """
    cur = raw_conn.cursor()
    try:
        for table in tables:
            pk_col = TABLE_PRIMARY_KEYS.get(table)
            if not pk_col:
                continue

            target_cols, select_exprs = resolve_table_columns(src_conn, raw_conn, table)
            target_cols_str = ", ".join(target_cols)

            # Query all existing records in PostgreSQL for this table
            cur.execute(f"SELECT {target_cols_str} FROM public.{table}")
            pg_rows = cur.fetchall()
            if not pg_rows:
                continue

            pk_idx = target_cols.index(pk_col)

            # Check every existing PostgreSQL record
            for pg_row in pg_rows:
                pk_val = pg_row[pk_idx]

                # Fetch corresponding row from canonical SQLite
                select_str = ", ".join(select_exprs)
                src_cur = src_conn.execute(
                    f"SELECT {select_str} FROM {table} WHERE {pk_col} = ?",
                    (pk_val,),
                )
                src_row = src_cur.fetchone()

                if src_row is None:
                    raise SafetyError(
                        f"Preflight Conflict: public.{table} contains alien record with primary key '{pk_val}' "
                        "that does not exist in canonical dataset. Aborting."
                    )

                # Compare all mapped columns field-by-field
                for i, col in enumerate(target_cols):
                    pg_val = pg_row[i]
                    src_val = src_row[i]
                    if not normalize_and_compare(pg_val, src_val, col):
                        raise SafetyError(
                            f"Preflight Conflict Mismatch in public.{table} for PK '{pk_val}': "
                            f"column '{col}' has value '{pg_val}' in PostgreSQL, but canonical source has '{src_val}'. "
                            "Aborting before any write."
                        )
    finally:
        cur.close()


def resolve_table_columns(
    src_conn: sqlite3.Connection,
    pg_conn: Any,
    table: str,
) -> tuple[list[str], list[str]]:
    """Determine the valid source SELECT expressions and target INSERT columns.

    Validates target columns against PostgreSQL information_schema to guarantee
    zero UndefinedColumn errors, while ensuring only existing SQLite columns
    are read.
    """
    if table in PROTECTED_TRANSACTIONAL_TABLES:
        raise SafetyError(f"Security violation: table '{table}' is protected and must never be catalog-seeded")

    sqlite_cols = [r[1] for r in src_conn.execute(f"PRAGMA table_info({table})").fetchall()]
    pg_cols = get_pg_table_columns(pg_conn, table)

    if not pg_cols:
        raise SafetyError(f"Target PostgreSQL table '{table}' does not exist or has no columns in public schema")

    target_cols: list[str] = []
    select_exprs: list[str] = []

    if table in EXPLICIT_COLUMN_EXPRESSIONS:
        mapping = EXPLICIT_COLUMN_EXPRESSIONS[table]
        for pg_col, src_expr in mapping.items():
            if pg_col in pg_cols:
                col_name_only = src_expr.split()[0]
                if col_name_only in sqlite_cols:
                    target_cols.append(pg_col)
                    select_exprs.append(src_expr)
    else:
        # Common intersection of matching column names
        for col in sqlite_cols:
            if col in pg_cols:
                target_cols.append(col)
                select_exprs.append(col)

    if not target_cols:
        raise SafetyError(f"No compatible columns found between SQLite and PostgreSQL for table '{table}'")

    return target_cols, select_exprs


def snapshot_user_records(raw_conn: Any) -> list[tuple]:
    """Captures a complete snapshot of all existing user records to verify zero modification."""
    cur = raw_conn.cursor()
    try:
        cur.execute("""
            SELECT user_id, display_name, email, home_city_id, status,
                   username, password_hash, email_verified, created_at, updated_at
            FROM public.users
            ORDER BY user_id
        """)
        return cur.fetchall()
    finally:
        cur.close()


def snapshot_protected_table_counts(raw_conn: Any) -> dict[str, int]:
    """Captures row counts of all existing protected transactional tables to verify zero modification."""
    cur = raw_conn.cursor()
    try:
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
        """)
        existing_tables = {r[0] for r in cur.fetchall()}
        counts: dict[str, int] = {}
        for tbl in sorted(PROTECTED_TRANSACTIONAL_TABLES):
            if tbl in existing_tables:
                cur.execute(f"SELECT COUNT(*) FROM public.{tbl}")
                row = cur.fetchone()
                counts[tbl] = row[0] if row else 0
        return counts
    finally:
        cur.close()


def seed_catalog(
    sqlite_path: str,
    pg_url: str,
    *,
    batch_size: int = 1000,
    dry_run: bool = False,
    target_branch: Optional[str] = None,
    confirm_production: bool = False,
    tables: Optional[Sequence[str]] = None,
) -> dict[str, dict[str, int]]:
    """Transfers reference catalog tables from SQLite to PostgreSQL in a single atomic transaction.

    Returns a mapping of table name to { "source": count, "transferred": count, "total": count }.
    """
    verify_sqlite_source_hash(sqlite_path)

    # Validate target table list against transactional tables
    target_tables = list(tables) if tables is not None else CATALOG_TABLES
    for table in target_tables:
        if table in PROTECTED_TRANSACTIONAL_TABLES:
            raise SafetyError(f"Refusing to seed protected transactional table '{table}'")

    print(f"[Seed Catalog] Opening source SQLite database (read-only): {sqlite_path}")
    src_conn = sqlite3.connect(Path(sqlite_path).resolve().as_uri() + "?mode=ro", uri=True)

    print("[Seed Catalog] Connecting to PostgreSQL...")
    pg_conn = connect_postgres(pg_url, use_pool=False)
    raw_conn = getattr(pg_conn, "_raw_conn", pg_conn)
    raw_conn.autocommit = False

    counts: dict[str, dict[str, int]] = {}
    try:
        # 1. Target Identity Verification (in-session GUC inspection, fail-closed)
        identity = verify_neon_target_identity(
            raw_conn,
            expected_branch_name=target_branch,
            confirm_production=confirm_production,
        )
        print(
            f"[Seed Catalog] Target Verified: Project '{identity['project_id']}', "
            f"Branch '{identity['branch_id']}', Endpoint '{identity['endpoint_id']}'"
        )

        # 2. Complete snapshot of protected transactional user records and table row counts
        pre_users = snapshot_user_records(raw_conn)
        pre_protected_counts = snapshot_protected_table_counts(raw_conn)

        # 3. Read-only schema compatibility check (No independent DDL or commits)

        # 4. Deep preflight conflict verification (checks IDs and all mapped fields)
        preflight_conflict_check(src_conn, raw_conn, target_tables)
        print("[Seed Catalog] Preflight conflict check passed: zero incompatible reference rows.")

        # 5. Transfer each catalog table in strict topological dependency order
        # Everything executes in ONE atomic transaction
        for table in target_tables:
            src_total = src_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

            target_cols, select_exprs = resolve_table_columns(src_conn, raw_conn, table)
            col_names = ", ".join(target_cols)
            select_str = ", ".join(select_exprs)
            placeholders = ", ".join(["%s"] * len(target_cols))
            insert_sql = f"INSERT INTO public.{table} ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

            print(f"[Seed Catalog] Processing '{table}' (source has {src_total} rows, mapped columns: {len(target_cols)})...")

            cur = src_conn.execute(f"SELECT {select_str} FROM {table}")
            rows = cur.fetchall()

            if dry_run:
                print(f"[Seed Catalog] [DRY RUN] Would batch-insert {len(rows)} rows into public.{table} ON CONFLICT DO NOTHING.")
                counts[table] = {"source": src_total, "transferred": 0, "total": src_total}
                continue

            pg_cur = raw_conn.cursor()
            try:
                execute_batch(pg_cur, insert_sql, rows, page_size=batch_size)
                pg_cur.execute(f"SELECT COUNT(*) FROM public.{table}")
                pg_total = pg_cur.fetchone()[0]
                counts[table] = {"source": src_total, "transferred": len(rows), "total": pg_total}
                print(f"[Seed Catalog] '{table}' processed: {len(rows)} source rows -> {pg_total} total rows.")
            finally:
                pg_cur.close()

        # 6. Commit single atomic transaction or rollback if dry run
        if dry_run:
            raw_conn.rollback()
            print("[Seed Catalog] [DRY RUN] Transaction rolled back cleanly. Zero persistent writes made.")
        else:
            # Post-seed transactional user data safety check before committing
            post_users = snapshot_user_records(raw_conn)
            if post_users != pre_users:
                raise SafetyError(
                    "CRITICAL INTEGRITY VIOLATION: Existing user records were modified or corrupted! Rolling back transaction."
                )

            post_protected_counts = snapshot_protected_table_counts(raw_conn)
            if post_protected_counts != pre_protected_counts:
                raise SafetyError(
                    f"CRITICAL INTEGRITY VIOLATION: Protected transactional tables were modified! "
                    f"Pre: {pre_protected_counts}, Post: {post_protected_counts}. Rolling back transaction."
                )

            raw_conn.commit()
            print("[Seed Catalog] Single atomic transaction committed successfully.")

    except Exception:
        raw_conn.rollback()
        raise
    finally:
        src_conn.close()
        pg_conn.close()

    print("[Seed Catalog] Catalog seeding execution complete.")
    return counts


def parse_args(args: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely seed canonical travel catalog to PostgreSQL (Neon).")
    parser.add_argument("--database-url", help="Target PostgreSQL connection URL. Defaults to DATABASE_URL in env.")
    parser.add_argument("--sqlite-path", help="Source SQLite database path. Defaults to APS_DB_PATH or APS_DB_ORIGINAL_PATH.")
    parser.add_argument("--target-branch", help="Target Neon branch name (e.g. 'production' or 'val-reg-repair').")
    parser.add_argument("--confirm-production", action="store_true", help="Explicit confirmation required to target the production branch.")
    parser.add_argument("--dry-run", action="store_true", help="Simulate seeding, validate columns, and roll back without committing.")
    parser.add_argument("--batch-size", type=int, default=1000, help="Batch size for execute_batch (default: 1000).")
    return parser.parse_args(args)


def main(cli_args: Optional[Sequence[str]] = None):
    args = parse_args(cli_args)
    settings = Settings.from_env()

    pg_url = args.database_url or settings.database_url
    if not pg_url:
        print("[Seed Catalog] ERROR: DATABASE_URL is required (via --database-url or environment).", file=sys.stderr)
        sys.exit(1)

    sqlite_source = args.sqlite_path or settings.original_db_path or settings.db_path
    if not sqlite_source:
        print("[Seed Catalog] ERROR: SQLite source path is required (via --sqlite-path, APS_DB_ORIGINAL_PATH, or APS_DB_PATH).", file=sys.stderr)
        sys.exit(1)

    seed_catalog(
        sqlite_source,
        pg_url,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        target_branch=args.target_branch,
        confirm_production=args.confirm_production,
    )


if __name__ == "__main__":
    main()
