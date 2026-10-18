"""Minimal structured request logging (stdlib logging only)."""
from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("tech4ce.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        started = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - started) * 1000
        request_id = getattr(request.state, "request_id", "-")
        logger.info("%s %s -> %s (%.1fms) request_id=%s", request.method, request.url.path,
                    response.status_code, duration_ms, request_id)
        return response
