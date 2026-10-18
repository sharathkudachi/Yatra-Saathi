"""Repository for `agent_session_state`."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AgentState:
    session_id: str
    state_version: int
    state_json: str
    state_sha256: str
    updated_at: str


def get(conn: sqlite3.Connection, session_id: str) -> Optional[AgentState]:
    row = conn.execute(
        "SELECT * FROM agent_session_state WHERE session_id = ?", (session_id,)
    ).fetchone()
    if not row:
        return None
    return AgentState(row["session_id"], row["state_version"], row["state_json"],
                       row["state_sha256"], row["updated_at"])


def insert(conn: sqlite3.Connection, *, session_id: str, state_json: str, state_sha256: str,
           updated_at: str) -> None:
    conn.execute(
        """INSERT INTO agent_session_state (session_id, state_version, state_json, state_sha256, updated_at)
           VALUES (?, 1, ?, ?, ?)""",
        (session_id, state_json, state_sha256, updated_at),
    )


def update(conn: sqlite3.Connection, *, session_id: str, new_version: int, state_json: str,
           state_sha256: str, updated_at: str) -> None:
    conn.execute(
        """UPDATE agent_session_state SET state_version = ?, state_json = ?, state_sha256 = ?,
             updated_at = ? WHERE session_id = ?""",
        (new_version, state_json, state_sha256, updated_at, session_id),
    )
