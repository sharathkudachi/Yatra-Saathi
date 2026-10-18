"""Settings loaded only from environment variables. No hard-coded paths."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Mapping, Optional

from .errors import ConfigError

# Schema version the application requires (PRAGMA user_version of the working copy).
REQUIRED_SCHEMA_VERSION = 7

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

DEFAULT_CORS_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


def cors_origins_from_env(env: Optional[Mapping[str, str]] = None) -> tuple[str, ...]:
    """CORS_ALLOW_ORIGINS: comma-separated origins; unset -> the Vite dev server; empty -> none."""
    env = os.environ if env is None else env
    raw = env.get("CORS_ALLOW_ORIGINS")
    if raw is None:
        return DEFAULT_CORS_ORIGINS
    return tuple(o.strip().rstrip("/") for o in raw.split(",") if o.strip())


def _int(env: Mapping[str, str], name: str, default: int, lo: int, hi: int) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if not lo <= value <= hi:
        raise ConfigError(f"{name} must be between {lo} and {hi}")
    return value


@dataclass(frozen=True)
class Settings:
    db_path: Optional[str]
    database_url: Optional[str]
    original_db_path: Optional[str]
    original_db_sha256: Optional[str]
    tax_rate_bp: int
    replan_limit: int
    confirmation_ttl_seconds: int
    agent_state_max_bytes: int
    busy_timeout_ms: int
    booking_mode: str
    # Milestone 3: HTTP layer secrets/config. Backend-only; never given to the agent process.
    human_token_secret: Optional[str]
    agent_token_secret: Optional[str]
    agent_service_key: Optional[str]
    agent_service_url: Optional[str]
    demo_login_user_ids: tuple[str, ...]
    # Browser origins allowed to call the human API (the frontend dev server by default).
    cors_allow_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    # Web Push (optional): without keys, notifications are still recorded (in-app) but not pushed.
    vapid_public_key: Optional[str] = None
    vapid_private_key: Optional[str] = None
    vapid_subject: str = "mailto:notifications@yatra.example"
    # Background loop: flight departure/landing notifications and releasing expired approvals.
    notify_scheduler: bool = False

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Settings":
        env = os.environ if env is None else env
        booking_mode = env.get("BOOKING_MODE", "mock")
        if booking_mode != "mock":
            raise ConfigError("BOOKING_MODE must be 'mock' for the MVP")
        sha = env.get("APS_DB_ORIGINAL_SHA256") or None
        if sha is not None and not _SHA256_RE.match(sha):
            raise ConfigError("APS_DB_ORIGINAL_SHA256 must be 64 lowercase hex characters")
        demo_ids = tuple(u for u in (env.get("DEMO_LOGIN_USER_IDS") or "").split(",") if u)
        raw_db_url = env.get("DATABASE_URL") or None
        if raw_db_url and raw_db_url.startswith("postgres://"):
            raw_db_url = "postgresql://" + raw_db_url[len("postgres://"):]
        return cls(
            db_path=env.get("APS_DB_PATH") or None,
            database_url=raw_db_url,
            original_db_path=env.get("APS_DB_ORIGINAL_PATH") or None,
            original_db_sha256=sha,
            tax_rate_bp=_int(env, "TAX_RATE_BP", 1200, 0, 10000),
            replan_limit=_int(env, "REPLAN_LIMIT", 3, 0, 20),
            confirmation_ttl_seconds=_int(env, "CONFIRMATION_TTL_SECONDS", 900, 60, 3600),
            agent_state_max_bytes=_int(env, "AGENT_STATE_MAX_BYTES", 1048576, 1, 1048576),
            busy_timeout_ms=_int(env, "DB_BUSY_TIMEOUT_MS", 5000, 0, 60000),
            booking_mode=booking_mode,
            human_token_secret=env.get("HUMAN_TOKEN_SECRET") or None,
            agent_token_secret=env.get("AGENT_TOKEN_SECRET") or None,
            agent_service_key=env.get("AGENT_SERVICE_KEY") or None,
            agent_service_url=env.get("AGENT_SERVICE_URL") or None,
            demo_login_user_ids=demo_ids,
            cors_allow_origins=cors_origins_from_env(env),
            vapid_public_key=env.get("VAPID_PUBLIC_KEY") or None,
            vapid_private_key=env.get("VAPID_PRIVATE_KEY") or None,
            vapid_subject=env.get("VAPID_SUBJECT") or "mailto:notifications@yatra.example",
            notify_scheduler=(env.get("NOTIFY_SCHEDULER") or "").lower() in ("1", "true", "yes"),
        )

    @property
    def is_postgres(self) -> bool:
        return bool(self.database_url and (
            self.database_url.startswith("postgresql://") or self.database_url.startswith("postgres://")
        ))

    def require_db_path(self) -> str:
        if self.database_url:
            return self.database_url
        if not self.db_path:
            raise ConfigError("Neither DATABASE_URL nor APS_DB_PATH is set")
        return self.db_path

    def require_original(self) -> tuple[str, str]:
        if not self.original_db_path or not self.original_db_sha256:
            raise ConfigError("APS_DB_ORIGINAL_PATH and APS_DB_ORIGINAL_SHA256 must both be set")
        return self.original_db_path, self.original_db_sha256
