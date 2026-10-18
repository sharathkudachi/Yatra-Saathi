# travel_agent/tools/db.py
"""Read-only access to the organiser-supplied APS-01.db.

The database is the source of truth and is never written: every connection is
opened in SQLite URI read-only mode with ``PRAGMA query_only`` as a second guard.
Developer 1 owns the application's DB layer; this module exists only so the agent
can read catalogue data until Developer 1 confirms the final access path.
"""
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

# Resolve path to <project root>/data/APS-01.db (override with APS01_DB_PATH)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DB_PATH = _PROJECT_ROOT / "data" / "APS-01.db"


def db_path() -> Path:
    return Path(os.environ.get("APS01_DB_PATH", str(_DEFAULT_DB_PATH)))


def query_db(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """
    Executes a read-only query against APS-01.db in URI mode.
    Raises sqlite3.OperationalError if any write or alteration is attempted.
    """
    path = db_path()
    if not path.exists():
        raise FileNotFoundError(f"Database not found at {path}. Set APS01_DB_PATH or place APS-01.db in data/")

    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = ON")
        cursor = conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
