"""``POST /api/v1/reason`` — full verified reasoning pipeline (MVP).

Validated evidence → analyzer → planner → text/table/vision agents (concurrent)
→ judge (per-claim four-verdict) → answer generator (verified-claims-only) →
deterministic citations. Every agent step is degradation-aware; an unverified
pipeline never presents claims as facts.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from app.api.dependencies import get_registry, get_request_id, get_settings
from app.config import Settings
from app.core.errors import EvidenceEmptyError
from app.models.routing import ModelRegistry
from app.orchestration.orchestrator import full_reasoning
from app.schemas.analysis import PlannedTask
from app.schemas.evidence import EvidenceBundle
from app.schemas.reasoning import ReasoningResponse, ResponseMetadata, ResponseStatus

router = APIRouter(tags=["reason"])


class ReasonRequest(BaseModel):
    """Body to ``POST /api/v1/reason``."""

    model_config = ConfigDict(extra="forbid")

    query: str
    evidence: EvidenceBundle
    request_id: str | None = None


def _status_for(result: object, bundle_size: int) -> ResponseStatus:
    # ``unverified`` produces a degraded response (partial) even though the
    # service itself is healthy — mirrors /analyze semantics.
    from app.orchestration.orchestrator import VERIFIED_VERDICTS  # noqa: WPS433

    if getattr(result, "unverified", False):  # type: ignore[no-any-return]
        return "partial"
    agent_runs = getattr(result, "agent_runs", [])
    has_error = any(getattr(run, "status", "") == "error" for run in agent_runs)
    has_partial = any(getattr(run, "status", "") in {"partial", "no_evidence"} for run in agent_runs)
    if has_error or has_partial:
        return "partial"
    verified = [v for v in getattr(result, "verifications", []) if v.verdict in VERIFIED_VERDICTS]
    if not verified and bundle_size > 0:
        # No verifiable evidence → honest empty answer, but not an error.
        return "partial"
    return "ok"


@router.post(
    "/reason",
    response_model=ReasoningResponse,
    summary="Verified multimodal reasoning",
    description=(
        "Validated evidence → QueryPlan → planned tasks → concurrent agents "
        "(text / table / vision) → per-claim Judge (SUPPORTED / "
        "PARTIALLY_SUPPORTED / UNSUPPORTED / CONTRADICTED) → answer generator "
        "grounded on verified claims → deterministic citations. Claims from "
        "unsupported agents are excluded; if the judge cannot decide, no "
        "factual answer is presented as verified."
    ),
)
async def reason(
    request: Request,
    body: ReasonRequest,
    settings: Settings = Depends(get_settings),
    registry: ModelRegistry = Depends(get_registry),
) -> ReasoningResponse:
    if not body.evidence.evidence:
        raise EvidenceEmptyError("evidence list is empty; nothing to reason over")

    request_id = get_request_id(request)
    started = time.perf_counter()

    result = await full_reasoning(
        query=body.query,
        bundle=body.evidence,
        request_id=request_id,
        settings=settings,
        registry=registry,
    )

    # Confining branch: unverified never produces a confident numeric answer.
    confidence: float
    if result.unverified:
        confidence = 0.0
    else:
        raw = getattr(result.verification_result, "supported", 0) / max(1, len(result.claims)) if result.claims else 0.0
        # 0.0 when nothing survived; otherwise 1.0 for purely supported.
        if result.verification_result.status == "supported":
            confidence = 0.9
        elif result.verification_result.status == "partially_supported":
            confidence = 0.6
        elif result.verification_result.status == "mixed":
            confidence = 0.5
        else:
            confidence = raw

    status = _status_for(result, len(body.evidence.evidence))
    total_ms = int((time.perf_counter() - started) * 1000)

    return ReasoningResponse(
        request_id=request_id,
        status=status,  # type: ignore[arg-type]
        answer=result.answer or (
            "The supplied evidence does not support a verified answer." if result.unverified else result.answer
        ),
        confidence=confidence,
        citations=result.citations,
        claims=result.claims,
        verification=result.verification_result,
        agent_outputs=result.agent_runs,
        plan=result.plan,
        metadata=ResponseMetadata(
            models={
                "analyzer": registry.model_for(
                    __import__("app.models.routing", fromlist=["ModelRole"]).ModelRole.ANALYZER
                ),
                "text_reasoner": registry.model_for(
                    __import__("app.models.routing", fromlist=["ModelRole"]).ModelRole.TEXT_REASONER
                ),
                "table_reasoner": registry.model_for(
                    __import__("app.models.routing", fromlist=["ModelRole"]).ModelRole.TABLE_REASONER
                ),
                "vision_reasoner": registry.model_for(
                    __import__("app.models.routing", fromlist=["ModelRole"]).ModelRole.VISION_REASONER
                ),
                "judge": registry.model_for(
                    __import__("app.models.routing", fromlist=["ModelRole"]).ModelRole.JUDGE
                ),
                "generator": registry.model_for(
                    __import__("app.models.routing", fromlist=["ModelRole"]).ModelRole.GENERATOR
                ),
            },
            evidence_total=len(body.evidence.evidence),
            evidence_used=list({eid for claim in result.claims for eid in claim.evidence_ids}),
            timings_ms={**result.timings_ms, "total": total_ms},
            agent_status={run.agent: run.status for run in result.agent_runs},
            degraded=[
                f"{run.agent}:{run.status}"
                for run in result.agent_runs
                if run.status not in {"ok", "partial"}
            ],
            pipeline_version=settings.app_version,
        ),
    )
