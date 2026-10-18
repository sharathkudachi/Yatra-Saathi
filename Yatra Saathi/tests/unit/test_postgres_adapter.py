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

    def test_postgres_schema_sessions_and_notifications_canonical(self):
        """POSTGRES_DDL_STATEMENTS defines agent_sessions, notifications, and emergency tables."""
        from src.db.postgres_schema import POSTGRES_DDL_STATEMENTS
        
        sessions_ddl = next((ddl for ddl in POSTGRES_DDL_STATEMENTS if "agent_sessions" in ddl and "CREATE TABLE" in ddl), None)
        self.assertIsNotNone(sessions_ddl)
        self.assertIn("last_error_code", sessions_ddl)
        self.assertIn("goal_text", sessions_ddl)
        self.assertIn("constraints_json", sessions_ddl)
        self.assertIn("spend_committed", sessions_ddl)

        notif_ddl = next((ddl for ddl in POSTGRES_DDL_STATEMENTS if "phase6_notifications" in ddl and "CREATE TABLE" in ddl), None)
        self.assertIsNotNone(notif_ddl)
        self.assertIn("is_read", notif_ddl)
        self.assertIn("event_type", notif_ddl)
        self.assertIn("dedupe_key", notif_ddl)

        pack_ddl = next((ddl for ddl in POSTGRES_DDL_STATEMENTS if "trip_packs" in ddl and "CREATE TABLE" in ddl), None)
        self.assertIsNotNone(pack_ddl)

        emergency_ddl = next((ddl for ddl in POSTGRES_DDL_STATEMENTS if "phase6_emergency_contacts" in ddl and "CREATE TABLE" in ddl), None)
        self.assertIsNotNone(emergency_ddl)

    def test_postgres_schema_additive_migrations_for_sessions_and_notifications(self):
        """init_postgres_schema applies additive migrations for agent_sessions and notifications."""
        from src.db.postgres_schema import init_postgres_schema

        mock_conn = MagicMock()
        mock_count_cursor = MagicMock()
        mock_count_cursor.fetchone.return_value = (25,)
        mock_conn.execute.return_value = mock_count_cursor

        num_stmts = init_postgres_schema(mock_conn)
        self.assertGreater(num_stmts, 0)

        executed_sqls = [call[0][0] for call in mock_conn.execute.call_args_list]
        self.assertTrue(any("ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS last_error_code" in s for s in executed_sqls))
        self.assertTrue(any("ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS constraints_json" in s for s in executed_sqls))
        self.assertTrue(any("ALTER TABLE phase6_notifications ADD COLUMN IF NOT EXISTS is_read" in s for s in executed_sqls))
        self.assertTrue(any("ALTER TABLE phase6_notifications ADD COLUMN IF NOT EXISTS dedupe_key" in s for s in executed_sqls))

    def test_errors_cors_headers_approved_origin(self):
        """Errors handler attaches CORS headers for trusted frontend origin."""
        from unittest.mock import MagicMock
        from src.api.errors import _cors_headers, is_trusted_origin

        req = MagicMock()
        req.headers.get.side_effect = lambda k: "https://yatra-saathi-frontend.vercel.app" if k == "origin" else None
        req.app.state.settings.cors_allow_origins = ["https://yatra-saathi-frontend.vercel.app"]
        self.assertTrue(is_trusted_origin("https://yatra-saathi-frontend.vercel.app", req))

        headers = _cors_headers(req)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "https://yatra-saathi-frontend.vercel.app")
        # Ensure credentials header is not emitted (auth uses Bearer tokens)
        self.assertNotIn("Access-Control-Allow-Credentials", headers)
        self.assertIn("GET", headers.get("Access-Control-Allow-Methods", ""))
        self.assertIn("Authorization", headers.get("Access-Control-Allow-Headers", ""))

    def test_errors_cors_headers_unapproved_origin_rejected(self):
        """Errors handler rejects unapproved or arbitrary origins."""
        from unittest.mock import MagicMock
        from src.api.errors import _cors_headers, is_trusted_origin

        req = MagicMock()
        req.app.state.settings.cors_allow_origins = ["https://yatra-saathi-frontend.vercel.app"]

        # Multiple hostile origin variations
        hostile_origins = [
            "https://attacker.evil.com",
            "https://evil-yatra-saathi-frontend.vercel.app",
            "https://attacker.com",
            "http://malicious.org",
        ]
        for hostile in hostile_origins:
            req.headers.get.side_effect = lambda k, h=hostile: h if k == "origin" else None
            self.assertFalse(is_trusted_origin(hostile, req), f"Expected {hostile} to be rejected")
            headers = _cors_headers(req)
            self.assertEqual(headers, {}, f"Expected empty headers for {hostile}")

    def test_cors_preflight_approved_and_unapproved(self):
        """Test preflight OPTIONS handling for approved and unapproved origins."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from fastapi.middleware.cors import CORSMiddleware
        from src.api.errors import register

        app = FastAPI()
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["https://yatra-saathi-frontend.vercel.app", "http://localhost:5173"],
            allow_origin_regex=r"^https:\/\/.*yatra-saathi-frontend.*\.vercel\.app$",
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
            allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID", "Origin"],
        )
        register(app)

        @app.get("/test-endpoint")
        def sample():
            return {"ok": True}

        client = TestClient(app)

        # 1. Preflight from approved origin
        res = client.options("/test-endpoint", headers={
            "Origin": "https://yatra-saathi-frontend.vercel.app",
            "Access-Control-Request-Method": "GET",
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("access-control-allow-origin"), "https://yatra-saathi-frontend.vercel.app")
        self.assertNotIn("access-control-allow-credentials", res.headers)

        # 2. Preflight from hostile origin
        res = client.options("/test-endpoint", headers={
            "Origin": "https://attacker.evil.com",
            "Access-Control-Request-Method": "GET",
        })
        self.assertNotEqual(res.headers.get("access-control-allow-origin"), "https://attacker.evil.com")

    def test_unhandled_exception_sanitizes_internal_errors(self):
        """Unhandled 500 exceptions must not leak SQL queries or stack traces."""
        import asyncio
        from unittest.mock import MagicMock
        from fastapi import FastAPI
        from src.api.errors import register

        app = FastAPI()
        register(app)

        # Retrieve registered 500 handler
        handler = app.exception_handlers.get(Exception)
        self.assertIsNotNone(handler)

        req = MagicMock()
        req.method = "POST"
        req.url = "http://testserver/api/v1/search/hotels"
        req.headers.get.side_effect = lambda k: "https://yatra-saathi-frontend.vercel.app" if k == "origin" else None

        exc = RuntimeError("psycopg2.OperationalError: syntax error at or near 'SELECT table_secrets'")
        resp = asyncio.run(handler(req, exc))

        self.assertEqual(resp.status_code, 500)
        import json
        body = json.loads(resp.body.decode("utf-8"))
        self.assertEqual(body.get("ok"), False)
        self.assertEqual(body.get("refusal", {}).get("code"), "INTERNAL_ERROR")
        # Message must be generic and not contain the SQL syntax error or secret name
        self.assertNotIn("table_secrets", body.get("refusal", {}).get("message", ""))
        self.assertNotIn("syntax error", body.get("refusal", {}).get("message", ""))
        self.assertIn("internal server error", body.get("refusal", {}).get("message", "").lower())


if __name__ == "__main__":
    unittest.main()
