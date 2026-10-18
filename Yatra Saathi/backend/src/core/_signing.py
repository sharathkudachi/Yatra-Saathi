"""Shared HMAC token encode/decode helpers for human_tokens.py and agent_tokens.py.

Format: base64url(canonical_json(claims)) + "." + hex(HMAC-SHA256(secret, payload_b64)).
Stdlib only (hmac/hashlib/base64), no JWT dependency, per the approved decision.
"""
from __future__ import annotations

import base64
import hmac
import json
from hashlib import sha256
from typing import Any

from src.core.errors import Tech4ceError
from src.core.hashing import canonical_json


class TokenError(Tech4ceError):
    """Base class for token problems. Subclasses map 1:1 to auth refusal codes."""


class TokenMalformed(TokenError):
    pass


class TokenSignatureInvalid(TokenError):
    pass


class TokenExpired(TokenError):
    pass


class TokenWrongRole(TokenError):
    pass


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def sign(secret: str, claims: dict[str, Any]) -> str:
    payload_b64 = _b64encode(canonical_json(claims).encode("utf-8"))
    signature = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def unsign(secret: str, token: str) -> dict[str, Any]:
    if not token or "." not in token:
        raise TokenMalformed("token is malformed")
    payload_b64, _, signature = token.partition(".")
    expected = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise TokenSignatureInvalid("token signature is invalid")
    try:
        claims = json.loads(_b64decode(payload_b64))
    except (ValueError, UnicodeDecodeError) as exc:
        raise TokenMalformed("token payload is not valid JSON") from exc
    if not isinstance(claims, dict):
        raise TokenMalformed("token payload must be a JSON object")
    return claims
