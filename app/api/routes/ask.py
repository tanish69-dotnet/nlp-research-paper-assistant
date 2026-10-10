"""POST /api/v1/ask — retrieval-backed convenience endpoint (Phase 8).

Retrieves evidence from Person 2's retrieval service, then delegates to the
existing validated reasoning orchestration (full_reasoning) which is the single
source of truth for evidence validation, agent dispatch, and citation
resolution.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_registry, get_request_id, get_settings
from app.config import Settings
from app.core.errors import (
    EvidenceEmptyError,
    ImagePathForbiddenError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from app.evidence.retrieval_client import (
    RetrievalRequest,
    build_retrieval_provider,
)
from app.evidence.adapter import adapt_retrieval_response
from app.models.routing import ModelRegistry
from app.orchestration.orchestrator import full_reasoning
from app.schemas.reasoning import ReasoningResponse, ResponseMetadata, ResponseStatus

router = APIRouter(tags=["ask"])


class AskRequest(BaseModel):
    """Request body for POST /api/v1/ask."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=50)
    request_id: str | None = None


@router.post(
    "/ask",
    response_model=ReasoningResponse,
    summary="End-to-end retrieval + reasoning",
    description=(
        "Retrieves evidence from Person 2's service (when enabled) and routes it"
        " through the same validated multi-LLM reasoning pipeline used by"
        " /reason. Never fabricates citations or evidence: citations are"
        " derived from the retrieved evidence bundle only."
    ),
)
async def ask(
    request: Request,
    body: AskRequest,
    settings: Settings = Depends(get_settings),
    registry: ModelRegistry = Depends(get_registry),
) -> ReasoningResponse:
    # Guard against accidental deployment without retrieval configured
    if settings.retrieval_mode == "disabled":
        raise ModelUnavailableError(
            "retrieval is disabled (set RETRIEVAL_MODE=mock or http to enable /ask)"
        )

    # Retrieve from Person 2 (mock or http mode)
    provider = build_retrieval_provider(settings)
    top_k = body.top_k if body.top_k is not None else settings.retrieval_top_k
    timeout = settings.retrieval_timeout_s
    request_id = get_request_id(request)
    started = time.perf_counter()

    # Call the remote service — any transport/validation error is translated
    # into a user-facing ProblemDetail (no internal detail leak).
    try:
        raw = await provider.retrieve(
            RetrievalRequest(query=body.query, top_k=top_k, timeout_s=timeout)
        )
    except (ModelTimeoutError, ModelUnavailableError):
        raise
    except Exception as exc:  # noqa: BLE001
        raise ModelUnavailableError("retrieval failed") from exc
    finally:
        # Always close the per-request client if the provider owns one
        try:
            await provider.aclose()
        except Exception:
            pass

    # Adapter: any envelope -> our EvidenceBundle contract
    bundle = raw.bundle
    if bundle is None:
        raise EvidenceEmptyError("retrieval returned no evidence")

    # Reuse the production gate: budgets + image-path confinement + presence
    from app.evidence.validation import validate_evidence  # noqa: WPS433

    try:
        validate_evidence(bundle, settings)
    except ImagePathForbiddenError as exc:
        # Map to EVIDENCE_INVALID so the client knows retrieval data was bad,
        # not that the service is down.
        from app.core.errors import EvidenceInvalidError  # noqa: WPS433

        raise EvidenceInvalidError(f"retrieval image_path forbidden: {exc.detail}") from exc

    # Re-use the production orchestration logic — no duplication.
    result = await full_reasoning(
        query=body.query,
        bundle=bundle,
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
        if result.verification_result.status == "supported":
            confidence = 0.9
        elif result.verification_result.status == "partially_supported":
            confidence = 0.6
        elif result.verification_result.status == "mixed":
            confidence = 0.5
        else:
            confidence = raw

    status: ResponseStatus = "partial" if result.unverified or any(
        getattr(run, "status", "") in {"error", "no_evidence", "partial"} for run in result.agent_runs
    ) else "ok"
    total_ms = int((time.perf_counter() - started) * 1000)

    return ReasoningResponse(
        request_id=request_id,
        status=status,
        answer=result.answer or (
            "The retrieved evidence does not support a verified answer." if result.unverified else result.answer
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
            evidence_total=len(bundle.evidence),
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
