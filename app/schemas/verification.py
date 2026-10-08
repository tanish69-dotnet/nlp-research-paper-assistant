"""Verification contracts: per-claim verdicts and aggregate status (API_SPEC §3.4)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Verdict = Literal["SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONTRADICTED"]

VerificationStatus = Literal[
    "supported", "partially_supported", "unsupported", "mixed", "unverified"
]


class ClaimVerification(BaseModel):
    """Judge/verifier verdict for a single claim.

    The verifier can only *assess* evidence — it can never add citations or
    invent evidence (PRD FR-13).
    """

    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1)
    verdict: Verdict
    verifier: str  # "deterministic" | "deterministic+judge" | "judge"
    rationale: str = ""
    evidence_ids_support: list[str] = Field(default_factory=list)
    evidence_ids_contradict: list[str] = Field(default_factory=list)
    missing_aspects: list[str] = Field(default_factory=list)


class VerificationResult(BaseModel):
    """Aggregate verification state returned with every reasoned answer."""

    model_config = ConfigDict(extra="forbid")

    status: VerificationStatus
    supported: int = Field(default=0, ge=0)
    partially_supported: int = Field(default=0, ge=0)
    unsupported: int = Field(default=0, ge=0)
    contradicted: int = Field(default=0, ge=0)
    unsupported_claims: list[str] = Field(default_factory=list)
    contradicted_claims: list[str] = Field(default_factory=list)
    needs_more_evidence: bool = False
