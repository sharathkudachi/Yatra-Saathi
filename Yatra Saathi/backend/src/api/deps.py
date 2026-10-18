"""FastAPI dependencies: DB connection per request, settings, and auth."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Iterator, Optional

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.contracts.codes import RefusalError
from src.core import agent_tokens, human_tokens
from src.core.clock import Clock, SystemClock
from src.core.config import Settings
from src.db.connection import connect
from src.db.repositories import sessions as sessions_repo
from src.db.repositories import trips as trips_repo


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_clock(request: Request) -> Clock:
    return getattr(request.app.state, "clock", None) or SystemClock()


def get_conn(settings: Settings = Depends(get_settings)) -> Iterator[sqlite3.Connection]:
    # FastAPI runs this dependency and the endpoint on different threadpool threads, so the
    # per-request connection must be usable across threads. It is never shared between
    # requests, so its use is still strictly sequential.
    conn = connect(settings, check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()


# HTTPBearer reads the same `Authorization: Bearer <token>` header, but declares it as a
# security scheme so Swagger's Authorize button sends it (Swagger UI drops plain header
# parameters named Authorization). auto_error=False keeps our own refusal envelope.
_human_bearer = HTTPBearer(auto_error=False, scheme_name="HumanToken")
_agent_bearer = HTTPBearer(auto_error=False, scheme_name="AgentToken")


def _bearer_token(credentials: Optional[HTTPAuthorizationCredentials]) -> str:
    if credentials is None or credentials.scheme != "Bearer" or not credentials.credentials:
        raise RefusalError("TOKEN_MISSING", "missing bearer token", http_status=401)
    return credentials.credentials


@dataclass(frozen=True)
class CurrentUser:
    user_id: str


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_human_bearer),
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock), conn: sqlite3.Connection = Depends(get_conn),
) -> CurrentUser:
    token = _bearer_token(credentials)
    if not settings.human_token_secret:
        raise RefusalError("TOKEN_INVALID", "human tokens are not configured", http_status=401)
    claims = human_tokens.verify(settings.human_token_secret, token, now=clock.now())
    user = trips_repo.get_user(conn, claims.user_id)
    if user is None:
        raise RefusalError("USER_NOT_FOUND", "token user does not exist", http_status=401)
    if user.status != "active":
        raise RefusalError("USER_INACTIVE", "user is not active", http_status=401)
    return CurrentUser(user_id=claims.user_id)


@dataclass(frozen=True)
class CurrentAgent:
    session_id: str
    run_id: str


def get_current_agent(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_agent_bearer),
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
) -> CurrentAgent:
    token = _bearer_token(credentials)
    if not settings.agent_token_secret:
        raise RefusalError("TOKEN_INVALID", "agent tokens are not configured", http_status=401)
    claims = agent_tokens.verify(settings.agent_token_secret, token, now=clock.now())
    return CurrentAgent(session_id=claims.session_id, run_id=claims.run_id)


def require_agent_session_match(session_id: str, agent: CurrentAgent) -> None:
    if agent.session_id != session_id:
        raise RefusalError("SESSION_ACCESS_DENIED",
                            "this agent token is not scoped to this session", http_status=403)


def require_session_owner(conn: sqlite3.Connection, session_id: str, user: CurrentUser) -> sessions_repo.Session:
    session = sessions_repo.get(conn, session_id)
    if session is None:
        raise RefusalError("SESSION_ACCESS_DENIED", "no such session", http_status=404)
    if session.user_id != user.user_id:
        raise RefusalError("SESSION_ACCESS_DENIED", "this user does not own the session", http_status=403)
    return session
