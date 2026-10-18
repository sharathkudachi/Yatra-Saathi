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

    def test_postgres_cursor_wrapper_iteration(self):
        """PostgresCursorWrapper is iterable, yielding PostgresRow instances."""
        mock_raw_cursor = MagicMock()
        mock_raw_cursor.description = [("iso4217",), ("name",), ("symbol",)]
        # Simulate fetchone yielding two rows then None
        mock_raw_cursor.fetchone.side_effect = [
            ("INR", "Indian Rupee", "₹"),
            ("USD", "US Dollar", "$"),
            None
        ]

        wrapper = PostgresCursorWrapper(mock_raw_cursor)
        rows = [r for r in wrapper]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["iso4217"], "INR")
        self.assertEqual(rows[0]["name"], "Indian Rupee")
        self.assertEqual(dict(rows[0]), {"iso4217": "INR", "name": "Indian Rupee", "symbol": "₹"})
        self.assertEqual(rows[1]["iso4217"], "USD")

    def test_postgres_cursor_wrapper_fetchmany(self):
        """PostgresCursorWrapper supports fetchmany."""
        mock_raw_cursor = MagicMock()
        mock_raw_cursor.description = [("id",)]
        mock_raw_cursor.fetchmany.return_value = [("a",), ("b",)]

        wrapper = PostgresCursorWrapper(mock_raw_cursor)
        rows = wrapper.fetchmany(2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["id"], "a")
        self.assertEqual(rows[1]["id"], "b")

    def test_currencies_endpoint_with_postgres_cursor(self):
        """GET /api/v1/currencies functions correctly when connected to PostgreSQL."""
        from fastapi.testclient import TestClient
        from src.main import create_app
        from src.api.deps import get_conn

        mock_conn = MagicMock()
        # Mock cursor returning currency rows
        mock_cursor = PostgresCursorWrapper(MagicMock())
        mock_cursor._cols = ["iso4217", "name", "symbol"]
        mock_cursor.fetchall = MagicMock(return_value=[
            PostgresRow(["INR", "Indian Rupee", "₹"], ["iso4217", "name", "symbol"]),
            PostgresRow(["USD", "US Dollar", "$"], ["iso4217", "name", "symbol"]),
        ])
        mock_conn.execute.return_value = mock_cursor

        s_pg = Settings.from_env({
            "DATABASE_URL": "postgresql://testuser:testpass@ep-sample.neon.tech/neondb",
            "BOOKING_MODE": "mock",
        })

        with unittest.mock.patch("src.main._validate_startup_db"):
            app = create_app(s_pg)
            app.dependency_overrides[get_conn] = lambda: mock_conn
            client = TestClient(app)

            resp = client.get("/api/v1/currencies", headers={"Origin": "https://yatra-saathi-frontend.vercel.app"})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(data.get("ok"))
            currencies = data.get("data", {}).get("currencies", [])
            self.assertGreaterEqual(len(currencies), 2)
            inr = next((c for c in currencies if c["code"] == "INR"), None)
            self.assertIsNotNone(inr)
            self.assertEqual(inr["name"], "Indian Rupee")
            self.assertEqual(inr["symbol"], "₹")
            self.assertEqual(inr["inrPerUnit"], "1")

    def test_postgres_schema_rate_limits_canonical_structure(self):
        """POSTGRES_DDL_STATEMENTS defines auth_rate_limits with canonical columns."""
        from src.db.postgres_schema import POSTGRES_DDL_STATEMENTS
        rate_limit_ddl = next((ddl for ddl in POSTGRES_DDL_STATEMENTS if "auth_rate_limits" in ddl and "CREATE TABLE" in ddl), None)
        self.assertIsNotNone(rate_limit_ddl)
        self.assertIn("attempt_key", rate_limit_ddl)
        self.assertIn("attempt_type", rate_limit_ddl)
        self.assertIn("first_attempt", rate_limit_ddl)
        self.assertIn("last_attempt", rate_limit_ddl)
        self.assertIn("blocked_until", rate_limit_ddl)
        self.assertIn("PRIMARY KEY (attempt_key, attempt_type)", rate_limit_ddl)

    def test_postgres_schema_rate_limits_additive_migration(self):
        """init_postgres_schema detects legacy auth_rate_limits columns and adds canonical columns."""
        from src.db.postgres_schema import init_postgres_schema

        mock_conn = MagicMock()
        # Simulate table existing with legacy columns (ip_address, attempt_count, ...)
        mock_cols_cursor = MagicMock()
        mock_cols_cursor.fetchall.return_value = [("ip_address",), ("attempt_count",), ("first_attempt_at",)]
        mock_count_cursor = MagicMock()
        mock_count_cursor.fetchone.return_value = (25,)

        def mock_execute(sql, *args, **kwargs):
            if "information_schema.columns" in sql:
                return mock_cols_cursor
            if "SELECT COUNT(*) FROM currencies" in sql:
                return mock_count_cursor
            return MagicMock()

        mock_conn.execute.side_effect = mock_execute
        num_stmts = init_postgres_schema(mock_conn)
        self.assertGreater(num_stmts, 0)

        # Verify additive migration SQL statements were executed
        executed_sqls = [call[0][0] for call in mock_conn.execute.call_args_list]
        self.assertTrue(any("ALTER TABLE auth_rate_limits ADD COLUMN IF NOT EXISTS attempt_key" in s for s in executed_sqls))
        self.assertTrue(any("ALTER TABLE auth_rate_limits ADD COLUMN IF NOT EXISTS attempt_type" in s for s in executed_sqls))
        self.assertTrue(any("ALTER TABLE auth_rate_limits ALTER COLUMN ip_address DROP NOT NULL" in s for s in executed_sqls))


if __name__ == "__main__":
    unittest.main()
