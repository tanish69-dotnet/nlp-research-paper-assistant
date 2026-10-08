"""Error contracts (API_SPEC §6).

``ProblemDetail`` is the only error shape any client will ever see. Stack
traces, provider payloads and prompt contents never appear here.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ErrorCode(StrEnum):
    """Stable machine-readable error codes.

    ``NOT_FOUND`` and ``MALFORMED_MODEL_OUTPUT`` were added during Phase 1 to
    cover standard routing failures and ARCHITECTURE §4.7's malformed-model
    failure path (documented additive change, see API_SPEC §6).
    """

    INVALID_REQUEST = "INVALID_REQUEST"
    EVIDENCE_EMPTY = "EVIDENCE_EMPTY"
    EVIDENCE_INVALID = "EVIDENCE_INVALID"
    IMAGE_PATH_FORBIDDEN = "IMAGE_PATH_FORBIDDEN"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    PROMPT_TOO_LONG = "PROMPT_TOO_LONG"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MALFORMED_MODEL_OUTPUT = "MALFORMED_MODEL_OUTPUT"
    NOT_FOUND = "NOT_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"


#: Human-readable titles used when building a ``ProblemDetail`` outside of a
#: typed exception (e.g. mapping a Starlette ``HTTPException``).
CODE_TITLES: dict[ErrorCode, str] = {
    ErrorCode.INVALID_REQUEST: "Invalid request",
    ErrorCode.EVIDENCE_EMPTY: "Empty evidence bundle",
    ErrorCode.EVIDENCE_INVALID: "Invalid evidence bundle",
    ErrorCode.IMAGE_PATH_FORBIDDEN: "Image path forbidden",
    ErrorCode.PAYLOAD_TOO_LARGE: "Payload too large",
    ErrorCode.PROMPT_TOO_LONG: "Prompt too long",
    ErrorCode.MODEL_UNAVAILABLE: "Model unavailable",
    ErrorCode.MODEL_TIMEOUT: "Model timeout",
    ErrorCode.MALFORMED_MODEL_OUTPUT: "Malformed model output",
    ErrorCode.NOT_FOUND: "Not found",
    ErrorCode.INTERNAL_ERROR: "Internal error",
}


class ProblemDetail(BaseModel):
    """RFC 9457-style error body with a stable machine code (API_SPEC §6)."""

    model_config = ConfigDict(extra="forbid")

    type: str
    title: str
    status: int
    detail: str
    code: ErrorCode
    request_id: str
    retryable: bool = False

    @classmethod
    def build(
        cls,
        *,
        code: ErrorCode,
        status: int,
        detail: str,
        request_id: str,
        retryable: bool = False,
        title: str | None = None,
    ) -> "ProblemDetail":
        return cls(
            type=f"https://researchlens.local/errors/{code}",
            title=title or CODE_TITLES[code],
            status=status,
            detail=detail,
            code=code,
            request_id=request_id,
            retryable=retryable,
        )
