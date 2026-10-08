"""Query-analysis contracts (API_SPEC §3.3).

Produced by the Query Analyzer (Phase 2); defined now because
``ReasoningResponse.plan`` depends on them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Modality

QuestionType = Literal[
    "definition",
    "lookup",
    "numeric_lookup",
    "comparison",
    "cross_modal_comparison",
    "multi_paper_comparison",
    "causal_explanation",
    "trend_analysis",
    "aggregation_list",
    "ablation_analysis",
    "other",
]

PaperScope = Literal["single", "multi", "any"]


class SubQuestion(BaseModel):
    """One decomposed part of a multi-part question."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    modalities: list[Modality] = Field(default_factory=list)


class AgentTask(BaseModel):
    """A unit of work routed to exactly one agent.

    ``task`` is a free string rather than an enum: task vocabulary is owned by
    the planner (Phase 2) and must not be frozen prematurely.
    """

    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1)
    modality: Modality
    target_references: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class QueryPlan(BaseModel):
    """Structured output of the Query Analyzer."""

    model_config = ConfigDict(extra="forbid")

    question_type: QuestionType
    required_modalities: list[Modality] = Field(default_factory=list)
    tasks: list[AgentTask] = Field(default_factory=list)
    target_references: list[str] = Field(default_factory=list)
    requires_cross_modal: bool = False
    paper_scope: PaperScope = "any"
    paper_ids: list[str] = Field(default_factory=list)
    sub_questions: list[SubQuestion] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
