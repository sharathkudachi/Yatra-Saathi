"""Registration behavior when the required home-city catalogue is empty or available."""
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from starlette.requests import Request

from src.api.routes.human.auth import register
from src.contracts.codes import RefusalError
from src.core.clock import SystemClock
from src.schemas.human import RegisterRequest


def _registration_connection(*, include_city: bool) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE cities (city_id TEXT PRIMARY KEY);
        CREATE TABLE auth_rate_limits (
            attempt_key TEXT NOT NULL,
            attempt_type TEXT NOT NULL,
            attempt_count INTEGER NOT NULL,
            first_attempt TEXT NOT NULL,
            last_attempt TEXT NOT NULL,
            blocked_until TEXT,
            PRIMARY KEY (attempt_key, attempt_type)
        );
        CREATE TABLE users (
            user_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            email TEXT NOT NULL,
            home_city_id TEXT NOT NULL REFERENCES cities(city_id),
            home_currency TEXT NOT NULL,
            locale TEXT NOT NULL,
            budget_band TEXT NOT NULL,
            travel_style TEXT NOT NULL,
            traveller_type TEXT NOT NULL,
            segment TEXT NOT NULL,
            date_of_signup TEXT NOT NULL,
            loyalty_tier TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            email_verified INTEGER NOT NULL,
            last_login_at TEXT
        );
        """
    )
    if include_city:
        conn.execute("INSERT INTO cities (city_id) VALUES (?)", ("cty-test",))
    return conn


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/auth/register",
            "raw_path": b"/api/v1/auth/register",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
    )


class RegistrationCityCatalogTests(unittest.TestCase):
    def setUp(self):
        self.body = RegisterRequest(
            full_name="Synthetic QA",
            username="synthetic_qa",
            email="synthetic.qa@example.invalid",
            password="ExploreIndia2026!",
        )
        self.settings = SimpleNamespace(human_token_secret="local-test-secret-0123456789")
        self.clock = SystemClock()

    def test_empty_city_catalog_returns_503_before_hashing_or_insert(self):
        conn = _registration_connection(include_city=False)
        try:
            with patch("src.api.routes.human.auth.auth_security.hash_password") as hash_password:
                with self.assertRaises(RefusalError) as raised:
                    register(self.body, _request(), self.settings, self.clock, conn)

            self.assertEqual(raised.exception.code, "CITY_CATALOG_UNAVAILABLE")
            self.assertEqual(raised.exception.http_status, 503)
            hash_password.assert_not_called()
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
        finally:
            conn.close()

    def test_registration_uses_an_existing_city(self):
        conn = _registration_connection(include_city=True)
        try:
            with patch(
                "src.api.routes.human.auth.auth_security.hash_password",
                return_value="test-hash",
            ) as hash_password:
                response = register(self.body, _request(), self.settings, self.clock, conn)

            hash_password.assert_called_once_with(self.body.password)
            self.assertEqual(response["data"]["user"]["username"], self.body.username)
            self.assertEqual(
                conn.execute("SELECT home_city_id FROM users WHERE username = ?", (self.body.username,)).fetchone()[0],
                "cty-test",
            )
        finally:
            conn.close()

    def test_postgres_unique_email_violation_maps_to_duplicate_refusal(self):
        class FakePostgresIntegrityError(Exception):
            pass

        class FakePostgres:
            IntegrityError = FakePostgresIntegrityError

        class FailingInsertConnection:
            def __init__(self, wrapped):
                self.wrapped = wrapped

            def execute(self, sql, params=()):
                if sql.lstrip().upper().startswith("INSERT INTO USERS"):
                    raise FakePostgresIntegrityError(
                        'duplicate key value violates unique constraint "uq_users_email_lower"'
                    )
                return self.wrapped.execute(sql, params)

            def __getattr__(self, name):
                return getattr(self.wrapped, name)

        conn = _registration_connection(include_city=True)
        try:
            with patch("src.api.routes.human.auth.psycopg2", FakePostgres):
                with self.assertRaises(RefusalError) as raised:
                    register(self.body, _request(), self.settings, self.clock, FailingInsertConnection(conn))

            self.assertEqual(raised.exception.code, "DUPLICATE_EMAIL")
            self.assertEqual(raised.exception.http_status, 409)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
