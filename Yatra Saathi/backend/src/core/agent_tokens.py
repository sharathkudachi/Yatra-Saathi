"""Agent tokens: HMAC-signed with AGENT_TOKEN_SECRET (backend only). Claims:
role='agent', session_id, run_id, issued/expiry (30 min, renewed on resume).
Session-scoped: a token for session A used against session B's routes is a 403
(SESSION_ACCESS_DENIED), checked by the caller comparing session ids. Rejected
on every human route."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.core._signing import TokenExpired, TokenMalformed, TokenWrongRole, sign, unsign
from src.core.clock import format_utc, parse_utc

DEFAULT_TTL_SECONDS = 30 * 60


@dataclass(frozen=True)
class AgentClaims:
    session_id: str
    run_id: str
    issued_at: str
    expires_at: str


def issue(secret: str, *, session_id: str, run_id: str, now: datetime,
          ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str:
    claims = {
        "role": "agent",
        "session_id": session_id,
        "run_id": run_id,
        "iat": format_utc(now),
        "exp": format_utc(now + timedelta(seconds=ttl_seconds)),
    }
    return sign(secret, claims)


def verify(secret: str, token: str, *, now: datetime) -> AgentClaims:
    claims = unsign(secret, token)
    if claims.get("role") != "agent":
        raise TokenWrongRole("token is not an agent token")
    for field in ("session_id", "run_id", "iat", "exp"):
        if not isinstance(claims.get(field), str):
            raise TokenMalformed(f"agent token missing field: {field}")
    try:
        expires_at = parse_utc(claims["exp"])
    except ValueError as exc:
        raise TokenMalformed("agent token has a malformed expiry") from exc
    if now.astimezone(timezone.utc) >= expires_at:
        raise TokenExpired("agent token has expired")
    return AgentClaims(session_id=claims["session_id"], run_id=claims["run_id"],
                       issued_at=claims["iat"], expires_at=claims["exp"])
