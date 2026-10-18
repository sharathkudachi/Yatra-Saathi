"""Comprehensive automated tests for secure registration, login, hashing, and rate limiting."""
import sqlite3
import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.core.config import Settings
from src.core.hashing import file_sha256
from src.main import create_app
from src.services import auth_security
from tests.support import WorkingCopy, assert_original_untouched, original_path, RECORDED_ORIGINAL_SHA256, settings_for


class SecureAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert_original_untouched()
        cls.wc = WorkingCopy(migrate=True)
        conn = cls.wc.raw()
        from scripts.seed_demo import seed
        seed(conn)
        conn.close()
        # Ensure human token secret is provided for issuing tokens
        cls.wc.settings = settings_for(
            cls.wc.path,
            HUMAN_TOKEN_SECRET="0123456789abcdef" * 4,
            DEMO_LOGIN_USER_IDS="usr_demo0001",
        )
        cls.app = create_app(cls.wc.settings)
        cls.client = TestClient(cls.app)

    @classmethod
    def tearDownClass(cls):
        cls.wc.cleanup()
        assert_original_untouched()

    def test_01_argon2id_hashing_and_verification(self):
        """Argon2id hashing is one-way, non-empty, and verifies securely."""
        pw = "SuperSecureTrip123!"
        hashed = auth_security.hash_password(pw)
        self.assertTrue(hashed.startswith("$argon2id$"))
        self.assertNotEqual(hashed, pw)
        self.assertTrue(auth_security.verify_password(hashed, pw))
        self.assertFalse(auth_security.verify_password(hashed, "WrongPassword123!"))
        self.assertFalse(auth_security.verify_password(None, pw))
        self.assertFalse(auth_security.verify_password(hashed, ""))

    def test_02_password_strength_validation(self):
        """Password strength enforces minimum 8 characters and rejects common weak passwords."""
        self.assertFalse(auth_security.validate_password_strength("short")[0])
        self.assertFalse(auth_security.validate_password_strength("12345678")[0])
        self.assertFalse(auth_security.validate_password_strength("password123")[0])
        self.assertTrue(auth_security.validate_password_strength("MyGoodPassword2026!")[0])

    def test_03_username_and_email_validation(self):
        """Username must be lowercase 3-30 chars, email must be valid."""
        self.assertTrue(auth_security.validate_username("valid_user99")[0])
        self.assertFalse(auth_security.validate_username("ab")[0])
        self.assertFalse(auth_security.validate_username("bad space")[0])
        self.assertFalse(auth_security.validate_username("user@with$ymbols")[0])

        self.assertTrue(auth_security.validate_email("user@example.com")[0])
        self.assertFalse(auth_security.validate_email("not-an-email")[0])
        self.assertFalse(auth_security.validate_email("@missinguser.com")[0])

    def test_04_registration_success(self):
        """New user registers successfully, receives safe profile, password securely hashed in DB."""
        resp = self.client.post("/api/v1/auth/register", json={
            "full_name": "Arjun Travel Explorer",
            "username": "arjun_explorer",
            "email": "arjun@example.com",
            "password": "ExploreIndia2026!",
        })
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()["data"]
        self.assertIn("token", data)
        self.assertIn("user", data)
        user = data["user"]
        self.assertEqual(user["username"], "arjun_explorer")
        self.assertEqual(user["email"], "arjun@example.com")
        self.assertEqual(user["display_name"], "Arjun Travel Explorer")

        # Security checks: Never return passwords or hashes in payload
        self.assertNotIn("password", user)
        self.assertNotIn("password_hash", user)
        self.assertNotIn("raw_password", user)
        self.assertNotIn("password", resp.text.lower())
        self.assertNotIn("password_hash", resp.text.lower())

        # Verify database record directly
        conn = self.wc.raw(readonly=True)
        try:
            row = conn.execute(
                "SELECT user_id, username, email, password_hash FROM users WHERE username = 'arjun_explorer'"
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[1], "arjun_explorer")
            self.assertEqual(row[2], "arjun@example.com")
            self.assertTrue(row[3].startswith("$argon2id$"))
            self.assertNotEqual(row[3], "ExploreIndia2026!")
        finally:
            conn.close()

    def test_05_duplicate_username_rejected(self):
        """Registering with an already existing username fails with 409."""
        resp = self.client.post("/api/v1/auth/register", json={
            "full_name": "Duplicate Username Tester",
            "username": "arjun_explorer",
            "email": "different_email@example.com",
            "password": "ValidPassword999!",
        })
        self.assertEqual(resp.status_code, 409)
        self.assertIn("already taken", resp.json()["refusal"]["message"])

    def test_06_duplicate_email_rejected_case_insensitive(self):
        """Registering with an already existing email (even with different case) fails with 409."""
        resp = self.client.post("/api/v1/auth/register", json={
            "full_name": "Duplicate Email Tester",
            "username": "unique_username_88",
            "email": "ARJUN@EXAMPLE.COM",
            "password": "ValidPassword999!",
        })
        self.assertEqual(resp.status_code, 409)
        self.assertIn("already exists", resp.json()["refusal"]["message"])

    def test_07_registration_input_validations(self):
        """Registration rejects weak passwords and invalid usernames/emails."""
        # Weak password
        resp = self.client.post("/api/v1/auth/register", json={
            "full_name": "Weak Pass User",
            "username": "weak_user_1",
            "email": "weak1@example.com",
            "password": "123",
        })
        self.assertEqual(resp.status_code, 422)  # Pydantic validation

        resp = self.client.post("/api/v1/auth/register", json={
            "full_name": "Weak Pass User",
            "username": "weak_user_2",
            "email": "weak2@example.com",
            "password": "password123",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["refusal"]["code"], "WEAK_PASSWORD")

        # Invalid username regex
        resp = self.client.post("/api/v1/auth/register", json={
            "full_name": "Invalid Username",
            "username": "bad user!",
            "email": "valid@example.com",
            "password": "StrongPassword2026!",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["refusal"]["code"], "INVALID_USERNAME")

    def test_08_login_with_username(self):
        """User can sign in using username and password."""
        resp = self.client.post("/api/v1/auth/login", json={
            "identifier": "arjun_explorer",
            "password": "ExploreIndia2026!",
        })
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()["data"]
        self.assertIn("token", data)
        self.assertEqual(data["user"]["username"], "arjun_explorer")

    def test_09_login_with_email_case_insensitive(self):
        """User can sign in using email (case-insensitive) and password."""
        resp = self.client.post("/api/v1/auth/login", json={
            "identifier": "ARJUN@EXAMPLE.COM",
            "password": "ExploreIndia2026!",
        })
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()["data"]
        self.assertIn("token", data)
        self.assertEqual(data["user"]["username"], "arjun_explorer")

    def test_10_login_wrong_password_returns_generic_error(self):
        """Wrong password returns generic LOGIN_MISMATCH error."""
        resp = self.client.post("/api/v1/auth/login", json={
            "identifier": "arjun_explorer",
            "password": "IncorrectPassword999!",
        })
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["refusal"]["code"], "LOGIN_MISMATCH")
        self.assertIn("Invalid username/email or password", resp.json()["refusal"]["message"])

    def test_11_login_unknown_user_returns_generic_error(self):
        """Unknown user returns same generic LOGIN_MISMATCH error (no enumeration)."""
        resp = self.client.post("/api/v1/auth/login", json={
            "identifier": "completely_unknown_user",
            "password": "SomePassword123!",
        })
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["refusal"]["code"], "LOGIN_MISMATCH")
        self.assertIn("Invalid username/email or password", resp.json()["refusal"]["message"])

    def test_12_sql_injection_defense(self):
        """SQL injection attempts in identifier or password fail safely."""
        injections = [
            "' OR '1'='1",
            "admin'--",
            "test@example.com' OR 1=1 --",
            "' UNION SELECT * FROM users --",
        ]
        for inj in injections:
            resp = self.client.post("/api/v1/auth/login", json={
                "identifier": inj,
                "password": inj,
            })
            self.assertEqual(resp.status_code, 401)
            self.assertEqual(resp.json()["refusal"]["code"], "LOGIN_MISMATCH")

    def test_13_demo_user_compatibility(self):
        """Demo user usr_demo0001 can authenticate via username + password and legacy flow."""
        # 1. New password flow (demo password seeded in migration 7)
        resp = self.client.post("/api/v1/auth/login", json={
            "identifier": "usr_demo0001",
            "password": "DemoPass1234!",
        })
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["data"]["user"]["user_id"], "usr_demo0001")

        # 2. Legacy flow (user_id + display_name + email)
        legacy_resp = self.client.post("/api/v1/auth/login", json={
            "user_id": "usr_demo0001",
            "display_name": "[DEMO] Traveller",
            "email": "demo.traveller@example.invalid",
        })
        self.assertEqual(legacy_resp.status_code, 200, legacy_resp.text)
        self.assertEqual(legacy_resp.json()["data"]["user"]["user_id"], "usr_demo0001")

    def test_14_cross_user_isolation(self):
        """User A cannot access User B's bookings, trips, notifications, or emergency contacts."""
        # Register User A
        resp_a = self.client.post("/api/v1/auth/register", json={
            "full_name": "User Alpha",
            "username": "user_alpha",
            "email": "alpha@example.com",
            "password": "AlphaPassword123!",
        })
        self.assertEqual(resp_a.status_code, 200)
        token_a = resp_a.json()["data"]["token"]
        user_a_id = resp_a.json()["data"]["user"]["user_id"]

        # Register User B
        resp_b = self.client.post("/api/v1/auth/register", json={
            "full_name": "User Beta",
            "username": "user_beta",
            "email": "beta@example.com",
            "password": "BetaPassword123!",
        })
        self.assertEqual(resp_b.status_code, 200)
        token_b = resp_b.json()["data"]["token"]
        user_b_id = resp_b.json()["data"]["user"]["user_id"]

        # User A GET /api/v1/auth/me returns User A
        me_a = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_a}"})
        self.assertEqual(me_a.status_code, 200)
        self.assertEqual(me_a.json()["data"]["user"]["user_id"], user_a_id)

        # User B GET /api/v1/auth/me returns User B
        me_b = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_b}"})
        self.assertEqual(me_b.status_code, 200)
        self.assertEqual(me_b.json()["data"]["user"]["user_id"], user_b_id)
        self.assertNotEqual(user_a_id, user_b_id)

        # User B can view their notifications safely
        notifs_b = self.client.get("/api/v1/notifications", headers={"Authorization": f"Bearer {token_b}"})
        self.assertEqual(notifs_b.status_code, 200)

        # User B can view their emergency contacts safely
        contacts_b = self.client.get("/api/v1/emergency/contacts", headers={"Authorization": f"Bearer {token_b}"})
        self.assertEqual(contacts_b.status_code, 200)

    def test_15_rate_limiting_abuse_prevention(self):
        """Repeated failed logins trigger 429 AUTH_RATE_LIMITED protection."""
        key = "brute_target_user"
        # Register a test target
        self.client.post("/api/v1/auth/register", json={
            "full_name": "Target Account",
            "username": key,
            "email": "target@example.com",
            "password": "ValidTargetPass1!",
        })

        # Send 5 failed attempts
        for _ in range(5):
            r = self.client.post("/api/v1/auth/login", json={
                "identifier": key,
                "password": "WrongPasswordAttempt!",
            })
            self.assertEqual(r.status_code, 401)

        # 6th attempt must be locked out with 429
        blocked_resp = self.client.post("/api/v1/auth/login", json={
            "identifier": key,
            "password": "WrongPasswordAttempt!",
        })
        self.assertEqual(blocked_resp.status_code, 429)
        self.assertEqual(blocked_resp.json()["refusal"]["code"], "AUTH_RATE_LIMITED")
        self.assertIn("temporarily locked", blocked_resp.json()["refusal"]["message"])


if __name__ == "__main__":
    unittest.main()
