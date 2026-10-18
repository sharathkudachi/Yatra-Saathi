"""POST /api/v1/auth/demo-login (section 12: demo login, allow-listed users only)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request

from src.api.deps import get_clock, get_conn, get_settings
from src.contracts.codes import RefusalError
from src.contracts.envelope import ok
from src.core import human_tokens
from src.core.clock import Clock
from src.core.config import Settings
from src.db.repositories import trips as trips_repo
from src.schemas.human import DemoLoginRequest

router = APIRouter()


@router.post("/auth/demo-login")
def demo_login(
    body: DemoLoginRequest, request: Request, settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock), conn: sqlite3.Connection = Depends(get_conn),
):
    if body.user_id not in settings.demo_login_user_ids:
        raise RefusalError("USER_NOT_ALLOWED", "this user is not allow-listed for demo login",
                            http_status=403)
    user = trips_repo.get_user(conn, body.user_id)
    if user is None:
        raise RefusalError("USER_NOT_FOUND", "no such user", http_status=404)
    if user.status != "active":
        raise RefusalError("USER_INACTIVE", "user is not active", http_status=403)
    if not settings.human_token_secret:
        raise RefusalError("TOKEN_INVALID", "human tokens are not configured", http_status=500)
    token = human_tokens.issue(settings.human_token_secret, body.user_id, now=clock.now())
    return ok({"token": token, "user_id": body.user_id, "display_name": user.display_name})
