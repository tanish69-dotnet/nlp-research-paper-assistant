"""ASGI middleware: request-id propagation and request body size limits.

Implemented as pure ASGI middleware (no ``BaseHTTPMiddleware``) so behaviour
does not depend on Starlette's higher-level helpers.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable, Iterable, MutableMapping
from typing import Any

import structlog

from app.core.ids import new_request_id, sanitize_request_id
from app.schemas.errors import ErrorCode, ProblemDetail

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]

logger = structlog.get_logger(__name__)

REQUEST_ID_HEADER = b"x-request-id"


def _headers(scope: Scope) -> dict[str, str]:
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }


def _request_id_from_scope(scope: Scope) -> str:
    state = scope.get("state")
    if isinstance(state, dict):
        value = state.get("request_id")
        if isinstance(value, str) and value:
            return value
    return sanitize_request_id(_headers(scope).get("x-request-id")) or new_request_id()


async def _send_problem(
    send: Send,
    *,
    status: int,
    code: ErrorCode,
    detail: str,
    request_id: str,
) -> None:
    problem = ProblemDetail.build(
        code=code, status=status, detail=detail, request_id=request_id
    )
    body = json.dumps(problem.model_dump(mode="json")).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("latin-1")),
                (REQUEST_ID_HEADER, request_id.encode("latin-1")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RequestContextMiddleware:
    """Assigns, propagates and logs a request id for every HTTP request.

    Accepts an inbound ``X-Request-ID`` only if it matches the safe pattern
    (SECURITY.md §7); otherwise a fresh UUID is generated. The id is stored in
    ASGI scope state (request-scoped, never a module global) and echoed in the
    response header.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = _headers(scope)
        request_id = sanitize_request_id(headers.get("x-request-id")) or new_request_id()
        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id

        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = int(message["status"])
                existing = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != REQUEST_ID_HEADER
                ]
                existing.append((REQUEST_ID_HEADER, request_id.encode("latin-1")))
                message = {**message, "headers": existing}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "request_completed",
                method=scope.get("method"),
                path=scope.get("path"),
                status=status_holder["status"],
                duration_ms=duration_ms,
                component="http",
            )
            structlog.contextvars.clear_contextvars()


class BodySizeLimitMiddleware:
    """Reject oversized request bodies with the documented ``413`` shape.

    Checks the ``Content-Length`` header before the request is parsed. Bodies
    without a content length are still bounded later by evidence size limits
    (``MAX_EVIDENCE_CHARS`` etc.).
    """

    def __init__(self, app: Any, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = _headers(scope).get("content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                declared = -1
            if declared > self.max_bytes:
                request_id = _request_id_from_scope(scope)
                logger.warning(
                    "request_rejected",
                    component="http",
                    error_code=ErrorCode.PAYLOAD_TOO_LARGE,
                    declared_bytes=declared,
                )
                await _send_problem(
                    send,
                    status=413,
                    code=ErrorCode.PAYLOAD_TOO_LARGE,
                    detail=(
                        f"request body of {declared} bytes exceeds "
                        f"MAX_REQUEST_BYTES={self.max_bytes}"
                    ),
                    request_id=request_id,
                )
                return

        await self.app(scope, receive, send)


def iter_middleware_headers(headers: Iterable[tuple[bytes, bytes]]) -> dict[str, str]:
    """Small helper for tests/tools: decode an ASGI header list."""
    return {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in headers}
