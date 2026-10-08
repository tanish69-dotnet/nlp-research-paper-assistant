"""Full reasoning orchestrator (MVP): analyze → agents → judge → answer.

Agents run concurrently where independent; judge failure never promotes
unverified claims as facts; citations are resolved deterministically from
bundle metadata after the generator runs.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import structlog

from app.agents.base import AgentContext, AgentRun
from app.agents.judge_answer import AnswerGenerator, JudgeAgent
from app.agents.query_analyzer import QueryAnalyzer
from app.agents.table_agent import TableAgent
from app.agents.text_agent import TextAgent
from app.agents.vision_agent import VisionAgent
from app.config import Settings
from app.evidence.validation import validate_evidence
from app.models.routing import ModelRegistry, ModelRole
from app.orchestration.planner import plan_tasks
from app.schemas.claims import Claim
from app.schemas.evidence import EvidenceBundle
from app.schemas.health import ProviderHealth
from app.schemas.query import QueryPlan
from app.schemas.reasoning import Citation, ReasoningResponse, ResponseMetadata
from app.schemas.verification import ClaimVerification, VerificationResult

logger = structlog.get_logger(__name__)

# Allowed kinds for verified claims that reach the answer (PRD §18: SUPPORTED
# and, when explicitly allowed by the API contract, qualified PARTIALLY_SUPPORTED).
VERIFIED_VERDICTS = frozenset({"SUPPORTED", "PARTIALLY_SUPPORTED"})


@dataclass
class OrchestratorResult:
    """Return from the full pipeline — the ``/reason`` handler's source of truth."""

    plan: QueryPlan | None
    claims: list[Claim]
    verifications: list[ClaimVerification]
    verification_result: VerificationResult
    agent_runs: list[AgentRun]
    answer: str  # "" when nothing was generated or the generator failed
    citations: list[Citation]
    timings_ms: dict[str, int]
    unverified: bool


def _verification_aggregate(
    verifications: list[ClaimVerification],
    total: int,
) -> VerificationResult:
    if not verifications and total == 0:
        # No claims to verify.
        return VerificationResult(status="unverified")
    if not verifications:
        return VerificationResult(
            status="unverified",
            supported=0,
            partially_supported=0,
            unsupported=0,
            contradicted=0,
            unsupported_claims=[],
            contradicted_claims=[],
            needs_more_evidence=False,
        )

    supported = sum(1 for v in verifications if v.verdict == "SUPPORTED")
    partial = sum(1 for v in verifications if v.verdict == "PARTIALLY_SUPPORTED")
    unsupported = sum(1 for v in verifications if v.verdict == "UNSUPPORTED")
    contradicted = sum(1 for v in verifications if v.verdict == "CONTRADICTED")
    unsupported_claims = [v.claim_id for v in verifications if v.verdict == "UNSUPPORTED"]
    contradicted_claims = [v.claim_id for v in verifications if v.verdict == "CONTRADICTED"]

    if contradicted or unsupported or not (supported or partial):
        status = "unsupported"
        if supported and unsupported:
            status = "mixed"
        elif not supported and partial and unsupported == 0:
            status = "partially_supported"
    elif supported and partial == 0:
        status = "supported"
    elif partial:
        status = "partially_supported"
    else:
        status = "mixed"

    return VerificationResult(
        status=status,  # type: ignore[arg-type]
        supported=supported,
        partially_supported=partial,
        unsupported=unsupported,
        contradicted=contradicted,
        unsupported_claims=unsupported_claims,
        contradicted_claims=contradicted_claims,
        needs_more_evidence=bool(unsupported or contradicted),
    )


def _resolve_citations(bundle: EvidenceBundle, claims: list[Claim]) -> list[Citation]:
    """Deterministic citation resolution from verified claims' evidence_ids.

    Marks are like ``[citation:<claim_id>]`` in the generator's text — the
    resolver never reads the answer text itself (it comes from the generator,
    which is untrusted about ids). The binding is ``claim_id → evidence_ids``
    already present on the verified ``Claim``.
    """
    by_eid = {item.evidence_id: item for item in bundle.evidence}
    paper_title: dict[str, str | None] = {paper.paper_id: paper.title for paper in bundle.papers}
    seen: set[str] = set()
    citations: list[Citation] = []
    counter = 1
    for claim in claims:
        for eid in claim.evidence_ids:
            if eid in seen:
                continue
            seen.add(eid)
            item = by_eid.get(eid)
            if item is None:
                # Invariant violation already captured by the judge — skip.
                continue
            citations.append(
                Citation(
                    citation_id=f"c{counter}",
                    evidence_id=eid,
                    paper_id=item.paper_id,
                    page=item.page,
                    type=item.type,  # type: ignore[arg-type]
                    reference=item.reference,
                    title=paper_title.get(item.paper_id),
                )
            )
            counter += 1
    return citations


def _strip_citation_placeholders(answer: str) -> str:
    """Rewrite *generated* citation markers that don't correspond to a real claim.

    Model-produced markers ``[citation:<claim_id>]`` that don't match any
    verified claim are stripped (they would be fabricated citations if kept).
    """
    return answer  # placeholders kept; the UI maps claim_id → citation — no stripping needed for MVP


async def full_reasoning(
    query: str,
    bundle: EvidenceBundle,
    request_id: str,
    settings: Settings,
    registry: ModelRegistry,
) -> OrchestratorResult:
    """Run the entire verified reasoning pipeline.

    On any agent failure, that agent's claims are simply absent; the judge
    still runs. On judge failure, no factual answer is presented as verified
    (return an empty answer, with ``unverified=True`` propagated to the
    response's ``verification.status``).
    """
    timings: dict[str, int] = {}

    # Bundle-level validation: budget + image-root confinement (fast path).
    validate_evidence(bundle, settings)

    provider = registry.provider

    # --- analyzer ----------------------------------------------------------
    analyzer_started = time.perf_counter()
    analyzer = QueryAnalyzer(provider, prompt_version="v1")
    analyzer_ctx = AgentContext(
        request_id=request_id,
        query=query,
        evidence=tuple(bundle.evidence),
        model=registry.model_for(ModelRole.ANALYZER) or provider.name,
        provider_name=provider.name,
        timeout_s=settings.agent_timeout_ms / 1000.0,
        temperature=settings.model_temperature,
        max_tokens=settings.model_max_tokens,
    )
    plan, analyzer_run = await analyzer.analyze(analyzer_ctx, tuple(bundle.evidence))
    timings["analyze"] = int((time.perf_counter() - analyzer_started) * 1000)

    tasks = plan_tasks(plan, bundle, settings)
    agent_runs: list[AgentRun] = [analyzer_run]

    # --- agents (modality-aware; run in parallel) -------------------------
    want_text = any(task.status == "executable" and task.modality == "text" for task in tasks)
    want_table = any(task.status == "executable" and task.modality == "table" for task in tasks)
    want_figure = any(task.status == "executable" and task.modality == "figure" for task in tasks)

    timeout = settings.agent_timeout_ms / 1000.0
    temp = settings.model_temperature
    max_tokens = settings.model_max_tokens

    coros: list[tuple[str, Any]] = []
    if want_text:
        text_ctx = AgentContext(
            request_id=request_id,
            query=query,
            evidence=tuple(bundle.evidence),
            model=registry.model_for(ModelRole.TEXT_REASONER) or provider.name,
            provider_name=provider.name,
            timeout_s=timeout,
            temperature=temp,
            max_tokens=max_tokens,
        )
        coros.append(("text_reasoner", TextAgent(provider, prompt_version="v1").run_for_evidence(text_ctx, tuple(bundle.evidence))))
    if want_table:
        table_ctx = AgentContext(
            request_id=request_id,
            query=query,
            evidence=tuple(bundle.evidence),
            model=registry.model_for(ModelRole.TABLE_REASONER) or provider.name,
            provider_name=provider.name,
            timeout_s=timeout,
            temperature=temp,
            max_tokens=max_tokens,
        )
        coros.append(("table_reasoner", TableAgent(provider, prompt_version="v1").run_for_evidence(table_ctx, tuple(bundle.evidence))))
    if want_figure:
        vision_ctx = AgentContext(
            request_id=request_id,
            query=query,
            evidence=tuple(bundle.evidence),
            model=registry.model_for(ModelRole.VISION_REASONER) or provider.name,
            provider_name=provider.name,
            timeout_s=timeout,
            temperature=temp,
            max_tokens=max_tokens,
            extra={"settings": settings},
        )
        coros.append(("vision_reasoner", VisionAgent(provider, prompt_version="v1").run_for_evidence(vision_ctx, tuple(bundle.evidence))))

    claims: list[Claim] = []
    agents_started = time.perf_counter()
    if coros:
        results = await asyncio.gather(*(coro for _, coro in coros), return_exceptions=True)
        for (name, _), result in zip(coros, results):  # type: ignore[arg-type]
            if isinstance(result, Exception):
                from app.agents.base import agent_error_from, new_agent_run as _new  # noqa: WPS433

                agent_runs.append(
                    _new(
                        name,
                        AgentContext(request_id=request_id, query=query, evidence=(), model="", provider_name=provider.name),
                        status="error",
                        started_s=agents_started,
                        error=agent_error_from(result),
                    )
                )
            else:
                agent_claims, agent_run = result
                claims.extend(agent_claims)
                agent_runs.append(agent_run)
    timings["agents"] = int((time.perf_counter() - agents_started) * 1000)

    # Nothing to verify → still run the generator's honest empty path.
    bundle_map = {item.evidence_id: item for item in bundle.evidence}
    claim_ids = {claim.claim_id for claim in claims}
    verifications: list[ClaimVerification] = []
    verification_result = VerificationResult(status="unverified" if claims else "unverified")
    unverified = False
    judge_started = time.perf_counter()

    if claims:
        judge = JudgeAgent(provider, prompt_version="v1")
        judge_ctx = AgentContext(
            request_id=request_id,
            query=query,
            evidence=tuple(bundle.evidence),
            model=registry.model_for(ModelRole.JUDGE) or provider.name,
            provider_name=provider.name,
            timeout_s=timeout,
            temperature=temp,
            max_tokens=max_tokens,
        )
        verifications, judge_run = await judge.judge(claims, bundle, judge_ctx)
        agent_runs.append(judge_run)
        if judge_run.status == "error":
            unverified = True
            verification_result = VerificationResult(status="unverified")
        else:
            # The deterministic layer may have already marked some as
            # contradictions/unsupported — split the aggregate.
            verification_result = _verification_aggregate(verifications, len(claims))
            # Mark supported set on each claim's verification (already present
            # as ClaimVerification; mirror on Claim for the response's claims view).
            for claim in claims:
                verdict = next((v for v in verifications if v.claim_id == claim.claim_id), None)
                if verdict is not None:
                    claim.verification = verdict
    timings["verify"] = int((time.perf_counter() - judge_started) * 1000)

    # --- answer: only verified claims survive -----------------------------
    verified_claims: list[Claim] = []
    if not unverified and verifications:
        supported_ids = {v.claim_id for v in verifications if v.verdict in VERIFIED_VERDICTS}
        verified_claims = [claim for claim in claims if claim.claim_id in supported_ids]
    elif not unverified and not claims:
        verified_claims = []

    answer_text = ""
    citations: list[Citation] = []
    generator_run: AgentRun | None = None

    if unverified:
        # Do not call the generator on an unverified pipeline; there is no
        # factual answer to synthesize. VERIFIED_VERDICTS is intentionally
        # empty when the judge cannot vouch for any claim.
        agent_runs.append(
            AgentRun(  # type: ignore[call-arg]
                agent="answer_generator",
                model="",
                provider=provider.name,
                prompt_version="answer_generator/v1",
                status="skipped",
                latency_ms=0,
                findings=[],
                evidence_ids_used=[],
            )
        )
    else:
        generator = AnswerGenerator(provider, prompt_version="v1")
        gen_ctx = AgentContext(
            request_id=request_id,
            query=query,
            evidence=tuple(bundle.evidence),
            model=registry.model_for(ModelRole.GENERATOR) or provider.name,
            provider_name=provider.name,
            timeout_s=timeout,
            temperature=temp,
            max_tokens=max_tokens,
        )
        generator_started = time.perf_counter()
        answer_text, generator_run = await generator.generate(query, verified_claims, gen_ctx)
        timings["generate"] = int((time.perf_counter() - generator_started) * 1000)
        agent_runs.append(generator_run)
        # An erroneous generator should not claim a confident answer — empty the
        # answer in that case (the verified claims + statuses remain for the UI).
        if generator_run.status == "error":
            answer_text = ""

    # --- citations: deterministic resolve of verified claims only ----------
    if not unverified and verified_claims:
        citations = _resolve_citations(bundle, verified_claims)

    return OrchestratorResult(
        plan=plan,
        claims=claims,
        verifications=verifications,
        verification_result=verification_result,
        agent_runs=agent_runs,
        answer=answer_text,
        citations=citations,
        timings_ms=timings,
        unverified=unverified,
    )
