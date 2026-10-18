"""Repository for user travel preferences (Phase 4).

Features:
- Pure SQL operations strictly scoped by user_id (multi-tenant safety).
- JSON encoding/decoding for flexible typed values (booleans, numbers, lists).
- Idempotent table and index creation.
- Foreign key cascade on user deletion.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.ids import new_id
from src.schemas.preferences import (
    PreferenceItem,
    PreferencePriority,
    PreferenceSource,
    UserTravelProfile,
)


def ensure_table_exists(conn: sqlite3.Connection) -> None:
    """Ensure the user_preferences table and index exist idempotently."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS user_preferences (
            preference_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            preference_key TEXT NOT NULL,
            preference_value TEXT NOT NULL,
            is_hard INTEGER NOT NULL DEFAULT 0,
            priority TEXT NOT NULL DEFAULT 'medium',
            confidence REAL NOT NULL DEFAULT 1.0,
            source TEXT NOT NULL DEFAULT 'explicit_user',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, preference_key)
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_preferences_user ON user_preferences(user_id)"
    )


def get_preferences_for_user(conn: sqlite3.Connection, user_id: str) -> Dict[str, PreferenceItem]:
    """Retrieve all active preferences for the given authenticated user."""
    ensure_table_exists(conn)
    cur = conn.execute(
        """SELECT preference_key, preference_value, is_hard, priority, confidence,
                  source, created_at, updated_at, active
           FROM user_preferences
           WHERE user_id = ? AND active = 1
           ORDER BY updated_at DESC""",
        (user_id,),
    )
    result: Dict[str, PreferenceItem] = {}
    for row in cur.fetchall():
        key = row[0] if isinstance(row, tuple) else row["preference_key"]
        val_raw = row[1] if isinstance(row, tuple) else row["preference_value"]
        is_hard = bool(row[2] if isinstance(row, tuple) else row["is_hard"])
        priority = row[3] if isinstance(row, tuple) else row["priority"]
        confidence = float(row[4] if isinstance(row, tuple) else row["confidence"])
        source = row[5] if isinstance(row, tuple) else row["source"]
        created_at = row[6] if isinstance(row, tuple) else row["created_at"]
        updated_at = row[7] if isinstance(row, tuple) else row["updated_at"]
        active = bool(row[8] if isinstance(row, tuple) else row["active"])

        try:
            val = json.loads(val_raw)
        except Exception:
            val = val_raw

        result[key] = PreferenceItem(
            preference_key=key,
            value=val,
            is_hard=is_hard,
            priority=PreferencePriority(priority),
            confidence=confidence,
            source=PreferenceSource(source),
            created_at=created_at,
            updated_at=updated_at,
            active=active,
        )
    return result


def upsert_preference(
    conn: sqlite3.Connection,
    user_id: str,
    item: PreferenceItem,
    *,
    now_iso: Optional[str] = None,
) -> PreferenceItem:
    """Insert or update a user preference, maintaining ownership and timestamps."""
    ensure_table_exists(conn)
    now = now_iso or datetime.now(timezone.utc).isoformat()
    val_json = json.dumps(item.value)
    pref_id = new_id("prf")

    conn.execute(
        """INSERT INTO user_preferences (
            preference_id, user_id, preference_key, preference_value,
            is_hard, priority, confidence, source, active,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, preference_key) DO UPDATE SET
            preference_value = excluded.preference_value,
            is_hard = excluded.is_hard,
            priority = excluded.priority,
            confidence = excluded.confidence,
            source = excluded.source,
            active = excluded.active,
            updated_at = excluded.updated_at""",
        (
            pref_id,
            user_id,
            item.preference_key,
            val_json,
            1 if item.is_hard else 0,
            item.priority.value,
            item.confidence,
            item.source.value,
            1 if item.active else 0,
            now,
            now,
        ),
    )

    return item.model_copy(
        update={
            "created_at": item.created_at or now,
            "updated_at": now,
        }
    )


def upsert_preferences(
    conn: sqlite3.Connection,
    user_id: str,
    items: List[PreferenceItem],
    *,
    now_iso: Optional[str] = None,
) -> List[PreferenceItem]:
    """Batch upsert multiple user preference items."""
    return [upsert_preference(conn, user_id, it, now_iso=now_iso) for it in items]


def get_profile(conn: sqlite3.Connection, user_id: str) -> UserTravelProfile:
    """Retrieve full UserTravelProfile for a user."""
    prefs = get_preferences_for_user(conn, user_id)
    return UserTravelProfile(
        user_id=user_id,
        preferences=prefs,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


def delete_preference(conn: sqlite3.Connection, user_id: str, preference_key: str) -> bool:
    """Delete a specific preference for an authenticated user."""
    ensure_table_exists(conn)
    cur = conn.execute(
        "DELETE FROM user_preferences WHERE user_id = ? AND preference_key = ?",
        (user_id, preference_key.strip().lower()),
    )
    return cur.rowcount > 0


def clear_preferences_for_user(conn: sqlite3.Connection, user_id: str) -> int:
    """Delete all preferences for an authenticated user."""
    ensure_table_exists(conn)
    cur = conn.execute("DELETE FROM user_preferences WHERE user_id = ?", (user_id,))
    return cur.rowcount
