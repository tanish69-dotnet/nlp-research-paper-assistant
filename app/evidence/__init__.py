"""Evidence boundary: validation, selection, provider access (Person 2 contract)."""

from app.evidence.adapter import (
    adapt_retrieval_record,
    adapt_retrieval_response,
)
from app.evidence.retrieval_client import (
    DisabledProvider,
    HttpRetrievalProvider,
    MockRetrievalProvider,
    RetrievalRequest,
    RetrievalResponse,
    build_retrieval_provider,
    build_retrieval_provider_from_settings,
)
from app.evidence.validation import (
    referenced_evidence_ids,
    resolve_image_path,
    validate_evidence,
    validate_evidence_images,
    validate_evidence_size,
)

__all__ = [
    "DisabledProvider",
    "HttpRetrievalProvider",
    "MockRetrievalProvider",
    "RetrievalRequest",
    "RetrievalResponse",
    "adapt_retrieval_record",
    "adapt_retrieval_response",
    "build_retrieval_provider",
    "build_retrieval_provider_from_settings",
    "referenced_evidence_ids",
    "resolve_image_path",
    "validate_evidence",
    "validate_evidence_images",
    "validate_evidence_size",
]
