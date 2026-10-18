import ast
import os
import re
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone

from src.core.clock import FixedClock, format_existing, format_utc, parse_utc
from src.core.config import Settings
from src.core.errors import ConfigError
from src.core.hashing import canonical_json, sha256_hex
from src.core.ids import new_booking_reference, new_id, new_idempotency_key

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ClockTests(unittest.TestCase):
    def test_utc_format_satisfies_schema_check(self):
        dt = datetime(2026, 9, 24, 4, 30, 5, 123456, tzinfo=timezone.utc)
        text = format_utc(dt)
        self.assertEqual(text, "2026-09-24T04:30:05.123Z")
        conn = sqlite3.connect(":memory:")
        self.assertEqual(conn.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ', ?) = ?", (text, text)).fetchone()[0], 1)
        self.assertEqual(parse_utc(text), dt.replace(microsecond=123000))

    def test_existing_format_is_plus_0530(self):
        dt = datetime(2026, 9, 24, 4, 30, 0, tzinfo=timezone.utc)
        self.assertEqual(format_existing(dt), "2026-09-24T10:00:00+05:30")

    def test_naive_datetimes_rejected(self):
        with self.assertRaises(ValueError):
            format_utc(datetime(2026, 1, 1))
        with self.assertRaises(ValueError):
            FixedClock(datetime(2026, 1, 1))

    def test_fixed_clock_advances(self):
        c = FixedClock(datetime(2026, 9, 24, tzinfo=timezone.utc))
        c.advance(901)
        self.assertEqual(c.now(), datetime(2026, 9, 24, tzinfo=timezone.utc) + timedelta(seconds=901))


class IdTests(unittest.TestCase):
    def test_new_table_ids_match_schema_pattern(self):
        for prefix in ["aud", "crt", "cit", "grp", "cnf", "run"]:
            self.assertRegex(new_id(prefix), rf"^{prefix}_[0-9a-f]{{16}}$")

    def test_existing_table_ids_follow_existing_convention(self):
        for prefix in ["agt", "bkg", "bit", "pay", "hld", "trp", "bud", "usr"]:
            self.assertRegex(new_id(prefix), rf"^{prefix}_[0-9a-f]{{8}}$")
        self.assertRegex(new_idempotency_key("idem"), r"^idem_[0-9a-f]{16}$")
        self.assertRegex(new_booking_reference(), r"^YTR-DEMO-[0-9A-F]{8}$")

    def test_unknown_prefix_rejected(self):
        with self.assertRaises(ValueError):
            new_id("xyz")


class HashingTests(unittest.TestCase):
    def test_canonical_json_is_order_independent(self):
        self.assertEqual(canonical_json({"b": 1, "a": "x"}), canonical_json({"a": "x", "b": 1}))
        self.assertEqual(sha256_hex(canonical_json({"a": 1})), sha256_hex('{"a":1}'))

    def test_floats_rejected(self):
        for obj in [1.5, {"a": 0.1}, [1, 2.0]]:
            with self.subTest(obj=obj), self.assertRaises(TypeError):
                canonical_json(obj)


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        s = Settings.from_env({})
        self.assertEqual((s.tax_rate_bp, s.replan_limit, s.confirmation_ttl_seconds, s.agent_state_max_bytes),
                         (1200, 3, 900, 1048576))

    def test_booking_mode_must_be_mock(self):
        with self.assertRaises(ConfigError):
            Settings.from_env({"BOOKING_MODE": "live"})

    def test_missing_db_path_is_an_error(self):
        with self.assertRaises(ConfigError):
            Settings.from_env({}).require_db_path()
        with self.assertRaises(ConfigError):
            Settings.from_env({}).require_original()

    def test_invalid_values_rejected(self):
        for env in [{"APS_DB_ORIGINAL_SHA256": "ABC"}, {"TAX_RATE_BP": "12%"},
                    {"TAX_RATE_BP": "10001"}, {"AGENT_STATE_MAX_BYTES": "2000000"}]:
            with self.subTest(env=env), self.assertRaises(ConfigError):
                Settings.from_env(env)


class NoHardcodedPathTests(unittest.TestCase):
    """No string literal in application code may be a database file or absolute path."""

    @staticmethod
    def _docstring_nodes(tree):
        ids = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = getattr(node, "body", [])
                if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                    ids.add(id(body[0].value))
        return ids

    def test_application_code_has_no_hardcoded_database_path(self):
        offenders = []
        for root, _dirs, files in os.walk(os.path.join(BACKEND, "src")):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                with open(path, encoding="utf-8") as fh:
                    tree = ast.parse(fh.read())
                docstrings = self._docstring_nodes(tree)
                for node in ast.walk(tree):
                    if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                            and id(node) not in docstrings):
                        v = node.value
                        if v.endswith(".db") or "/mnt/" in v or re.match(r"^(/|[A-Za-z]:[\\/])\S*\.\w+$", v):
                            offenders.append(f"{path}: {v!r}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
