"""Evaluation case schema (EVALUATION.md §5, §8).

Cases carry frozen evidence so systems A/B/C/D can be compared on identical
inputs (EVALUATION.md §7, point 1). The offline fixture below provides the 7
``question_category`` slices the project promises.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.evidence import EvidenceBundle

Category = Literal["text", "table", "figure", "text_table", "text_figure", "table_figure", "multi_paper"]


class GoldAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    alternatives: list[str] = Field(default_factory=list)


class GoldClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    text: str
    verdict: Literal["SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONTRADICTED"] = "SUPPORTED"
    evidence_ids: list[str] = Field(default_factory=list)


class EvalCase(BaseModel):
    """One evaluation example — schema is intentionally lenient so SPIQA/QASper and
    the fixture-derived dataset share one path.
    """

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    category: Category
    evidence: EvidenceBundle
    papers: list[str] = Field(default_factory=list)
    gold_answer: GoldAnswer | None = None
    gold_evidence_ids: list[str] = Field(default_factory=list)
    gold_claims: list[GoldClaim] = Field(default_factory=list)
    answer_type: Literal["span", "numeric", "list", "free", "other"] = "free"
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvalDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    cases: list[EvalCase]
    manifest: dict[str, Any] = Field(default_factory=dict)
