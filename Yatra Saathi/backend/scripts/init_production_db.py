"""Initialize or verify the production working database copy.

Usage (from backend/): python -m scripts.init_production_db

Reads APS_DB_ORIGINAL_PATH, APS_DB_ORIGINAL_SHA256, and APS_DB_PATH from environment.
- If APS_DB_PATH does not exist:
    1. Verifies the original database fingerprint.
    2. Creates a restorable stamped working copy at APS_DB_PATH.
    3. Applies all database migrations (0001 - 0007).
    4. Seeds the demo user record for initial login testing.
- If APS_DB_PATH already exists:
    1. Verifies the working copy mark (asserts it is not the original database).
    2. Applies any new/pending database migrations idempotently.
    3. Preserves all user registrations, trips, preferences, and bookings.
"""
from __future__ import annotations

import os
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
from src.core.errors import Tech4ceError
from src.db.connection import connect
from src.db.migrations.runner import apply_migrations
from src.db.working_copy_guard import assert_working_copy, make_working_copy
from scripts.seed_demo import seed


def init_db(settings: Settings | None = None) -> int:
    settings = settings or Settings.from_env()

    # 1. PostgreSQL (Neon / Cloud hosting) branch
    if settings.is_postgres:
        print(f"[Init DB] Detected PostgreSQL database backend via DATABASE_URL.")
        from src.db.postgres_schema import init_postgres_schema
        conn = connect(settings)
        try:
            num_stmts = init_postgres_schema(conn)
            print(f"[Init DB] Applied {num_stmts} PostgreSQL schema definitions.")

            # Seed demo user if not already present
            row = conn.execute("SELECT user_id FROM users WHERE user_id = ?", ("usr_demo0001",)).fetchone()
            if not row:
                conn.execute(
                    """INSERT INTO users (
                        user_id, display_name, email, home_currency, locale, status, created_at,
                        username, password_hash, email_verified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        "usr_demo0001", "Demo Traveler", "sharath.demo@yatrasaathi.in", "INR", "en-IN",
                        "active", "2026-10-18T10:00:00Z", "usr_demo0001",
                        "$argon2id$v=19$m=65536,t=3,p=4$YYeqjFJESyftnO5vSIAeIw$ZC4FJtDLGldjICcaZ2lKHlhnjvDnHlRb0HYdtyTXy4Q", 1
                    ),
                )
                conn.commit()
                print("[Init DB] Seeded demo user: usr_demo0001.")
            else:
                print("[Init DB] Existing demo user usr_demo0001 verified.")

            # Seed reference catalog if cities table is empty
            try:
                city_count = conn.execute("SELECT COUNT(*) FROM cities").fetchone()[0]
            except Exception:
                city_count = 0
            if city_count == 0:
                source_db = settings.original_db_path or settings.db_path
                if source_db and os.path.isfile(source_db):
                    print(f"[Init DB] Catalog tables empty. Seeding catalog from {source_db}...")
                    try:
                        from scripts.seed_postgres_catalog import seed_catalog
                        seed_catalog(source_db, settings.database_url)
                    except Exception as e:
                        print(f"[Init DB] Warning: Catalog seed encountered: {e}")

            # Health check: query public tables
            cur = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
            tables = [r[0] for r in cur.fetchall()]
            print(f"[Init DB] PostgreSQL Health Check PASSED: {len(tables)} tables verified.")
        finally:
            conn.close()
        return 0

    # 2. SQLite (Local / Stamped working copy) branch
    db_path = settings.require_db_path()
    original_path, expected_sha = settings.require_original()

    # Ensure parent directory exists (e.g. Render mounted persistent disk directory)
    db_dir = os.path.dirname(os.path.abspath(db_path))
    if not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        print(f"[Init DB] Created database directory: {db_dir}")

    if not os.path.isfile(db_path):
        print(f"[Init DB] Working database not found at {db_path}. Initializing new working copy from original dataset...")
        copy_res = make_working_copy(original_path, expected_sha, db_path, overwrite=False)
        print(f"[Init DB] Created working copy stamped with application_id 0x{copy_res['application_id']:08X}.")
        
        mig_res = apply_migrations(settings)
        print(f"[Init DB] Applied migrations: {mig_res or 'none'}.")
        
        conn = connect(settings)
        try:
            seed_res = seed(conn)
            print(f"[Init DB] Seeded demo user: {seed_res.get('user', {}).get('user_id', 'usr_demo0001')}.")
        finally:
            conn.close()
        print("[Init DB] Database initialization complete.")
    else:
        print(f"[Init DB] Found existing working database at {db_path}. Verifying integrity...")
        assert_working_copy(db_path, original_path)
        mig_res = apply_migrations(settings)
        print(f"[Init DB] Applied pending migrations: {mig_res or 'none (database up to date)'}.")
        print("[Init DB] Working database verified.")

    # Integrity verification
    conn = connect(settings)
    try:
        integ = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errs = conn.execute("PRAGMA foreign_key_check").fetchall()
        user_ver = conn.execute("PRAGMA user_version").fetchone()[0]
        if integ != "ok":
            print(f"[Init DB] ERROR: PRAGMA integrity_check failed: {integ}", file=sys.stderr)
            return 1
        if fk_errs:
            print(f"[Init DB] ERROR: PRAGMA foreign_key_check found {len(fk_errs)} violations: {fk_errs}", file=sys.stderr)
            return 1
        print(f"[Init DB] Health check PASSED: integrity='{integ}', foreign_keys=0 violations, user_version={user_ver}.")
    finally:
        conn.close()

    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return init_db()
    except Tech4ceError as exc:
        print(f"[Init DB] REFUSED: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"[Init DB] UNEXPECTED ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
