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


def _table_has_row_label_column(table: Any) -> bool:
    """Whether the first header is a row label (all row[0] cells are non-numeric).

    Retrieval corpora are inconsistent: some tables carry an explicit label
    header (``["Model", "R2@1", ...]``) while others drop it
    (``["R2@1", ...]`` with the label still in ``row[0]``). The metric-column
    scan must not treat a missing-label header list as one-metric-short.
    """
    from app.agents import table_ops as _ops  # local import: avoid circular

    if not table.headers or not table.rows:
        return False
    first_cells = [
        str(row[0]).strip()
        for row in table.rows
        if row and row[0] is not None and str(row[0]).strip()
    ]
    if not first_cells:
        return False
    return all(_ops._coerce_float(cell) is None for cell in first_cells)  # noqa: SLF001


def _numeric_columns(table_item: EvidenceItem) -> list[str]:
    if table_item.table_data is None:
        return []
    # Heuristic: every metric column that contains at least one parseable
    # float is a candidate for "metric" ordering. Row-label headers are
    # skipped only when the header list actually carries one.
    from app.agents import table_ops as _ops  # local import: avoid circular

    candidates = (
        table_item.table_data.headers[1:]
        if _table_has_row_label_column(table_item.table_data)
        else table_item.table_data.headers
    )
    numeric: list[str] = []
    for header in candidates:
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
            selected_metric = _selected_metric_label(query)
            # Focus on the column mentioned in the query. A header matches
            # when it appears in the question (e.g. "R10@1") OR the question
            # names the column's metric family — the KEHNN corpus stores the
            # first header as a row offset, so its short label ("R2@1") can
            # otherwise be missed entirely. An explicit metric token
            # (R<n>@k) pins the trace to that column alone so a nearby
            # caption-only table cannot dilute the authoritative trace.
            focused: list[str] = []
            for col in numeric_cols:
                col_lower = col.strip().lower()
                if selected_metric is not None:
                    if col_lower == selected_metric:
                        focused.append(col)
                    continue
                if col_lower and (
                    col_lower in query_lower
                    or query_lower in col_lower
                    or any(part and part in query_lower for part in col_lower.replace("@", " ").split())
                ):
                    focused.append(col)
            if not focused and any(w in query_lower for w in ("best", "highest", "lowest", "most", "rank", "top", "winning")):
                # A broad "which model is best" question should expose every
                # numeric metric, so the model can verify consistency across
                # the table instead of seeing only an arbitrary first column.
                focused = numeric_cols
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


def _selected_metric_label(query: str) -> str | None:
    """Explicit ``R<n>@k`` metric token named in the question, if any.

    A question pinning one metric ("highest R2@1") must trace that column
    alone; multi-metric traces on the same table dilute the authoritative
    signal when caption-only neighbor tables share the bundle.
    """
    import re

    match = re.search(r"\br\s*(\d+)\s*@\s*(\d+)\b", query or "", re.IGNORECASE)
    if not match:
        return None
    return f"r{match.group(1)}@{match.group(2)}"


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
