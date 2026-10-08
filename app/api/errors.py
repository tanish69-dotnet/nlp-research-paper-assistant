"""Exception handlers translating failures into ``ProblemDetail`` (API_SPEC §6).

Clients receive stable codes and safe messages; stacks and provider payloads
stay in server logs (SECURITY.md §6/§7).
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from app.api.dependencies import get_request_id
from app.core.errors import ReasoningError
from app.schemas.errors import CODE_TITLES, ErrorCode, ProblemDetail

logger = structlog.get_logger(__name__)

_MAX_REPORTED_VALIDATION_ERRORS = 20


def _response(
    *,
    status: int,
    code: ErrorCode,
    detail: str,
    request_id: str,
    retryable: bool = False,
    title: str | None = None,
) -> JSONResponse:
    problem = ProblemDetail.build(
        code=code,
        status=status,
        detail=detail,
        request_id=request_id,
        retryable=retryable,
        title=title,
    )
    return JSONResponse(status_code=status, content=problem.model_dump(mode="json"))


def _safe_validation_detail(exc: RequestValidationError) -> str:
    """Field-level summary without echoing full input values."""
    entries = []
    for error in exc.errors()[:_MAX_REPORTED_VALIDATION_ERRORS]:
        location = ".".join(str(part) for part in error.get("loc", ()))
        entries.append(
            {"loc": location, "msg": error.get("msg", ""), "type": error.get("type", "")}
        )
    return "request validation failed: " + json.dumps(entries, ensure_ascii=False)


def install_exception_handlers(app: FastAPI) -> None:
    """Register the documented error model on ``app``."""

    @app.exception_handler(ReasoningError)
    async def _reasoning_error(request: Request, exc: ReasoningError) -> JSONResponse:
        logger.warning(
            "request_failed",
            component="api",
            error_code=exc.code,
            detail=exc.detail,
        )
        return _response(
            status=exc.status_code,
            code=exc.code,
            detail=exc.detail,
            request_id=get_request_id(request),
            retryable=exc.retryable,
            title=exc.title,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.warning(
            "request_failed",
            component="api",
            error_code=ErrorCode.INVALID_REQUEST,
            detail="schema validation failed",
        )
        return _response(
            status=400,
            code=ErrorCode.INVALID_REQUEST,
            detail=_safe_validation_detail(exc),
            request_id=get_request_id(request),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            code = ErrorCode.NOT_FOUND
        elif 400 <= exc.status_code < 500:
            code = ErrorCode.INVALID_REQUEST
        else:
            code = ErrorCode.INTERNAL_ERROR
        return _response(
            status=exc.status_code,
            code=code,
            detail=str(exc.detail),
            request_id=get_request_id(request),
            title=CODE_TITLES[code],
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Stack trace stays in the log; the client sees a stable code only.
        logger.error(
            "unhandled_exception",
            component="api",
            error_type=type(exc).__name__,
            exc_info=True,
        )
        return _response(
            status=500,
            code=ErrorCode.INTERNAL_ERROR,
            detail="internal server error",
            request_id=get_request_id(request),
        )
