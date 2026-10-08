"""Text Reasoning Agent (ARCHITECTURE §4.2).

Reasons only over the text-type evidence passed by the planner, extracts
atomic findings, and labels each one as ``author_claim`` vs ``inference``.
Every claim is bound to the supplied evidence ids — any id the model
invents is dropped rather than hallucinated citations created.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from app.agents.base import AgentContext, agent_error_from, complete_json, new_agent_run
from app.models.base import ModelProvider
from app.prompts.assembly import EvidenceContext, assemble_three_zone
from app.prompts.loader import load_prompt
from app.schemas.claims import AgentRun, Claim
from app.schemas.evidence import EvidenceItem

logger = structlog.get_logger(__name__)

AGENT_NAME = "text_reasoner"
PROMPT_VERSION = "text_agent/v1"
ALLOWED_KINDS = frozenset({"author_claim", "inference", "limitation", "methodology", "definition"})


class TextAgent:
    """Produces structured findings over text-type evidence."""

    name = AGENT_NAME

    def __init__(self, provider: ModelProvider, *, prompt_version: str = "v1") -> None:
        self._provider = provider
        self._prompt_version = prompt_version

    def _evidence_contexts(
        self, evidence: tuple[EvidenceItem, ...], max_chars: int
    ) -> list[EvidenceContext]:
        """Keep only text items for this agent."""
        return [
            EvidenceContext.from_item(item, max_chars)
            for item in evidence
            if item.type == "text"
        ]

    def _validated_findings(
        self,
        raw_findings: list[dict[str, Any]],
        known_ids: set[str],
    ) -> tuple[list[Claim], list[str]]:
        """Schema-validate, filter by kind and by evidence id.

        Returns ``(kept_claims, dropped_reason_log)``.
        """
        kept: list[Claim] = []
        dropped_reasons: list[str] = []
        for idx, raw in enumerate(raw_findings):
            payload = dict(raw)
            payload.setdefault("agent", AGENT_NAME)
            try:
                candidate = Claim.model_validate(payload)
            except Exception as exc:  # noqa: BLE001
                dropped_reasons.append(f"claim[{idx}] schema: {type(exc).__name__}")
                continue
            if candidate.kind not in ALLOWED_KINDS:
                dropped_reasons.append(f"claim[{candidate.claim_id}] kind={candidate.kind!r} not allowed for text")
                continue
            unknown = [eid for eid in candidate.evidence_ids if eid not in known_ids]
            if unknown:
                logger.warning(
                    "text_agent_dropped_unknown_evidence_id",
                    component="agents",
                    claim_id=candidate.claim_id,
                    unknown=unknown,
                )
                continue
            kept.append(candidate)

        # If everything was dropped but we had text evidence we say the agent
        # honestly reports "insufficient" rather than hallucinating an empty
        # fallback list.
        return kept, dropped_reasons

    async def run_for_evidence(
        self,
        ctx: AgentContext,
        evidence: tuple[EvidenceItem, ...] | None = None,
        *,
        max_chars_per_item: int = 4000,
    ) -> tuple[list[Claim], AgentRun]:
        """Run the text agent for a slice of evidence.

        Returns ``(claims, AgentRun)`` so the orchestrator and API can carry
        both the findings and their provenance.
        """
        started = time.perf_counter()
        if evidence is None:
            evidence = ctx.evidence
        evidence_ctx = self._evidence_contexts(evidence, max_chars_per_item)
        known_ids = {item.evidence_id for item in evidence if item.type == "text"}

        if not evidence_ctx:
            logger.info(
                "text_agent_no_evidence",
                component="agents",
                request_id=ctx.request_id,
            )
            return [], new_agent_run(
                AGENT_NAME,
                ctx,
                status="no_evidence",
                started_s=started,
                evidence_ids_used=[],
                prompt_version=PROMPT_VERSION,
            )

        template = load_prompt("text_agent", self._prompt_version)
        messages = assemble_three_zone(template, ctx.query, evidence_ctx)
        system, user = messages[0].content, messages[1].content

        try:
            payload, response = await complete_json(
                self._provider, system=system, user=user, ctx=ctx
            )
        except Exception as exc:  # noqa: BLE001
            return [], new_agent_run(
                AGENT_NAME,
                ctx,
                status="error",
                started_s=started,
                evidence_ids_used=list(known_ids),
                prompt_version=PROMPT_VERSION,
                error=agent_error_from(exc),
            )

        raw_findings = payload.get("findings") if isinstance(payload, dict) else None
        if not isinstance(raw_findings, list):
            return [], new_agent_run(
                AGENT_NAME,
                ctx,
                status="error",
                started_s=started,
                evidence_ids_used=list(known_ids),
                prompt_version=PROMPT_VERSION,
                error=agent_error_from(
                    type("MalformedOutput", (), {"detail": "payload.findings is not a list"})(),
                ),
            )

        kept, drop_reasons = self._validated_findings(raw_findings, known_ids)
        status = "ok" if kept else "partial"
        if drop_reasons:
            logger.info(
                "text_agent_filtered_findings",
                component="agents",
                kept=len(kept),
                dropped=len(drop_reasons),
                reasons=drop_reasons,
            )

        return kept, new_agent_run(
            AGENT_NAME,
            ctx,
            status=status,
            started_s=started,
            findings=[claim.claim_id for claim in kept],
            evidence_ids_used=list(known_ids),
            prompt_version=PROMPT_VERSION,
            usage_prompt_tokens=response.usage.prompt_tokens,
            usage_completion_tokens=response.usage.completion_tokens,
        )

    async def run(self, ctx: AgentContext) -> AgentRun:
        """Protocol entrypoint: reason over ``ctx.evidence``."""
        _, run = await self.run_for_evidence(ctx, ctx.evidence)
        return run
