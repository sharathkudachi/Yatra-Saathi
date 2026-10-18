"""Maps domain/token errors to the approved response envelope (section 12)."""
from __future__ import annotations

import logging
import re
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.contracts.codes import RefusalError
from src.contracts.envelope import refused
from src.core._signing import TokenError, TokenExpired, TokenMalformed, TokenSignatureInvalid, TokenWrongRole
from src.core.config import cors_origins_from_env

logger = logging.getLogger("yatra.api.errors")

_AUTH_CODE_FOR_ERROR = {
    TokenExpired: "TOKEN_EXPIRED",
    TokenWrongRole: "TOKEN_WRONG_ROLE",
    TokenSignatureInvalid: "TOKEN_INVALID",
    TokenMalformed: "TOKEN_INVALID",
}

_VERCEL_REGEX = re.compile(r"^https:\/\/yatra-saathi-frontend(\.vercel\.app|-([a-zA-Z0-9_-]+-)?sharathkudachi\.vercel\.app)$")
_DEV_REGEX = re.compile(r"^http:\/\/(localhost|127\.0\.0\.1)(:[0-9]+)?$")


def is_trusted_origin(origin: str | None, request: Request | None = None) -> bool:
    """Verifies that an origin is an authorized frontend origin."""
    if not origin:
        return False
    origin_clean = origin.strip().rstrip("/")
    if _VERCEL_REGEX.match(origin_clean) or _DEV_REGEX.match(origin_clean):
        return True
    try:
        configured = request.app.state.settings.cors_allow_origins if request and hasattr(request.app.state, "settings") else None
    except Exception:
        configured = None
    if configured is None:
        configured = cors_origins_from_env()
    for allowed in configured:
        if allowed == "*" or allowed.rstrip("/") == origin_clean:
            return True
    return False


def _cors_headers(request: Request) -> dict[str, str]:
    """Generates narrow, secure CORS headers for approved frontend origins only."""
    origin = request.headers.get("origin")
    if not origin or not is_trusted_origin(origin, request):
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
        "Access-Control-Allow-Headers": "Authorization, Content-Type, Accept, X-Request-ID, Origin",
    }


def register(app: FastAPI) -> None:
    @app.exception_handler(RefusalError)
    async def _refusal_handler(request: Request, exc: RefusalError) -> JSONResponse:
        headers = _cors_headers(request)
        return JSONResponse(
            status_code=exc.http_status,
            content=refused(exc.code, exc.message),
            headers=headers if headers else None,
        )

    @app.exception_handler(TokenError)
    async def _token_handler(request: Request, exc: TokenError) -> JSONResponse:
        code = "TOKEN_INVALID"
        for error_type, mapped_code in _AUTH_CODE_FOR_ERROR.items():
            if isinstance(exc, error_type):
                code = mapped_code
                break
        headers = _cors_headers(request)
        return JSONResponse(
            status_code=401,
            content=refused(code, str(exc)),
            headers=headers if headers else None,
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(f"Unhandled exception on {request.method} {request.url}")
        headers = _cors_headers(request)
        # Protect internal stack traces, database schemas, and SQL queries from being leaked
        return JSONResponse(
            status_code=500,
            content=refused("INTERNAL_ERROR", "An internal server error occurred. Please try again later."),
            headers=headers if headers else None,
        )
