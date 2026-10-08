"""Request identifiers.

IDs are request-scoped values passed through context/ASGI state — never module
globals (ARCHITECTURE §6, "no global mutable service state").
"""

from __future__ import annotations

import re
import uuid

# Conservative charset: safe in headers, logs and JSON; bounded length.
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,63}$")


def new_request_id() -> str:
    """Generate a fresh opaque request id."""
    return uuid.uuid4().hex


def sanitize_request_id(value: str | None) -> str | None:
    """Return ``value`` if it is a legal request id, otherwise ``None``.

    Callers must fall back to :func:`new_request_id` — hostile or malformed
    inbound ids are never propagated into logs or responses.
    """
    if value is None:
        return None
    candidate = value.strip()
    if REQUEST_ID_RE.fullmatch(candidate):
        return candidate
    return None
