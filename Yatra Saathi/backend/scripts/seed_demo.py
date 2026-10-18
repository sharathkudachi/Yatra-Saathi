"""Seeds clearly-marked demo data into the working copy (section 14). Refuses
to target the original database. Idempotent: re-running against a working
copy that already has the demo rows leaves them as they are.

The values themselves live in data-model/seed/demo_seed.json.

Usage (from backend/):  python -m scripts.seed_demo
Reads APS_DB_PATH / APS_DB_ORIGINAL_PATH / APS_DB_ORIGINAL_SHA256 from the environment.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from src.core.clock import SystemClock
from src.core.config import Settings
from src.core.errors import Tech4ceError
from src.db.connection import connect
from src.db.unit_of_work import transaction
from src.db.working_copy_guard import assert_not_original

SEED_FILE = Path(__file__).resolve().parents[2] / "data-model" / "seed" / "demo_seed.json"
SEED = json.loads(SEED_FILE.read_text(encoding="utf-8"))

DEMO_USER_ID = SEED["user"]["user_id"]
DEMO_TRIP_ID = SEED["trip"]["trip_id"]
DEMO_BUDGET_ID = SEED["budget"]["budget_id"]
AHMEDABAD_CITY_NAME = SEED["trip"]["origin_city"]
JAIPUR_CITY_NAME = SEED["trip"]["destination_city"]

BUDGET_TOTAL = SEED["budget"]["total_amount"]
SESSION_SPEND_CAP = SEED["session_spend_cap"]  # Effective cap ends up at the budget total (section 14).


def _city_id(conn, name: str) -> str:
    row = conn.execute("SELECT city_id FROM cities WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise Tech4ceError(f"seed_demo: city not found: {name}")
    return row[0] if isinstance(row, (tuple, list)) else row["city_id"]


def seed(conn) -> dict:
    now = SystemClock().existing()
    existing = conn.execute("SELECT 1 FROM users WHERE user_id = ?", (DEMO_USER_ID,)).fetchone()
    if existing:
        with transaction(conn):
            conn.execute(
                """UPDATE users SET 
                     username = COALESCE(username, ?),
                     password_hash = COALESCE(password_hash, ?),
                     email_verified = 1
                   WHERE user_id = ?""",
                (DEMO_USER_ID, "$argon2id$v=19$m=65536,t=3,p=4$YYeqjFJESyftnO5vSIAeIw$ZC4FJtDLGldjICcaZ2lKHlhnjvDnHlRb0HYdtyTXy4Q", DEMO_USER_ID),
            )
        return {"status": "already seeded", "user_id": DEMO_USER_ID, "trip_id": DEMO_TRIP_ID,
                "budget_id": DEMO_BUDGET_ID}

    user, trip, budget = SEED["user"], SEED["trip"], SEED["budget"]
    home_city_id = _city_id(conn, user["home_city"])
    destination_city_id = _city_id(conn, JAIPUR_CITY_NAME)

    with transaction(conn):
        conn.execute(
            """INSERT INTO users (
                 user_id, display_name, email, home_city_id, home_currency, locale, budget_band,
                 travel_style, traveller_type, segment, date_of_signup, loyalty_tier, status,
                 created_at, updated_at, username, password_hash, email_verified
               ) VALUES (?, ?, ?, ?, ?, ?, 'value', 'leisure', 'couple', 'demo',
                         date(?), NULL, 'active', ?, ?, ?, ?, 1)""",
            (DEMO_USER_ID, user["display_name"], user["email"], home_city_id,
             user["home_currency"], user["locale"], now, now, now,
             DEMO_USER_ID, "$argon2id$v=19$m=65536,t=3,p=4$YYeqjFJESyftnO5vSIAeIw$ZC4FJtDLGldjICcaZ2lKHlhnjvDnHlRb0HYdtyTXy4Q"),
        )
        conn.execute(
            """INSERT INTO trips (
                 trip_id, owner_user_id, title, origin_city_id, destination_city_id, start_date,
                 end_date, party_size, adults, children, trip_type, is_group_trip, status,
                 home_currency, notes, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'leisure', 0,
                         'planning', ?, ?, ?, ?)""",
            (DEMO_TRIP_ID, DEMO_USER_ID, trip["title"], _city_id(conn, AHMEDABAD_CITY_NAME),
             destination_city_id, trip["start_date"], trip["end_date"],
             trip["adults"] + trip["children"], trip["adults"], trip["children"],
             user["home_currency"], "DEMO DATA: seed_demo", now, now),
        )
        total, split = float(BUDGET_TOTAL), budget["category_split"]
        conn.execute(
            """INSERT INTO budgets (
                 budget_id, trip_id, total_amount, currency, accommodation_cap, transport_cap,
                 food_cap, activities_cap, misc_cap, alert_threshold_pct, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 80, ?, ?)""",
            (DEMO_BUDGET_ID, DEMO_TRIP_ID, BUDGET_TOTAL, budget["currency"],
             *(f"{total * split[k]:.2f}" for k in ("accommodation", "transport", "food", "activities", "misc")),
             now, now),
        )
    return {"status": "seeded", "user_id": DEMO_USER_ID, "trip_id": DEMO_TRIP_ID,
            "budget_id": DEMO_BUDGET_ID, "budget_total": BUDGET_TOTAL,
            "session_spend_cap": SESSION_SPEND_CAP}


def main(argv: list[str] | None = None) -> int:
    try:
        settings = Settings.from_env()
        path = settings.require_db_path()
        assert_not_original(path, settings.original_db_path)
        conn = connect(settings)
        try:
            result = seed(conn)
        finally:
            conn.close()
    except Tech4ceError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
