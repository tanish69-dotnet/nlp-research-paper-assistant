"""Expected-failure exceptions.

Every error maps to a stable :class:`ErrorCode` (API_SPEC §6) and an HTTP
status. Routes translate these into ``ProblemDetail``; internal logs keep the
diagnostic detail, clients never see stack traces (SECURITY.md §6).
"""

from __future__ import annotations

from app.schemas.errors import ErrorCode


class ReasoningError(Exception):
    """Base class for all anticipated, non-bug failures."""

    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    status_code: int = 500
    retryable: bool = False
    title: str = "Internal error"

    def __init__(self, detail: str, *, retryable: bool | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if retryable is not None:
            self.retryable = retryable


class InvalidRequestError(ReasoningError):
    code = ErrorCode.INVALID_REQUEST
    status_code = 400
    title = "Invalid request"


class EvidenceEmptyError(ReasoningError):
    code = ErrorCode.EVIDENCE_EMPTY
    status_code = 400
    title = "Empty evidence bundle"


class EvidenceInvalidError(ReasoningError):
    code = ErrorCode.EVIDENCE_INVALID
    status_code = 400
    title = "Invalid evidence bundle"


class ImagePathForbiddenError(ReasoningError):
    code = ErrorCode.IMAGE_PATH_FORBIDDEN
    status_code = 400
    title = "Image path forbidden"


class PayloadTooLargeError(ReasoningError):
    code = ErrorCode.PAYLOAD_TOO_LARGE
    status_code = 413
    title = "Payload too large"


class PromptTooLongError(ReasoningError):
    code = ErrorCode.PROMPT_TOO_LONG
    status_code = 422
    title = "Prompt too long"


class ModelUnavailableError(ReasoningError):
    code = ErrorCode.MODEL_UNAVAILABLE
    status_code = 503
    retryable = True
    title = "Model unavailable"


class ModelTimeoutError(ReasoningError):
    code = ErrorCode.MODEL_TIMEOUT
    status_code = 504
    retryable = True
    title = "Model timeout"


class MalformedModelOutputError(ReasoningError):
    code = ErrorCode.MALFORMED_MODEL_OUTPUT
    status_code = 502
    title = "Malformed model output"


class NotFoundError(ReasoningError):
    code = ErrorCode.NOT_FOUND
    status_code = 404
    title = "Not found"
