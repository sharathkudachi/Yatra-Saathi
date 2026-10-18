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


def register(app: FastAPI) -> None:
    @app.exception_handler(RefusalError)
    async def _refusal_handler(request: Request, exc: RefusalError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=refused(exc.code, exc.message))

    @app.exception_handler(TokenError)
    async def _token_handler(request: Request, exc: TokenError) -> JSONResponse:
        code = "TOKEN_INVALID"
        for error_type, mapped_code in _AUTH_CODE_FOR_ERROR.items():
            if isinstance(exc, error_type):
                code = mapped_code
                break
        return JSONResponse(status_code=401, content=refused(code, str(exc)))
