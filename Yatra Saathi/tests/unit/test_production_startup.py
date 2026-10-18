"""Regression test verifying production entrypoint imports and startup database validation.

Prevents Render startup failures:
    - ModuleNotFoundError: No module named 'scripts' / 'src'
    - NotAWorkingCopy: working copy not found: postgresql://...
"""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from src.core.config import Settings
from src.core.errors import NotAWorkingCopy, RefusedOriginalTarget
from src.db.working_copy_guard import WORKING_COPY_APPLICATION_ID
from src.main import _validate_startup_db


class TestProductionStartupImports(unittest.TestCase):
    def test_direct_script_execution_resolves_scripts_and_src(self):
        """Simulates Render running 'python scripts/run_production.py' from backend root."""
        sub_code = (
            "import sys\n"
            "from pathlib import Path\n"
            "import scripts.run_production\n"
            "import scripts.init_production_db\n"
            "print('SUCCESS: scripts and src resolved cleanly')\n"
        )
        cmd = [sys.executable, "-c", sub_code]
        res = subprocess.run(cmd, cwd=str(_BACKEND_DIR), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Import test failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")
        self.assertIn("SUCCESS: scripts and src resolved cleanly", res.stdout)

    def test_script_path_invocation_resolves_backend_dir(self):
        """Simulates executing 'python scripts/run_production.py' where sys.path[0] is scripts/."""
        sub_code = (
            "import sys\n"
            "from pathlib import Path\n"
            "scripts_dir = Path.cwd() / 'scripts'\n"
            "sys.path[0] = str(scripts_dir)\n"
            "import run_production\n"
            "assert hasattr(run_production, '_BACKEND_DIR')\n"
            "print('SUCCESS: sys.path[0] was normalized and backend root was added')\n"
        )
        cmd = [sys.executable, "-c", sub_code]
        res = subprocess.run(cmd, cwd=str(_BACKEND_DIR), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Path invocation failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")
        self.assertIn("SUCCESS: sys.path[0] was normalized and backend root was added", res.stdout)


class TestStartupDatabaseValidation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.orig_path = os.path.join(self.temp_dir.name, "orig.db")
        with open(self.orig_path, "wb") as f:
            f.write(b"original-database-content")

        self.working_copy = os.path.join(self.temp_dir.name, "working.db")
        conn = sqlite3.connect(self.working_copy)
        conn.execute(f"PRAGMA application_id = {WORKING_COPY_APPLICATION_ID}")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_sqlite_refuses_original_as_target(self):
        """Startup must refuse to run if target resolves to the original database."""
        settings = Settings(
            db_path=self.orig_path,
            database_url=None,
            original_db_path=self.orig_path,
            original_db_sha256=None,
            tax_rate_bp=1200,
            replan_limit=3,
            confirmation_ttl_seconds=900,
            agent_state_max_bytes=1048576,
            busy_timeout_ms=5000,
            booking_mode="mock",
            human_token_secret=None,
            agent_token_secret=None,
            agent_service_key=None,
            agent_service_url=None,
            demo_login_user_ids=(),
        )
        with self.assertRaises(RefusedOriginalTarget):
            _validate_startup_db(settings)

    def test_sqlite_refuses_missing_or_unmarked_database(self):
        """Startup must refuse non-working-copy or missing SQLite file."""
        settings = Settings(
            db_path=os.path.join(self.temp_dir.name, "nonexistent.db"),
            database_url=None,
            original_db_path=self.orig_path,
            original_db_sha256=None,
            tax_rate_bp=1200,
            replan_limit=3,
            confirmation_ttl_seconds=900,
            agent_state_max_bytes=1048576,
            busy_timeout_ms=5000,
            booking_mode="mock",
            human_token_secret=None,
            agent_token_secret=None,
            agent_service_key=None,
            agent_service_url=None,
            demo_login_user_ids=(),
        )
        with self.assertRaises(NotAWorkingCopy):
            _validate_startup_db(settings)

    def test_sqlite_accepts_valid_marked_working_copy(self):
        """Startup accepts a valid marked SQLite working copy."""
        settings = Settings(
            db_path=self.working_copy,
            database_url=None,
            original_db_path=self.orig_path,
            original_db_sha256=None,
            tax_rate_bp=1200,
            replan_limit=3,
            confirmation_ttl_seconds=900,
            agent_state_max_bytes=1048576,
            busy_timeout_ms=5000,
            booking_mode="mock",
            human_token_secret=None,
            agent_token_secret=None,
            agent_service_key=None,
            agent_service_url=None,
            demo_login_user_ids=(),
        )
        # Should not raise
        _validate_startup_db(settings)

    def test_postgres_startup_bypasses_sqlite_working_copy_guard(self):
        """Startup with PostgreSQL DATABASE_URL verifies connection and never calls SQLite working copy guard."""
        pg_url = "postgresql://mock_user:mock_pass@mock_host.render.com:5432/mock_db?sslmode=require"
        settings = Settings(
            db_path=None,
            database_url=pg_url,
            original_db_path=self.orig_path,
            original_db_sha256=None,
            tax_rate_bp=1200,
            replan_limit=3,
            confirmation_ttl_seconds=900,
            agent_state_max_bytes=1048576,
            busy_timeout_ms=5000,
            booking_mode="mock",
            human_token_secret=None,
            agent_token_secret=None,
            agent_service_key=None,
            agent_service_url=None,
            demo_login_user_ids=(),
        )
        self.assertTrue(settings.is_postgres)

        mock_conn = MagicMock()
        with patch("src.db.connection.connect", return_value=mock_conn) as mock_connect, \
             patch("src.main.assert_working_copy") as mock_assert_working_copy:
            _validate_startup_db(settings)
            mock_connect.assert_called_once_with(settings)
            mock_conn.execute.assert_called_once_with("SELECT 1")
            mock_conn.close.assert_called_once()
            mock_assert_working_copy.assert_not_called()

    def test_postgres_startup_fails_if_connection_unhealthy(self):
        """Startup fails with database connection error if PostgreSQL is unreachable."""
        pg_url = "postgresql://mock_user:mock_pass@mock_host.render.com:5432/mock_db?sslmode=require"
        settings = Settings(
            db_path=None,
            database_url=pg_url,
            original_db_path=self.orig_path,
            original_db_sha256=None,
            tax_rate_bp=1200,
            replan_limit=3,
            confirmation_ttl_seconds=900,
            agent_state_max_bytes=1048576,
            busy_timeout_ms=5000,
            booking_mode="mock",
            human_token_secret=None,
            agent_token_secret=None,
            agent_service_key=None,
            agent_service_url=None,
            demo_login_user_ids=(),
        )
        with patch("src.db.connection.connect", side_effect=ConnectionRefusedError("PostgreSQL connection refused")), \
             patch("src.main.assert_working_copy") as mock_assert_working_copy:
            with self.assertRaises(ConnectionRefusedError):
                _validate_startup_db(settings)
            mock_assert_working_copy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
