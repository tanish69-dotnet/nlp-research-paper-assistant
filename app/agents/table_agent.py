"""Table Reasoning Agent (ARCHITECTURE §4.3).

Structured ``TableData`` is the authoritative numerical source; image is only
supplementary (PRD §10: use both ``table_data`` and ``table_image`` when
available). Deterministic helpers from :mod:`app.agents.table_ops` are run
first; the LLM interprets their traces.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from app.agents.base import AgentContext, agent_error_from, complete_json, new_agent_run
from app.agents.table_ops import (
    best_in_column,
    lookup_cell,
    numeric_ranking,
)
from app.core.errors import EvidenceInvalidError
from app.evidence.table_quality import table_evidence_status, table_evidence_supports_values
from app.models.base import ModelProvider
from app.prompts.assembly import EvidenceContext, assemble_three_zone
from app.prompts.loader import load_prompt
from app.schemas.claims import AgentRun, Claim
from app.schemas.evidence import EvidenceItem

logger = structlog.get_logger(__name__)

AGENT_NAME = "table_reasoner"
PROMPT_VERSION = "table_agent/v1"
ALLOWED_KINDS = frozenset(
    {"table_observation", "table_comparison", "table_interpretation", "author_claim", "limitation"}
)


def _numeric_columns(table_item: EvidenceItem) -> list[str]:
    if table_item.table_data is None:
        return []
    # Heuristic: every non-first column that contains at least one parseable float
    # is a candidate for "metric" ordering.
    from app.agents import table_ops as _ops  # local import: avoid circular

    headers = table_item.table_data.headers
    numeric: list[str] = []
    for header in headers[1:]:
        values = _ops._numeric_column_values(table_item.table_data, header)  # noqa: SLF001
        if values:
            numeric.append(header)
    return numeric


class TableAgent:
    """Reasons over structured tables with a place for a fallback image."""

    name = AGENT_NAME

    def __init__(self, provider: ModelProvider, *, prompt_version: str = "v1") -> None:
        self._provider = provider
        self._prompt_version = prompt_version

    # --- evidence selection ------------------------------------------------
    def _table_items(self, evidence: tuple[EvidenceItem, ...]) -> list[EvidenceItem]:
        return [item for item in evidence if item.type == "table"]

    def _evidence_contexts(
        self, evidence: tuple[EvidenceItem, ...], max_chars: int
    ) -> tuple[list[EvidenceContext], list[EvidenceItem]]:
        """Keep only table items (and their text envelope for context)."""
        items = self._table_items(evidence)
        contexts: list[EvidenceContext] = []
        for item in items:
            contexts.append(EvidenceContext.from_item(item, max_chars))
        return contexts, items

    # --- deterministic trace construction ----------------------------------
    def _deterministic_trace(
        self, items: list[EvidenceItem], query: str
    ) -> list[str]:
        """Derive a small, focused trace from headers/caption + question wording.

        The LLM receives these lines verbatim under "DETERMINISTIC TRACE" — it
        must not contradict them. Limit to at most one best + one ranking per
        table so the prompt stays bounded.
        """
        traces: list[str] = []
        query_lower = query.lower()
        for item in items:
            table = item.table_data
            if table is None:
                if item.image is not None:
                    traces.append(
                        f"Note: {item.evidence_id} has no structured table_data — "
                        f"text/caption + table_image are the only sources."
                    )
                continue
            if not table.headers:
                continue

            numeric_cols = _numeric_columns(item)
            # Focus on the column mentioned in the query (header substring match).
            focused: list[str] = []
            for col in numeric_cols:
                if col.strip().lower() in query_lower:
                    focused.append(col)
            if not focused and any(w in query_lower for w in ("best", "highest", "lowest", "most", "rank", "top", "winning")):
                focused = numeric_cols[:1]
            if not focused and numeric_cols:
                focused = numeric_cols[:1]

            for column in focused:
                result = best_in_column(table, item.evidence_id, column)
                traces.append(result.detail)
            if item.caption:
                traces.append(f"Caption ({item.evidence_id}): {item.caption}")
        return traces

    # --- findings validation -----------------------------------------------
    def _validated_findings(
        self,
        raw_findings: list[dict[str, Any]],
        known_ids: set[str],
    ) -> tuple[list[Claim], list[str]]:
        kept: list[Claim] = []
        dropped: list[str] = []
        for idx, raw in enumerate(raw_findings):
            payload = dict(raw)
            payload.setdefault("agent", AGENT_NAME)
            try:
                candidate = Claim.model_validate(payload)
            except Exception as exc:  # noqa: BLE001
                dropped.append(f"claim[{idx}] schema: {type(exc).__name__}")
                continue
            if candidate.kind not in ALLOWED_KINDS:
                dropped.append(f"claim[{candidate.claim_id}] kind={candidate.kind!r} not allowed for table")
                continue
            unknown = [eid for eid in candidate.evidence_ids if eid not in known_ids]
            if unknown:
                logger.warning(
                    "table_agent_dropped_unknown_evidence_id",
                    component="agents",
                    claim_id=candidate.claim_id,
                    unknown=unknown,
                )
                continue
            kept.append(candidate)
        return kept, dropped

    # --- main --------------------------------------------------------------
    async def run_for_evidence(
        self,
        ctx: AgentContext,
        evidence: tuple[EvidenceItem, ...] | None = None,
        *,
        max_chars_per_item: int = 4000,
    ) -> tuple[list[Claim], AgentRun]:
        started = time.perf_counter()
        if evidence is None:
            evidence = ctx.evidence

        items = self._table_items(evidence)
        known_ids = {item.evidence_id for item in evidence}

        if not items:
            return [], new_agent_run(
                AGENT_NAME,
                ctx,
                status="no_evidence",
                started_s=started,
                evidence_ids_used=[],
                prompt_version=PROMPT_VERSION,
            )

        # A caption-only table remains searchable, but must not be handed to a
        # model for a numerical/comparative question.  The deterministic Judge
        # has the same gate for callers that bypass this agent guard.
        if any(not table_evidence_supports_values(item) for item in items) and _requires_table_values(ctx.query):
            incomplete = [
                f"{item.evidence_id}={table_evidence_status(item)}"
                for item in items
                if not table_evidence_supports_values(item)
            ]
            logger.info(
                "table_agent_incomplete_evidence",
                component="agents",
                request_id=ctx.request_id,
                evidence=incomplete,
            )
            return [], new_agent_run(
                AGENT_NAME,
                ctx,
                status="no_evidence",
                started_s=started,
                evidence_ids_used=list(known_ids),
                prompt_version=PROMPT_VERSION,
            )

        evidence_ctx, table_items = self._evidence_contexts(evidence, max_chars_per_item)
        trace_lines = self._deterministic_trace(table_items, ctx.query)

        # Assemble three-zone prompt: Zone A is the template, Zone B is the
        # question, Zone C is the structured table envelope. Deterministic
        # trace lines are appended inside the user content, not into Zone A.
        template = load_prompt("table_agent", self._prompt_version)
        messages = assemble_three_zone(template, ctx.query, evidence_ctx)
        system, user = messages[0].content, messages[1].content
        if trace_lines:
            user += "\n\n--- DETERMINISTIC TRACE (authoritative, do not contradict) ---\n" + "\n".join(trace_lines)

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
        if drop_reasons:
            logger.info(
                "table_agent_filtered_findings",
                component="agents",
                kept=len(kept),
                dropped=len(drop_reasons),
                reasons=drop_reasons,
            )
        status = "ok" if kept else "partial"
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
        _, run = await self.run_for_evidence(ctx, ctx.evidence)
        return run


def _requires_table_values(query: str) -> bool:
    """Conservative routing guard for value/comparison table questions."""
    import re

    return bool(
        re.search(
            r"\b(?:best|better|highest|lowest|higher|lower|outperform|"
            r"performance|accuracy|score|metric|rank(?:ed|ing)?|compare|which model|which method)\b",
            query or "",
            re.IGNORECASE,
        )
    )
