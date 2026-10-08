"""Claim and agent-run contracts (API_SPEC §3.4, §3.6).

Every claim carries the ``evidence_id`` set it was derived from; citations are
resolved from those IDs by code, never from model text (PRD FR-14).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import AgentStatus, TokenUsage
from app.schemas.errors import ErrorCode
from app.schemas.verification import ClaimVerification

ClaimKind = Literal[
    "author_claim",
    "inference",
    "limitation",
    "methodology",
    "definition",
    "table_observation",
    "table_comparison",
    "table_interpretation",
    "figure_observation",
    "cross_modal_link",
    "comparison_row",
]


class Claim(BaseModel):
    """An atomic, evidence-linked statement produced by an agent."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1)
    agent: str = Field(min_length=1)  # e.g. "table_reasoner"
    kind: ClaimKind
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    verification: ClaimVerification | None = None


class AgentError(BaseModel):
    """Structured failure record attached to a degraded agent run."""

    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str
    retriable: bool = False
    attempts: int = 1


class AgentRun(BaseModel):
    """Observability record for one agent invocation (returned in metadata)."""

    model_config = ConfigDict(extra="forbid")

    agent: str
    model: str
    provider: str
    prompt_version: str = "unversioned"
    status: AgentStatus
    latency_ms: int = Field(ge=0)
    evidence_ids_used: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)  # claim_ids
    usage: TokenUsage = Field(default_factory=TokenUsage)
    error: AgentError | None = None
