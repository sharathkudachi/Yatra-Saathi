"""Human tokens: HMAC-signed with HUMAN_TOKEN_SECRET (backend only). Claims:
user_id, role='user', issued/expiry (8h default), a unique id. Demo login only
issues these for `DEMO_LOGIN_USER_IDS`. Rejected on every agent route."""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.core._signing import TokenExpired, TokenMalformed, TokenWrongRole, sign, unsign
from src.core.clock import format_utc, parse_utc

DEFAULT_TTL_SECONDS = 8 * 3600


@dataclass(frozen=True)
class HumanClaims:
    user_id: str
    jti: str
    issued_at: str
    expires_at: str


def issue(secret: str, user_id: str, *, now: datetime, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str:
    claims = {
        "role": "user",
        "user_id": user_id,
        "jti": secrets.token_hex(16),
        "iat": format_utc(now),
        "exp": format_utc(now + timedelta(seconds=ttl_seconds)),
    }
    return sign(secret, claims)


def verify(secret: str, token: str, *, now: datetime) -> HumanClaims:
    claims = unsign(secret, token)
    if claims.get("role") != "user":
        raise TokenWrongRole("token is not a human (user) token")
    for field in ("user_id", "jti", "iat", "exp"):
        if not isinstance(claims.get(field), str):
            raise TokenMalformed(f"human token missing field: {field}")
    try:
        expires_at = parse_utc(claims["exp"])
    except ValueError as exc:
        raise TokenMalformed("human token has a malformed expiry") from exc
    if now.astimezone(timezone.utc) >= expires_at:
        raise TokenExpired("human token has expired")
    return HumanClaims(user_id=claims["user_id"], jti=claims["jti"], issued_at=claims["iat"],
                       expires_at=claims["exp"])
