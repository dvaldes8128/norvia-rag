"""Consistent API error envelope (Q2.4)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorBody(BaseModel):
    error: str
    detail: Any = None
    code: str = Field(description="Stable machine-readable error code")


def _envelope(status_code: int, *, error: str, code: str, detail: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorBody(error=error, detail=detail, code=code).model_dump(),
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = {
            400: "bad_request",
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            413: "payload_too_large",
            415: "unsupported_media_type",
            422: "validation_error",
        }.get(exc.status_code, "http_error")
        detail = exc.detail
        error = str(detail)
        if isinstance(detail, dict):
            code = str(detail.get("code") or code)
            error = str(detail.get("message") or detail.get("error") or error)
        return _envelope(
            exc.status_code,
            error=error,
            code=code,
            detail=detail,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _envelope(
            422,
            error="Validation failed",
            code="validation_error",
            detail=exc.errors(),
        )
