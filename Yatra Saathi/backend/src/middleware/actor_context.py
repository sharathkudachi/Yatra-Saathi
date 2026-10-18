"""Determines the audit actor from the route, never from a caller's claim
(section 10): human routes -> user + actor_user_id; internal agent routes ->
agent + agent_run_id; anything else -> system. This middleware only tags the
request path; the actual actor/actor_user_id/agent_run_id used in an audit
event always comes from the verified token in `app/api/deps.py`, never from
this header-level classification alone.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

HUMAN_PREFIX = "/api/v1"
AGENT_PREFIX = "/internal/agent/v1"


class ActorContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith(AGENT_PREFIX):
            request.state.route_kind = "agent"
        elif path.startswith(HUMAN_PREFIX):
            request.state.route_kind = "human"
        else:
            request.state.route_kind = "system"
        return await call_next(request)
