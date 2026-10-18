"""Connections to the working copy only. Never creates a database file."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from src.core.config import REQUIRED_SCHEMA_VERSION, Settings
from src.core.errors import SafetyError
from src.db.working_copy_guard import assert_working_copy


def connect(settings: Settings, *, readonly: bool = False, require_schema: bool = True,
            check_same_thread: bool = True) -> sqlite3.Connection:
    path = settings.require_db_path()
    assert_working_copy(path, settings.original_db_path)
    mode = "ro" if readonly else "rw"  # 'rw' (not 'rwc'): sqlite may not create a new file
    conn = sqlite3.connect(Path(path).resolve().as_uri() + f"?mode={mode}", uri=True,
                           isolation_level=None, check_same_thread=check_same_thread)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {int(settings.busy_timeout_ms)}")
        conn.execute("PRAGMA foreign_keys = ON")
        if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise SafetyError("foreign key enforcement could not be enabled")
        if require_schema:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version < REQUIRED_SCHEMA_VERSION:
                raise SafetyError(
                    f"working copy schema version {version} < required {REQUIRED_SCHEMA_VERSION}; run migrations"
                )
    except Exception:
        conn.close()
        raise
    return conn
