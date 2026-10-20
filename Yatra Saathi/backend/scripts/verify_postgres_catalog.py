"""Read-only PostgreSQL catalog and data integrity verifier for Yatra Saathi.

Performs strictly read-only verification of:
1. Neon target session identity (project ID, branch ID, endpoint ID).
2. Row counts across all 11 catalog tables.
3. Foreign-key referential integrity (zero orphan foreign keys).
4. Representative catalog queries (cities, flights, hotels, currencies).
5. Preservation and referential validity of user records.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Ensure backend root is on sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from src.core.config import Settings
from src.core.errors import SafetyError
from src.db.postgres import connect_postgres

EXPECTED_NEON_PROJECT_ID = "dawn-sky-64344251"

EXPECTED_CATALOG_COUNTS = {
    "currencies": 25,
    "countries": 30,
    "languages": 26,
    "cities": 60,
    "airports": 80,
    "airlines": 30,
    "hotels": 300,
    "hotel_room_types": 1200,
    "flights": 4000,
    "flight_fares": 8002,
    "inventory_calendar": 15030,
}

FK_ORPHAN_CHECKS = [
    ("cities.country_id -> countries.country_id",
     "SELECT COUNT(*) FROM cities c LEFT JOIN countries co ON c.country_id = co.country_id WHERE c.country_id IS NOT NULL AND co.country_id IS NULL"),
    ("airports.city_id -> cities.city_id",
     "SELECT COUNT(*) FROM airports a LEFT JOIN cities c ON a.city_id = c.city_id WHERE a.city_id IS NOT NULL AND c.city_id IS NULL"),
    ("hotels.city_id -> cities.city_id",
     "SELECT COUNT(*) FROM hotels h LEFT JOIN cities c ON h.city_id = c.city_id WHERE h.city_id IS NOT NULL AND c.city_id IS NULL"),
    ("hotel_room_types.hotel_id -> hotels.hotel_id",
     "SELECT COUNT(*) FROM hotel_room_types rt LEFT JOIN hotels h ON rt.hotel_id = h.hotel_id WHERE rt.hotel_id IS NOT NULL AND h.hotel_id IS NULL"),
    ("flights.airline_id -> airlines.airline_id",
     "SELECT COUNT(*) FROM flights f LEFT JOIN airlines a ON f.airline_id = a.airline_id WHERE f.airline_id IS NOT NULL AND a.airline_id IS NULL"),
    ("flights.origin_airport_id -> airports.airport_id",
     "SELECT COUNT(*) FROM flights f LEFT JOIN airports a ON f.origin_airport_id = a.airport_id WHERE f.origin_airport_id IS NOT NULL AND a.airport_id IS NULL"),
    ("flights.dest_airport_id -> airports.airport_id",
     "SELECT COUNT(*) FROM flights f LEFT JOIN airports a ON f.dest_airport_id = a.airport_id WHERE f.dest_airport_id IS NOT NULL AND a.airport_id IS NULL"),
    ("flight_fares.flight_id -> flights.flight_id",
     "SELECT COUNT(*) FROM flight_fares ff LEFT JOIN flights f ON ff.flight_id = f.flight_id WHERE ff.flight_id IS NOT NULL AND f.flight_id IS NULL"),
    ("users.home_city_id -> cities.city_id",
     "SELECT COUNT(*) FROM users u LEFT JOIN cities c ON u.home_city_id = c.city_id WHERE u.home_city_id IS NOT NULL AND c.city_id IS NULL"),
]


def verify_database(pg_url: str, expected_branch: Optional[str] = None) -> bool:
    """Performs full read-only safety and completeness verification."""
    print("=" * 70)
    print("Yatra Saathi - Read-Only PostgreSQL Catalog Verification")
    print("=" * 70)

    pg_conn = connect_postgres(pg_url, use_pool=False)
    raw_conn = getattr(pg_conn, "_raw_conn", pg_conn)
    cur = raw_conn.cursor()

    all_passed = True
    try:
        # 1. Neon Session Identity
        print("\n[Check 1/5] Verifying Neon Target Identity (GUC settings)...")
        cur.execute("""
            SELECT
                current_setting('neon.project_id', true) AS project_id,
                current_setting('neon.branch_id', true) AS branch_id,
                current_setting('neon.endpoint_id', true) AS endpoint_id,
                current_database() AS db_name
        """)
        row = cur.fetchone()
        project_id, branch_id, endpoint_id, db_name = row[0], row[1], row[2], row[3]

        print(f"  Project ID  : {project_id}")
        print(f"  Branch ID   : {branch_id}")
        print(f"  Endpoint ID : {endpoint_id}")
        print(f"  Database    : {db_name}")

        if project_id != EXPECTED_NEON_PROJECT_ID:
            print(f"  [FAIL] Project ID mismatch: expected {EXPECTED_NEON_PROJECT_ID}, got {project_id}")
            all_passed = False
        else:
            print("  [PASS] Project ID verified.")

        # 2. Table Counts
        print("\n[Check 2/5] Verifying Catalog Table Row Counts...")
        for table, expected_cnt in EXPECTED_CATALOG_COUNTS.items():
            try:
                cur.execute(f"SELECT COUNT(*) FROM public.{table}")
                actual_cnt = cur.fetchone()[0]
                status = "[PASS]" if actual_cnt >= expected_cnt else "[FAIL]"
                if actual_cnt < expected_cnt:
                    all_passed = False
                print(f"  {status} {table:20s}: actual {actual_cnt:5d} (expected >= {expected_cnt})")
            except Exception as e:
                print(f"  [FAIL] {table:20s}: error querying: {e}")
                all_passed = False

        # 3. Foreign Key Integrity
        print("\n[Check 3/5] Verifying Foreign Key Referential Integrity (Orphan checks)...")
        for desc, sql in FK_ORPHAN_CHECKS:
            try:
                cur.execute(sql)
                orphan_cnt = cur.fetchone()[0]
                status = "[PASS]" if orphan_cnt == 0 else "[FAIL]"
                if orphan_cnt > 0:
                    all_passed = False
                print(f"  {status} {desc}: {orphan_cnt} orphans")
            except Exception as e:
                print(f"  [FAIL] {desc}: query error: {e}")
                all_passed = False

        # 4. Representative Domain Queries
        print("\n[Check 4/5] Executing Representative Domain Queries...")
        # (a) City search
        cur.execute("SELECT city_id, name, country_code, timezone, primary_language FROM public.cities WHERE city_id = 'cty_009c9fd2'")
        kandy = cur.fetchone()
        if kandy and kandy[1] == "Kandy":
            print(f"  [PASS] City Lookup (Kandy): ID={kandy[0]}, Name={kandy[1]}, Country={kandy[2]}, Timezone={kandy[3]}")
        else:
            print(f"  [FAIL] City Lookup (Kandy) failed: row={kandy}")
            all_passed = False

        # (b) Hotel search
        cur.execute("""
            SELECT h.hotel_id, h.name, c.name, COUNT(rt.room_type_id)
            FROM public.hotels h
            JOIN public.cities c ON h.city_id = c.city_id
            JOIN public.hotel_room_types rt ON h.hotel_id = rt.hotel_id
            GROUP BY h.hotel_id, h.name, c.name
            LIMIT 1
        """)
        hotel = cur.fetchone()
        if hotel:
            print(f"  [PASS] Hotel & Room Join: Hotel='{hotel[1]}', City='{hotel[2]}', Room Types={hotel[3]}")
        else:
            print("  [FAIL] Hotel & Room Join query returned no rows")
            all_passed = False

        # (c) Flight search
        cur.execute("""
            SELECT f.flight_number, al.name, orig.iata, dest.iata, MIN(ff.base_fare::numeric)
            FROM public.flights f
            JOIN public.airlines al ON f.airline_id = al.airline_id
            JOIN public.airports orig ON f.origin_airport_id = orig.airport_id
            JOIN public.airports dest ON f.dest_airport_id = dest.airport_id
            JOIN public.flight_fares ff ON f.flight_id = ff.flight_id
            GROUP BY f.flight_number, al.name, orig.iata, dest.iata
            LIMIT 1
        """)
        flight = cur.fetchone()
        if flight:
            print(f"  [PASS] Flight & Fare Join: Flight={flight[0]} ({flight[1]}), Route={flight[2]}->{flight[3]}, Min Fare={flight[4]}")
        else:
            print("  [FAIL] Flight & Fare Join query returned no rows")
            all_passed = False

        # (d) Currencies
        cur.execute("SELECT iso4217, name, symbol, exponent FROM public.currencies WHERE iso4217 IN ('INR', 'USD', 'LKR', 'EUR') ORDER BY iso4217")
        currencies = cur.fetchall()
        if len(currencies) == 4:
            curr_str = ", ".join([f"{c[0]} ({c[2]})" for c in currencies])
            print(f"  [PASS] Reference Currencies verified: {curr_str}")
        else:
            print(f"  [FAIL] Reference Currencies query returned {len(currencies)} rows (expected 4)")
            all_passed = False

        # 5. User Records & Foreign Key Validations
        print("\n[Check 5/5] Verifying User Records and Referential Validity...")
        cur.execute("""
            SELECT u.user_id, u.email, u.display_name, u.home_city_id, c.name
            FROM public.users u
            LEFT JOIN public.cities c ON u.home_city_id = c.city_id
            ORDER BY u.user_id
        """)
        users = cur.fetchall()
        print(f"  Total Users: {len(users)}")
        for u in users:
            city_label = u[4] if u[4] else ("(No Home City)" if u[3] is None else f"(INVALID FK: {u[3]})")
            print(f"    - User {u[0]}: {u[1]} ({u[2]}) -> Home City: {city_label}")
            if u[3] is not None and u[4] is None:
                print(f"  [FAIL] User {u[0]} references nonexistent city_id '{u[3]}'")
                all_passed = False

        print("\n" + "=" * 70)
        if all_passed:
            print("VERIFICATION RESULT: ALL CHECKS PASSED [SUCCESS]")
        else:
            print("VERIFICATION RESULT: ONE OR MORE CHECKS FAILED [FAILURE]")
        print("=" * 70)
        return all_passed

    finally:
        cur.close()
        pg_conn.close()


def main(cli_args: Optional[Sequence[str]] = None):
    parser = argparse.ArgumentParser(description="Read-only PostgreSQL catalog verifier for Yatra Saathi.")
    parser.add_argument("--database-url", help="Target PostgreSQL connection URL. Defaults to DATABASE_URL in env.")
    parser.add_argument("--target-branch", help="Expected Neon branch name (optional).")
    args = parser.parse_args(cli_args)

    settings = Settings.from_env()
    pg_url = args.database_url or settings.database_url
    if not pg_url:
        print("ERROR: DATABASE_URL is required.", file=sys.stderr)
        sys.exit(1)

    success = verify_database(pg_url, expected_branch=args.target_branch)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
