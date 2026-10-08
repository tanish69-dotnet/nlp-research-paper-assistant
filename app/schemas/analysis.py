"""Phase 2 analysis contracts: planned tasks and the /analyze response."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.claims import AgentRun, Claim
from app.schemas.common import Modality
from app.schemas.query import QueryPlan
from app.schemas.reasoning import ResponseMetadata, ResponseStatus

TaskStatus = Literal["executable", "deferred", "skipped"]


class PlannedTask(BaseModel):
    """One unit of work from the QueryPlan, routed by the planner.

    ``status="executable"`` means an implemented agent can run it now;
    ``"deferred"`` means the modality's agent does not exist yet (Phase 3+);
    ``"skipped"`` means it cannot run (no matching evidence).
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    task: str = Field(min_length=1)
    modality: Modality
    agent: str | None = None  # e.g. "text_reasoner"; None when not runnable
    status: TaskStatus
    reason: str = ""
    target_references: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    sub_question_ids: list[str] = Field(default_factory=list)


class AnalyzeResponse(BaseModel):
    """Output of ``POST /api/v1/analyze`` (API_SPEC §3.3).

    Structured intermediate artifacts only — no final natural-language answer
    (the AnswerGenerator arrives in a later phase). Claims carry
    ``verification=None`` until the judge exists (Phase 4).
    """

    model_config = ConfigDict(extra="forbid")

    request_id: str
    status: ResponseStatus
    plan: QueryPlan | None = None
    tasks: list[PlannedTask] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    agent_outputs: list[AgentRun] = Field(default_factory=list)
    metadata: ResponseMetadata = Field(default_factory=ResponseMetadata)
