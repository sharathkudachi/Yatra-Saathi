"""Maps domain/token errors to the approved response envelope (section 12)."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.contracts.codes import RefusalError
from src.contracts.envelope import refused
from src.core._signing import TokenError, TokenExpired, TokenMalformed, TokenSignatureInvalid, TokenWrongRole

_AUTH_CODE_FOR_ERROR = {
    TokenExpired: "TOKEN_EXPIRED",
    TokenWrongRole: "TOKEN_WRONG_ROLE",
    TokenSignatureInvalid: "TOKEN_INVALID",
    TokenMalformed: "TOKEN_INVALID",
}


def _cors_headers(request: Request) -> dict[str, str]:
    origin = request.headers.get("origin")
    if not origin:
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Allow-Methods": "*",
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
        headers = _cors_headers(request)
        return JSONResponse(
            status_code=500,
            content=refused("INTERNAL_ERROR", str(exc) or "An internal server error occurred."),
            headers=headers if headers else None,
        )
