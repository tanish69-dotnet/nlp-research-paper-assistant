"""Structured logging (PRD FR-24, SECURITY.md §7).

JSON by default so events are machine-readable from day one. A scrubbing
processor enforces the "never log secrets / paper bodies / image payloads"
rule centrally, regardless of what callers pass.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.config import Settings

#: Keys whose values are always replaced with ``[REDACTED]``.
SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "b64",
        "base64",
        "image",
        "images",
        "image_b64",
        "password",
        "secret",
        "token",
        "openai_compat_api_key",
    }
)

#: Long strings (evidence bodies, prompts) are truncated, not logged in full.
MAX_LOG_VALUE_CHARS = 500

_REDACTED = "[REDACTED]"


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return (
        lowered in SENSITIVE_KEYS
        or lowered.endswith("_api_key")
        or lowered.endswith("_token")
        or lowered.endswith("_secret")
        or lowered.endswith("_b64")
    )


def scrub(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Redact secrets and truncate oversized values before rendering.

    Runs last in the processor chain so no renderer can bypass it.
    """
    for key in list(event_dict):
        value = event_dict[key]
        if _is_sensitive(str(key)):
            event_dict[key] = _REDACTED
        elif isinstance(value, str) and len(value) > MAX_LOG_VALUE_CHARS:
            event_dict[key] = f"{value[:MAX_LOG_VALUE_CHARS]}…[{len(value)} chars]"
        elif isinstance(value, dict):
            event_dict[key] = {
                sub: (
                    _REDACTED
                    if _is_sensitive(str(sub))
                    else (
                        f"{sub_val[:MAX_LOG_VALUE_CHARS]}…"
                        if isinstance(sub_val, str) and len(sub_val) > MAX_LOG_VALUE_CHARS
                        else sub_val
                    )
                )
                for sub, sub_val in value.items()
            }
    return event_dict


def setup_logging(settings: Settings) -> None:
    """Configure structlog for the whole process (idempotent)."""
    level = getattr(logging, settings.log_level, logging.INFO)

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        scrub,
    ]
    if settings.log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
        force=True,
    )
