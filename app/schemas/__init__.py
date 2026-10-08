"""Pydantic contracts for the reasoning service (API_SPEC — source of truth).

Import contracts from this package, not from individual modules, so the team
has one stable surface to review.
"""

from app.schemas.analysis import AnalyzeResponse, PlannedTask, TaskStatus
from app.schemas.claims import AgentError, AgentRun, Claim, ClaimKind
from app.schemas.common import AgentStatus, EvidenceType, Modality, TokenUsage
from app.schemas.errors import CODE_TITLES, ErrorCode, ProblemDetail
from app.schemas.evidence import (
    EVIDENCE_ID_PATTERN,
    EvidenceBundle,
    EvidenceItem,
    ImageRef,
    PaperRef,
    RetrievalMeta,
    TableData,
)
from app.schemas.health import (
    HealthResponse,
    HealthStatus,
    ModelsResponse,
    ProviderHealth,
    RoleInfo,
)
from app.schemas.query import AgentTask, PaperScope, QueryPlan, QuestionType, SubQuestion
from app.schemas.reasoning import (
    Citation,
    ReasoningOptions,
    ReasoningRequest,
    ReasoningResponse,
    ResponseMetadata,
    ResponseStatus,
)
from app.schemas.verification import (
    ClaimVerification,
    Verdict,
    VerificationResult,
    VerificationStatus,
)

__all__ = [
    "CODE_TITLES",
    "EVIDENCE_ID_PATTERN",
    "AgentError",
    "AgentRun",
    "AgentStatus",
    "AgentTask",
    "AnalyzeResponse",
    "Claim",
    "ClaimKind",
    "ClaimVerification",
    "Citation",
    "ErrorCode",
    "EvidenceBundle",
    "EvidenceItem",
    "EvidenceType",
    "HealthResponse",
    "HealthStatus",
    "ImageRef",
    "Modality",
    "ModelsResponse",
    "PaperRef",
    "PaperScope",
    "PlannedTask",
    "ProblemDetail",
    "ProviderHealth",
    "QueryPlan",
    "QuestionType",
    "ReasoningOptions",
    "ReasoningRequest",
    "ReasoningResponse",
    "ResponseMetadata",
    "ResponseStatus",
    "RetrievalMeta",
    "RoleInfo",
    "SubQuestion",
    "TableData",
    "TaskStatus",
    "TokenUsage",
    "Verdict",
    "VerificationResult",
    "VerificationStatus",
]
