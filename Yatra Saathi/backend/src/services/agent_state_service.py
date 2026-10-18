"""Agent-saved JSON state: object only, <= 1MB, versioned, checksummed (section 6/15)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from src.contracts.codes import RefusalError
from src.core.clock import Clock
from src.core.hashing import canonical_json, sha256_hex
from src.db.repositories import agent_state as state_repo


@dataclass(frozen=True)
class StateView:
    state: dict
    version: int


def _validate_object(state: object, max_bytes: int) -> str:
    if not isinstance(state, dict):
        raise RefusalError("STATE_INVALID", "state must be a JSON object")
    try:
        text = canonical_json(state)
    except TypeError as exc:
        raise RefusalError("STATE_INVALID", f"state is not valid JSON: {exc}") from exc
    if len(text.encode("utf-8")) > max_bytes:
        raise RefusalError("STATE_TOO_LARGE", f"state exceeds {max_bytes} bytes")
    return text


def get_state(conn, session_id: str) -> Optional[StateView]:
    row = state_repo.get(conn, session_id)
    if row is None:
        return None
    if sha256_hex(row.state_json) != row.state_sha256:
        raise RefusalError("STATE_CORRUPT", "stored state checksum does not match its content")
    try:
        state = json.loads(row.state_json)
    except json.JSONDecodeError as exc:
        raise RefusalError("STATE_CORRUPT", f"stored state is not valid JSON: {exc}") from exc
    return StateView(state=state, version=row.state_version)


def put_state(conn, clock: Clock, session_id: str, new_state: dict, *,
              if_match_version: Optional[int], max_bytes: int) -> StateView:
    text = _validate_object(new_state, max_bytes)
    existing = state_repo.get(conn, session_id)
    now = clock.utc()

    if existing is None:
        if if_match_version not in (None, 0):
            raise RefusalError("STATE_VERSION_CONFLICT", "no existing state for this session")
        state_repo.insert(conn, session_id=session_id, state_json=text,
                           state_sha256=sha256_hex(text), updated_at=now)
        return StateView(state=new_state, version=1)

    if if_match_version != existing.state_version:
        raise RefusalError(
            "STATE_VERSION_CONFLICT",
            f"If-Match {if_match_version} does not match current version {existing.state_version}",
        )
    new_version = existing.state_version + 1
    state_repo.update(conn, session_id=session_id, new_version=new_version, state_json=text,
                       state_sha256=sha256_hex(text), updated_at=now)
    return StateView(state=new_state, version=new_version)
