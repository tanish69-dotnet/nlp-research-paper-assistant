"""``POST /api/v1/analyze`` — structured analysis endpoint (Phase 3).

Validated evidence → QueryPlan → planned tasks (text/table/figure) →
per-modality agents run in parallel where independent. Verification is absent
until the Judge arrives (Phase 4) — claims carry ``verification=None``.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from app.agents.base import AgentContext, AgentRun
from app.agents.query_analyzer import QueryAnalyzer
from app.agents.table_agent import TableAgent
from app.agents.text_agent import TextAgent
from app.agents.vision_agent import VisionAgent
from app.api.dependencies import get_registry, get_request_id, get_settings
from app.config import Settings
from app.core.errors import EvidenceEmptyError
from app.evidence.validation import validate_evidence
from app.models.routing import ModelRegistry
from app.orchestration.planner import plan_tasks
from app.schemas.analysis import AnalyzeResponse
from app.schemas.claims import Claim
from app.schemas.evidence import EvidenceBundle
from app.schemas.query import QueryPlan
from app.schemas.reasoning import ReasoningOptions, ResponseMetadata

router = APIRouter(tags=["analyze"])


class AnalyzeRequest(BaseModel):
    """Request to ``POST /api/v1/analyze`` (API_SPEC §3.3)."""

    model_config = ConfigDict(extra="forbid")

    query: str
    evidence: EvidenceBundle
    options: ReasoningOptions | None = None
    request_id: str | None = None


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    summary="Analyze a question and extract grounded claims",
    description=(
        "Validated evidence → QueryPlan (via the Analyzer, with a deterministic "
        "fallback) → planned tasks (text/table/figure) → structured findings "
        "from Text/Table/Vision agents. Claims carry ``verification=None`` until "
        "Phase 4; no final answer is generated."
    ),
)
async def analyze(
    request: Request,
    body: AnalyzeRequest,
    settings: Settings = Depends(get_settings),
    registry: ModelRegistry = Depends(get_registry),
) -> AnalyzeResponse:
    if not body.evidence.evidence:
        raise EvidenceEmptyError("evidence list is empty; nothing to reason over")

    validate_evidence(body.evidence, settings)

    request_id = get_request_id(request)
    started_s = time.perf_counter()
    provider = registry.provider

    # --- analyzer ----------------------------------------------------------
    analyzer = QueryAnalyzer(provider, prompt_version="v1")
    analyzer_model = registry.model_for(
        __import__("app.models.routing", fromlist=["ModelRole"]).ModelRole.ANALYZER
    )
    agent_ctx = AgentContext(
        request_id=request_id,
        query=body.query,
        evidence=tuple(body.evidence.evidence),
        model=analyzer_model or provider.name,
        provider_name=provider.name,
        timeout_s=(settings.agent_timeout_ms / 1000.0),
        temperature=settings.model_temperature,
        max_tokens=settings.model_max_tokens,
    )
    plan: QueryPlan
    analyzer_run: AgentRun
    plan, analyzer_run = await analyzer.analyze(agent_ctx, tuple(body.evidence.evidence))

    # --- planner -----------------------------------------------------------
    tasks = plan_tasks(plan, body.evidence, settings)

    # --- agents (modality-aware; run in parallel where independent) --------
    # Tasks are grouped by modality so each agent receives only the evidence
    # that belongs to it (PRD §10: use both table_data and table_image when
    # available; figure reasoning uses caption + surrounding text).
    text_tasks = [task for task in tasks if task.modality == "text" and task.status == "executable"]
    table_tasks = [task for task in tasks if task.modality == "table" and task.status == "executable"]
    figure_tasks = [task for task in tasks if task.modality == "figure" and task.status == "executable"]

    wants_text = bool(text_tasks)
    wants_table = bool(table_tasks)
    wants_figure = bool(figure_tasks)

    claims: list[Claim] = []
    agent_runs: list[AgentRun] = [analyzer_run]

    timeout = settings.agent_timeout_ms / 1000.0
    temperature = settings.model_temperature
    max_tokens = settings.model_max_tokens

    coros: list[tuple[str, Any]] = []
    if wants_text:
        text_model = registry.model_for(
            __import__("app.models.routing", fromlist=["ModelRole"]).ModelRole.TEXT_REASONER
        )
        text_ctx = AgentContext(
            request_id=request_id,
            query=body.query,
            evidence=tuple(body.evidence.evidence),
            model=text_model or provider.name,
            provider_name=provider.name,
            timeout_s=timeout,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        agent = TextAgent(provider, prompt_version="v1")
        coros.append(("text_reasoner", agent.run_for_evidence(text_ctx, tuple(body.evidence.evidence))))

    if wants_table:
        table_model = registry.model_for(
            __import__("app.models.routing", fromlist=["ModelRole"]).ModelRole.TABLE_REASONER
        )
        table_ctx = AgentContext(
            request_id=request_id,
            query=body.query,
            evidence=tuple(body.evidence.evidence),
            model=table_model or provider.name,
            provider_name=provider.name,
            timeout_s=timeout,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        agent = TableAgent(provider, prompt_version="v1")
        coros.append(("table_reasoner", agent.run_for_evidence(table_ctx, tuple(body.evidence.evidence))))

    if wants_figure:
        vision_model = registry.model_for(
            __import__("app.models.routing", fromlist=["ModelRole"]).ModelRole.VISION_REASONER
        )
        vision_ctx = AgentContext(
            request_id=request_id,
            query=body.query,
            evidence=tuple(body.evidence.evidence),
            model=vision_model or provider.name,
            provider_name=provider.name,
            timeout_s=timeout,
            temperature=temperature,
            max_tokens=max_tokens,
            extra={"settings": settings},
        )
        agent = VisionAgent(provider, prompt_version="v1")
        coros.append(("vision_reasoner", agent.run_for_evidence(vision_ctx, tuple(body.evidence.evidence))))

    async def _gather() -> None:
        results = await asyncio.gather(*(coro for _, coro in coros), return_exceptions=True)
        for (name, _), result in zip(coros, results):  # type: ignore[arg-type]
            if isinstance(result, Exception):
                # Provider-level failure became a BaseException before the agent
                # could emit an AgentRun — synthesize a degraded run.
                from app.agents.base import agent_error_from, new_agent_run as _new  # noqa: WPS433

                agent_runs.append(
                    _new(
                        name,
                        AgentContext(request_id=request_id, query=body.query, evidence=(), model="", provider_name=provider.name),
                        status="error",
                        started_s=started_s,
                        error=agent_error_from(result),
                    )
                )
            else:
                agent_claims, agent_run = result
                claims.extend(agent_claims)
                agent_runs.append(agent_run)

    if coros:
        await _gather()

    status = "partial" if any(task.status in {"deferred", "skipped"} for task in tasks) else "ok"
    # A degraded/error run for an agent that was supposed to handle the question
    # also promotes the response to partial.
    if any(run.status in {"error", "no_evidence"} and run.agent in {"text_reasoner", "table_reasoner", "vision_reasoner"} for run in agent_runs):
        if status == "ok":
            status = "partial"

    total_ms = int((time.perf_counter() - started_s) * 1000)
    return AnalyzeResponse(
        request_id=request_id,
        status=status,  # type: ignore[arg-type]
        plan=plan,
        tasks=tasks,
        claims=claims,
        agent_outputs=agent_runs,
        metadata=ResponseMetadata(
            models={
                "analyzer": analyzer_model,
                "text_reasoner": registry.model_for(
                    __import__("app.models.routing", fromlist=["ModelRole"]).ModelRole.TEXT_REASONER
                ),
                "table_reasoner": registry.model_for(
                    __import__("app.models.routing", fromlist=["ModelRole"]).ModelRole.TABLE_REASONER
                ),
                "vision_reasoner": registry.model_for(
                    __import__("app.models.routing", fromlist=["ModelRole"]).ModelRole.VISION_REASONER
                ),
            },
            evidence_total=len(body.evidence.evidence),
            evidence_used=[eid for task in tasks for eid in task.evidence_ids],
            timings_ms={"total": total_ms},
        ),
    )
