"""Unit tests for PostgreSQL catalog seeder: column mapping, dependency order, safety guards, and transactional table protection."""
from datetime import datetime
from decimal import Decimal
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.seed_postgres_catalog import (
    CATALOG_TABLES,
    EXPLICIT_COLUMN_EXPRESSIONS,
    EXPECTED_NEON_PROJECT_ID,
    EXPECTED_ORIGINAL_SHA256,
    PROTECTED_TRANSACTIONAL_TABLES,
    get_pg_table_columns,
    main,
    normalize_and_compare,
    parse_args,
    preflight_conflict_check,
    resolve_table_columns,
    seed_catalog,
    snapshot_protected_table_counts,
    snapshot_user_records,
    verify_neon_target_identity,
    verify_sqlite_source_hash,
)
from src.core.errors import SafetyError


class TestPostgresCatalogSeeder(unittest.TestCase):
    def test_catalog_tables_topological_dependency_order(self):
        """Parents must precede children to satisfy foreign-key constraints."""
        indices = {table: i for i, table in enumerate(CATALOG_TABLES)}

        # cities depends on countries
        self.assertLess(indices["countries"], indices["cities"])
        # airports and hotels depend on cities
        self.assertLess(indices["cities"], indices["airports"])
        self.assertLess(indices["cities"], indices["hotels"])
        # airlines depends on countries
        self.assertLess(indices["countries"], indices["airlines"])
        # hotel_room_types depends on hotels
        self.assertLess(indices["hotels"], indices["hotel_room_types"])
        # flights depends on airlines and airports
        self.assertLess(indices["airlines"], indices["flights"])
        self.assertLess(indices["airports"], indices["flights"])
        # flight_fares depends on flights
        self.assertLess(indices["flights"], indices["flight_fares"])
        # inventory_calendar depends on flight_fares and hotel_room_types
        self.assertLess(indices["flight_fares"], indices["inventory_calendar"])
        self.assertLess(indices["hotel_room_types"], indices["inventory_calendar"])

    def test_protected_transactional_tables_excluded_and_guarded(self):
        """Transactional tables must never appear in CATALOG_TABLES and must raise SafetyError."""
        intersection = set(CATALOG_TABLES) & PROTECTED_TRANSACTIONAL_TABLES
        self.assertEqual(intersection, set(), f"Catalog tables must not include transactional tables: {intersection}")

        for table in ["users", "bookings", "payments", "trips", "sessions", "confirmations"]:
            with self.subTest(table=table):
                self.assertIn(table, PROTECTED_TRANSACTIONAL_TABLES)
                mock_src = MagicMock(spec=sqlite3.Connection)
                mock_pg = MagicMock()
                with self.assertRaisesRegex(SafetyError, "protected and must never be catalog-seeded"):
                    resolve_table_columns(mock_src, mock_pg, table)

    def test_currencies_explicit_column_mapping(self):
        """Currencies correctly maps minor_unit_exponent to exponent."""
        mock_src = sqlite3.connect(":memory:")
        mock_src.execute(
            "CREATE TABLE currencies (currency_id TEXT, iso4217 TEXT, name TEXT, symbol TEXT, minor_unit_exponent INTEGER, display_locale TEXT, updated_at TEXT)"
        )
        mock_pg = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("iso4217",), ("name",), ("symbol",), ("exponent",)]
        mock_pg.cursor.return_value = mock_cursor

        target_cols, select_exprs = resolve_table_columns(mock_src, mock_pg, "currencies")
        self.assertEqual(target_cols, ["iso4217", "name", "symbol", "exponent"])
        self.assertEqual(select_exprs, ["iso4217", "name", "symbol", "minor_unit_exponent"])
        mock_src.close()

    def test_table_column_intersection_filters_missing_pg_columns(self):
        """Columns present in SQLite but absent in PostgreSQL are omitted from both select and insert."""
        mock_src = sqlite3.connect(":memory:")
        mock_src.execute(
            "CREATE TABLE countries (country_id TEXT, iso2 TEXT, iso3 TEXT, name TEXT, default_currency TEXT, calling_code TEXT, region TEXT, updated_at TEXT)"
        )
        mock_pg = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("country_id",), ("name",), ("iso2",), ("iso3",)]
        mock_pg.cursor.return_value = mock_cursor

        target_cols, select_exprs = resolve_table_columns(mock_src, mock_pg, "countries")
        self.assertEqual(set(target_cols), {"country_id", "name", "iso2", "iso3"})
        self.assertEqual(target_cols, select_exprs)
        self.assertNotIn("default_currency", target_cols)
        self.assertNotIn("calling_code", target_cols)
        mock_src.close()

    def test_source_hash_verification(self):
        """Verifies APS-01 SHA256 integrity check raises SafetyError on mismatch."""
        with tempfile.TemporaryDirectory() as tmp:
            test_db = Path(tmp) / "APS-01.db"
            test_db.write_text("corrupted content", encoding="utf-8")
            with self.assertRaises(SafetyError):
                verify_sqlite_source_hash(str(test_db), EXPECTED_ORIGINAL_SHA256)

    def test_target_identity_verification_refuses_foreign_project(self):
        """Rejects database connections whose neon.project_id does not match the authorized project."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = ("wrong-project-12345", "br-curly-bar-azc5gozu", "ep-123", "neondb")
        mock_conn.cursor.return_value = mock_cur

        with self.assertRaisesRegex(SafetyError, "Neon Project ID mismatch"):
            verify_neon_target_identity(mock_conn, expected_branch_name="production")

    def test_target_identity_verification_fails_closed_when_neon_settings_missing(self):
        """Fails closed if neon.project_id or neon.branch_id is missing or empty."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        # Empty project ID
        mock_cur.fetchone.return_value = (None, "br-curly-bar-azc5gozu", "ep-123", "neondb")
        mock_conn.cursor.return_value = mock_cur

        with self.assertRaisesRegex(SafetyError, "Neon identity verification failed closed: 'neon.project_id' is missing or empty"):
            verify_neon_target_identity(mock_conn)

        # Empty branch ID
        mock_cur.fetchone.return_value = (EXPECTED_NEON_PROJECT_ID, "", "ep-123", "neondb")
        with self.assertRaisesRegex(SafetyError, "Neon identity verification failed closed: 'neon.branch_id' is missing or empty"):
            verify_neon_target_identity(mock_conn)

    def test_target_identity_verification_refuses_unconfirmed_production(self):
        """Rejects production branch without explicit confirm_production flag."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (EXPECTED_NEON_PROJECT_ID, "br-curly-bar-azc5gozu", "ep-prod", "neondb")
        mock_conn.cursor.return_value = mock_cur

        with self.assertRaisesRegex(SafetyError, "REFUSAL: Target connection resolves to the 'production' branch"):
            verify_neon_target_identity(mock_conn, expected_branch_name="production", confirm_production=False)

    def test_target_identity_verification_refuses_production_branch_id_even_without_cli_arg(self):
        """Even if --target-branch is omitted, connecting to production branch ID must refuse without --confirm-production."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (EXPECTED_NEON_PROJECT_ID, "br-curly-bar-azc5gozu", "ep-prod", "neondb")
        mock_conn.cursor.return_value = mock_cur

        with self.assertRaisesRegex(SafetyError, "REFUSAL: Target connection resolves to the 'production' branch"):
            verify_neon_target_identity(mock_conn, expected_branch_name=None, confirm_production=False)

    def test_target_identity_verification_accepts_confirmed_production(self):
        """Allows confirmed production target matching expected project and branch ID."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (EXPECTED_NEON_PROJECT_ID, "br-curly-bar-azc5gozu", "ep-prod", "neondb")
        mock_conn.cursor.return_value = mock_cur

        info = verify_neon_target_identity(mock_conn, expected_branch_name="production", confirm_production=True)
        self.assertEqual(info["project_id"], EXPECTED_NEON_PROJECT_ID)
        self.assertEqual(info["branch_id"], "br-curly-bar-azc5gozu")

    def test_normalize_and_compare_handles_all_data_types(self):
        """Validates comparison across NULLs, floats, Decimals, integers, booleans, timestamps, and Unicode."""
        # 1. NULLs
        self.assertTrue(normalize_and_compare(None, None, "test"))
        self.assertFalse(normalize_and_compare(None, "val", "test"))
        self.assertFalse(normalize_and_compare("val", None, "test"))

        # 2. Floats, Decimals, GPS coordinates
        self.assertTrue(normalize_and_compare(7.290572, 7.290572, "lat"))
        self.assertTrue(normalize_and_compare(Decimal("150.50"), 150.50, "price"))
        self.assertTrue(normalize_and_compare(Decimal("150.00"), 150, "price"))
        self.assertTrue(normalize_and_compare(80.633728001, 80.633728000, "lng"))

        # 3. Booleans
        self.assertTrue(normalize_and_compare(True, True, "is_active"))
        self.assertFalse(normalize_and_compare(True, False, "is_active"))

        # 4. Discrete Integers: Zero tolerance exact equality
        self.assertTrue(normalize_and_compare(2, 2, "exponent"))
        self.assertFalse(normalize_and_compare(2, 3, "exponent"))
        self.assertTrue(normalize_and_compare(0, 0, "rtl"))
        self.assertFalse(normalize_and_compare(0, 1, "rtl"))
        self.assertTrue(normalize_and_compare(125000, 125000, "population"))
        self.assertFalse(normalize_and_compare(125000, 125001, "population"))

        # 5. Currency / Monetary: Must match to exact cent/paisa (within 0.005)
        self.assertTrue(normalize_and_compare(Decimal("8180.17"), 8180.17, "base_fare"))
        self.assertTrue(normalize_and_compare(8180.170, 8180.170, "base_price"))
        self.assertFalse(normalize_and_compare(8180.17, 8180.18, "base_fare"))  # 1 cent difference rejected!

        # 6. Geographic coordinates: ~1.11 meter tolerance (1e-5 deg) for IEEE 754 binary float diffs
        self.assertTrue(normalize_and_compare(7.290572, 7.290572005, "lat"))  # within ~1 meter
        self.assertFalse(normalize_and_compare(7.290572, 7.290700, "lat"))  # ~14 meters diff rejected!

        # 7. Unicode and strings
        self.assertTrue(normalize_and_compare("  Sinhala  ", "Sinhala", "english_name"))
        # Sinhala native_name NFC normalization
        self.assertTrue(normalize_and_compare("සිංහල", "සිංහල", "native_name"))
        # Currency symbols
        self.assertTrue(normalize_and_compare("₹", "₹", "symbol"))
        self.assertTrue(normalize_and_compare("د.إ", "د.إ", "symbol"))

    def test_preflight_conflict_check_detects_alien_keys(self):
        """Detects if PostgreSQL table contains alien/incompatible primary keys before seeding."""
        mock_src = sqlite3.connect(":memory:")
        mock_src.execute("CREATE TABLE countries (country_id TEXT PRIMARY KEY, name TEXT)")
        mock_src.execute("INSERT INTO countries VALUES ('cnt_valid_1', 'Country One')")

        mock_pg = MagicMock()
        mock_cur = MagicMock()
        # First fetchall is for get_pg_table_columns (columns), second is for existing table rows
        mock_cur.fetchall.side_effect = [
            [("country_id",), ("name",)],
            [("cnt_alien_999", "Alien Country")],
        ]
        mock_pg.cursor.return_value = mock_cur

        with self.assertRaisesRegex(SafetyError, "Preflight Conflict: public.countries contains alien record with primary key 'cnt_alien_999'"):
            preflight_conflict_check(mock_src, mock_pg, ["countries"])
        mock_src.close()

    def test_preflight_conflict_check_detects_field_mismatches(self):
        """Detects if existing PostgreSQL record has a different column value than canonical SQLite."""
        mock_src = sqlite3.connect(":memory:")
        mock_src.execute("CREATE TABLE countries (country_id TEXT PRIMARY KEY, name TEXT)")
        mock_src.execute("INSERT INTO countries VALUES ('cnt_lk', 'Sri Lanka')")

        mock_pg = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.side_effect = [
            [("country_id",), ("name",)],
            [("cnt_lk", "Wrong Country Name")],  # Conflict in 'name'
        ]
        mock_pg.cursor.return_value = mock_cur

        with self.assertRaisesRegex(SafetyError, "Preflight Conflict Mismatch in public.countries for PK 'cnt_lk': column 'name' has value 'Wrong Country Name' in PostgreSQL, but canonical source has 'Sri Lanka'"):
            preflight_conflict_check(mock_src, mock_pg, ["countries"])
        mock_src.close()

    def test_preflight_conflict_check_passes_with_matching_keys_and_values(self):
        """Passes when all existing PostgreSQL keys and values match canonical SQLite."""
        mock_src = sqlite3.connect(":memory:")
        mock_src.execute("CREATE TABLE countries (country_id TEXT PRIMARY KEY, name TEXT)")
        mock_src.execute("INSERT INTO countries VALUES ('cnt_lk', 'Sri Lanka')")

        mock_pg = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.side_effect = [
            [("country_id",), ("name",)],
            [("cnt_lk", "Sri Lanka")],
        ]
        mock_pg.cursor.return_value = mock_cur

        # Should complete without error
        preflight_conflict_check(mock_src, mock_pg, ["countries"])
        mock_src.close()

    def test_cli_dry_run_flag_parsed(self):
        args = parse_args(["--dry-run", "--target-branch", "val-reg-repair", "--batch-size", "500"])
        self.assertTrue(args.dry_run)
        self.assertEqual(args.target_branch, "val-reg-repair")
        self.assertEqual(args.batch_size, 500)


if __name__ == "__main__":
    unittest.main()

