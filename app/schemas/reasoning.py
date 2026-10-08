"""Reasoning request/response contracts (API_SPEC §3.4, §5)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.claims import AgentRun, Claim
from app.schemas.common import EvidenceType
from app.schemas.evidence import EvidenceBundle
from app.schemas.query import QueryPlan
from app.schemas.verification import VerificationResult

ResponseStatus = Literal["ok", "partial", "error"]


class Citation(BaseModel):
    """A citation resolved **by the system** from the input evidence bundle.

    Model-authored citation objects are never trusted (PRD FR-14); every row
    here corresponds to an ``evidence_id`` that arrived with the request.
    """

    model_config = ConfigDict(extra="forbid")

    citation_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    paper_id: str = Field(min_length=1)
    page: int | None = None
    type: EvidenceType
    reference: str | None = None
    title: str | None = None


class ReasoningOptions(BaseModel):
    """Per-request pipeline options (all optional, safe defaults)."""

    model_config = ConfigDict(extra="forbid")

    include_agent_outputs: bool = True
    include_plan: bool = True
    include_unverified_claims: bool = False
    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    max_evidence_items: int = Field(default=40, ge=1)
    timeout_ms: int = Field(default=120_000, ge=1_000)
    language: str = "en"


class ReasoningRequest(BaseModel):
    """Input to ``POST /api/v1/reason``.

    An empty ``evidence.evidence`` list is accepted by the schema so the route
    can answer with the documented ``400 EVIDENCE_EMPTY`` instead of a 422
    validation failure (API_SPEC §6).
    """

    model_config = ConfigDict(extra="forbid")

    request_id: str | None = None
    query: str = Field(min_length=1)
    evidence: EvidenceBundle
    options: ReasoningOptions = Field(default_factory=ReasoningOptions)


class ResponseMetadata(BaseModel):
    """Observability block attached to every response."""

    model_config = ConfigDict(extra="forbid")

    models: dict[str, str] = Field(default_factory=dict)
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    timings_ms: dict[str, int] = Field(default_factory=dict)
    agent_status: dict[str, str] = Field(default_factory=dict)
    degraded: list[str] = Field(default_factory=list)
    dropped_evidence_ids: list[str] = Field(default_factory=list)
    evidence_used: list[str] = Field(default_factory=list)
    evidence_total: int = Field(default=0, ge=0)
    pipeline_version: str = "0.1.0"
    cache_hit: bool = False


class ReasoningResponse(BaseModel):
    """Output of ``POST /api/v1/reason`` (API_SPEC §5 guarantees apply)."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    status: ResponseStatus
    answer: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    citations: list[Citation] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    verification: VerificationResult
    agent_outputs: list[AgentRun] = Field(default_factory=list)
    plan: QueryPlan | None = None
    metadata: ResponseMetadata = Field(default_factory=ResponseMetadata)
