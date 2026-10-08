"""``POST /api/v1/analyze`` — structured analysis endpoint (Phase 2).

The route is owned here (``app/api``) — orchestration is pure (takes a bundle
and settings, returns structured artifacts) and agents are provider-pluggable.
This keeps the boundary ARCHITECTURE demands clean:
``routes/analyze.py → orchestration/planner → agents/* → models/*``.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request

from app.agents.base import AgentContext
from app.agents.query_analyzer import QueryAnalyzer
from app.agents.text_agent import TextAgent
from app.api.dependencies import get_registry, get_request_id, get_settings
from app.config import Settings
from app.core.errors import EvidenceEmptyError
from app.evidence.validation import validate_evidence
from app.models.routing import ModelRegistry
from app.orchestration.planner import plan_tasks
from app.schemas.analysis import AnalyzeResponse
from app.schemas.claims import AgentRun
from app.schemas.evidence import EvidenceBundle
from app.schemas.query import QueryPlan
from app.schemas.reasoning import ReasoningOptions, ResponseMetadata

router = APIRouter(tags=["analyze"])

# Pydantic view types for this endpoint (must be plain models, not internal
# domain objects, so OpenAPI renders without exposing internal aliases).
from pydantic import BaseModel, ConfigDict  # noqa: E402  # keep route header readable


class AnalyzeRequest(BaseModel):
    """Request to ``POST /api/v1/analyze`` (API_SPEC §3.3).

    Validation allows an empty evidence list so the handler can answer with the
    documented ``400 EVIDENCE_EMPTY`` rather than a 422.
    """

    model_config = ConfigDict(extra="forbid")

    query: str
    evidence: EvidenceBundle
    options: ReasoningOptions | None = None
    request_id: str | None = None


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    summary="Analyze a question and extract text-backed claims",
    description=(
        "Validated evidence → QueryPlan (via the Analyzer, with a deterministic "
        "fallback) → planned tasks (text→executable, table/figure→deferred) → "
        "Structured findings from the Text Agent. No final answer is generated "
        "here — claims carry ``verification=None`` until the Judge exists."
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

    # Phase 1 gate: budget + image-path confinement (no traversal).
    validate_evidence(body.evidence, settings)

    request_id = get_request_id(request)  # middleware sets state.request_id
    started_s = time.perf_counter()
    provider = registry.provider
    model_name = registry.model_for(
        # analyzer and text agent use the analyzer/text roles respectively
        __import__("app.models.routing", fromlist=["ModelRole"]).ModelRole.ANALYZER
    )

    # --- analyzer ----------------------------------------------------------
    analyzer = QueryAnalyzer(provider, prompt_version="v1")
    agent_ctx = AgentContext(
        request_id=request_id,
        query=body.query,
        evidence=tuple(body.evidence.evidence),
        model=model_name or registry.provider.name,
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

    # --- text agent --------------------------------------------------------
    claims_holder = []
    text_run: AgentRun | None = None
    wants_text = any(task.status == "executable" and task.modality == "text" for task in tasks)

    if wants_text:
        text_model = registry.model_for(
            __import__("app.models.routing", fromlist=["ModelRole"]).ModelRole.TEXT_REASONER
        )
        text_ctx = AgentContext(
            request_id=request_id,
            query=body.query,
            evidence=tuple(body.evidence.evidence),
            model=text_model or registry.provider.name,
            provider_name=provider.name,
            timeout_s=(settings.agent_timeout_ms / 1000.0),
            temperature=settings.model_temperature,
            max_tokens=settings.model_max_tokens,
        )
        agent = TextAgent(provider, prompt_version="v1")
        text_claims, text_run = await agent.run_for_evidence(text_ctx, tuple(body.evidence.evidence))
        claims_holder = text_claims
    else:
        claims_holder = []

    outputs: list[AgentRun] = [analyzer_run]
    if text_run is not None:
        outputs.append(text_run)

    status = "partial" if any(task.status == "deferred" for task in tasks) else "ok"
    total_ms = int((time.perf_counter() - started_s) * 1000)

    return AnalyzeResponse(
        request_id=request_id,
        status=status,  # type: ignore[arg-type]
        plan=plan,
        tasks=tasks,
        claims=claims_holder,
        agent_outputs=outputs,
        metadata=ResponseMetadata(
            models={
                "analyzer": registry.model_for(
                    __import__("app.models.routing", fromlist=["ModelRole"]).ModelRole.ANALYZER
                ),
                "text_reasoner": registry.model_for(
                    __import__("app.models.routing", fromlist=["ModelRole"]).ModelRole.TEXT_REASONER
                ),
            },
            evidence_total=len(body.evidence.evidence),
            evidence_used=[eid for task in tasks for eid in task.evidence_ids],
            timings_ms={"total": total_ms},
        ),
    )
