"""Unit tests for PostgreSQL adapter, parameter conversion, row behavior, and Neon URL normalization."""
import unittest
from unittest.mock import MagicMock

from src.core.config import Settings
from src.db.postgres import PostgresConnectionWrapper, PostgresCursorWrapper, PostgresRow, adapt_sql, normalize_neon_url


class TestPostgresAdapter(unittest.TestCase):
    def test_adapt_sql_basic(self):
        sql = "SELECT * FROM users WHERE user_id = ? AND status = ?"
        expected = "SELECT * FROM users WHERE user_id = %s AND status = %s"
        self.assertEqual(adapt_sql(sql), expected)

    def test_adapt_sql_preserves_literals(self):
        sql = "SELECT * FROM cities WHERE name = 'Why?' AND country_id = ?"
        expected = "SELECT * FROM cities WHERE name = 'Why?' AND country_id = %s"
        self.assertEqual(adapt_sql(sql), expected)

    def test_adapt_sql_escaped_quotes(self):
        sql = "SELECT * FROM hotels WHERE name = 'O''Reilly?' AND city_id = ?"
        expected = "SELECT * FROM hotels WHERE name = 'O''Reilly?' AND city_id = %s"
        self.assertEqual(adapt_sql(sql), expected)

    def test_postgres_row_dict_and_index_access(self):
        cols = ["user_id", "display_name", "email", "status"]
        vals = ["usr_1234", "Sharath Kudachi", "sharath@example.com", "active"]
        row = PostgresRow(vals, cols)

        # Dict access
        self.assertEqual(row["user_id"], "usr_1234")
        self.assertEqual(row["display_name"], "Sharath Kudachi")
        self.assertEqual(row.get("email"), "sharath@example.com")
        self.assertEqual(row.get("nonexistent", "default"), "default")

        # Tuple / index access
        self.assertEqual(row[0], "usr_1234")
        self.assertEqual(row[1], "Sharath Kudachi")
        self.assertEqual(row[2], "sharath@example.com")
        self.assertEqual(row[3], "active")

        # Dict conversion & keys
        d = dict(row)
        self.assertEqual(d["user_id"], "usr_1234")
        self.assertIn("user_id", row.keys())
        self.assertEqual(len(row), 4)

    def test_normalize_neon_url_adds_sslmode(self):
        url = "postgresql://testuser:testpass@ep-demo-123.us-east-2.aws.neon.tech/neondb"
        norm = normalize_neon_url(url)
        self.assertIn("sslmode=require", norm)

    def test_normalize_neon_url_converts_postgres_prefix(self):
        url = "postgres://testuser:testpass@ep-demo-123.us-east-2.aws.neon.tech/neondb"
        norm = normalize_neon_url(url)
        self.assertTrue(norm.startswith("postgresql://"))
        self.assertIn("sslmode=require", norm)

    def test_settings_detects_postgres(self):
        s_pg = Settings.from_env({
            "DATABASE_URL": "postgresql://testuser:testpass@ep-sample.neon.tech/neondb",
            "BOOKING_MODE": "mock",
        })
        self.assertTrue(s_pg.is_postgres)
        self.assertEqual(s_pg.require_db_path(), "postgresql://testuser:testpass@ep-sample.neon.tech/neondb")

        s_sqlite = Settings.from_env({
            "APS_DB_PATH": "var/aps01_working.db",
            "APS_DB_ORIGINAL_PATH": "data/original/APS-01.db",
            "APS_DB_ORIGINAL_SHA256": "ecc58821ccb7f7d19a23bac157e95ba84521238b40ba52ad568d7932675cae0a",
            "BOOKING_MODE": "mock",
        })
        self.assertFalse(s_sqlite.is_postgres)
        self.assertEqual(s_sqlite.require_db_path(), "var/aps01_working.db")

    def test_postgres_cursor_wrapper(self):
        mock_raw_cursor = MagicMock()
        mock_raw_cursor.description = [("id",), ("val",)]
        mock_raw_cursor.fetchone.return_value = ("1", "test")
        mock_raw_cursor.fetchall.return_value = [("1", "test"), ("2", "demo")]

        wrapper = PostgresCursorWrapper(mock_raw_cursor)
        row = wrapper.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["id"], "1")
        self.assertEqual(row[0], "1")

        rows = wrapper.fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["val"], "demo")


if __name__ == "__main__":
    unittest.main()
