"""Unit tests for PostgreSQL recovery and data preservation tooling."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from scripts.recover_postgres_data import (
    REVERSE_CATALOG_TABLES,
    TRANSACTIONAL_TABLES,
    export_transactional_data,
    safe_reverse_delete_catalog,
)
from scripts.seed_postgres_catalog import CATALOG_TABLES, PROTECTED_TRANSACTIONAL_TABLES


class TestPostgresRecovery(unittest.TestCase):
    def test_reverse_catalog_tables_is_exact_reverse_topological_order(self):
        """Must match exact reverse order of CATALOG_TABLES to respect foreign-key constraints."""
        expected = list(reversed(CATALOG_TABLES))
        self.assertEqual(REVERSE_CATALOG_TABLES, expected)

    def test_transactional_tables_coverage(self):
        """Ensures all critical user-owned tables are included in export list."""
        for required in ["users", "trips", "bookings", "payments", "sessions"]:
            with self.subTest(table=required):
                self.assertIn(required, TRANSACTIONAL_TABLES)

    def test_export_transactional_data_captures_user_rows_to_json(self):
        """Verifies export captures table records into structured JSON."""
        mock_raw = MagicMock()
        mock_cur = MagicMock()

        # Mock information_schema tables
        mock_cur.fetchall.side_effect = [
            [("users",)],  # table_schema = 'public' returns 'users'
            [("usr_1", "demo@yatra.in", "Demo User", None)],  # SELECT * FROM public.users
        ]
        mock_cur.description = [("user_id", None), ("email", None), ("display_name", None), ("home_city_id", None)]
        mock_raw.cursor.return_value = mock_cur

        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "backup_users.json"
            counts = export_transactional_data(mock_raw, str(out_file))

            self.assertEqual(counts.get("users"), 1)
            self.assertTrue(out_file.exists())
            data = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(len(data["users"]), 1)
            self.assertEqual(data["users"][0]["email"], "demo@yatra.in")

    def test_safe_reverse_delete_excludes_referenced_cities(self):
        """Verifies candidate count query for cities contains exclusion of user-referenced cities."""
        mock_raw = MagicMock()
        mock_cur = MagicMock()

        executed_queries = []
        def record_execute(sql, *args):
            executed_queries.append(sql)

        mock_cur.execute.side_effect = record_execute
        mock_cur.fetchall.return_value = [("cities",)]
        mock_cur.fetchone.return_value = (59,)  # 59 unreferenced cities
        mock_raw.cursor.return_value = mock_cur

        counts = safe_reverse_delete_catalog(mock_raw, dry_run=True)
        self.assertEqual(counts.get("cities"), 59)
        mock_raw.rollback.assert_called_once()  # dry_run rolls back

        # Ensure query strictly excludes users.home_city_id
        city_query = [q for q in executed_queries if "public.cities" in q][0]
        self.assertIn("home_city_id FROM public.users", city_query)
        self.assertNotIn("CASCADE", city_query)


if __name__ == "__main__":
    unittest.main()
