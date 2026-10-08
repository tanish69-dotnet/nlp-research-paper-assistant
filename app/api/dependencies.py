"""FastAPI dependency providers.

Everything stateful is read from ``app.state`` (built once in ``create_app``);
no global mutable service state exists (ARCHITECTURE §6).
"""

from __future__ import annotations

from fastapi import Request

from app.config import Settings
from app.core.ids import new_request_id, sanitize_request_id
from app.models.routing import ModelRegistry


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_registry(request: Request) -> ModelRegistry:
    return request.app.state.registry


def get_request_id(request: Request) -> str:
    """Request id set by :class:`RequestContextMiddleware`.

    Falls back to the sanitized inbound header, then to a fresh id, so error
    handlers always have a correlation value even if middleware ordering
    changes.
    """
    state_id = getattr(request.state, "request_id", None)
    if isinstance(state_id, str) and state_id:
        return state_id
    return (
        sanitize_request_id(request.headers.get("X-Request-ID"))
        or new_request_id()
    )
