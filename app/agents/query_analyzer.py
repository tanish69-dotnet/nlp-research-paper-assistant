"""Query Analyzer (ARCHITECTURE §4.1, PRD FR-1–FR-5).

Classifies the question, detects required modalities, binds explicit target
references ("Table 3", "Figure 5", ...), decomposes multi-part questions, and
emits a schema-validated :class:`QueryPlan`.

It NEVER answers the question — it only plans which agents should handle it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog

from app.agents.base import AgentContext, agent_error_from, complete_json, new_agent_run
from app.models.base import ModelProvider
from app.prompts.assembly import EvidenceContext, assemble_three_zone
from app.prompts.loader import PromptTemplate, load_prompt
from app.schemas.claims import AgentRun
from app.schemas.evidence import EvidenceItem
from app.schemas.query import AgentTask, QueryPlan, SubQuestion

logger = structlog.get_logger(__name__)

AGENT_NAME = "query_analyzer"
PROMPT_VERSION = "query_analyzer/v1"

# Deterministic reference hints: "Table 3", "table 4", "Figure 5", "fig. 2",
# "figure 1", "Section 4.2", "eq. 7", "equation 3". Kept deliberately narrow
# (DEVELOPMENT_PLAN Phase 2): hints only, the LLM binds semantics.
_REFERENCE_PATTERNS: dict[str, re.Pattern[str]] = {
    "table": re.compile(r"\btable\s+(\d+[A-Za-z]?(?:\.\d+)?)\b", re.IGNORECASE),
    "figure": re.compile(r"\b(?:figure|fig\.?)\s+(\d+[A-Za-z]?(?:\.\d+)?)\b", re.IGNORECASE),
    "section": re.compile(r"\bsection\s+(\d+(?:\.\d+)*)\b", re.IGNORECASE),
    "equation": re.compile(r"\b(?:equation|eq\.?)\s+(\d+[A-Za-z]?(?:\.\d+)?)\b", re.IGNORECASE),
}

_CANONICAL_PREFIX = {"table": "Table", "figure": "Figure", "section": "Section", "equation": "Equation"}
_PAPER_ID_REFERENCE_RE = re.compile(
    r"^\s*(?:arxiv:)?\d{4}\.\d{4,5}(?:v\d+)?\s*$", re.IGNORECASE
)

# Table-intent signals for questions that need structured table reasoning
# even without an explicit "Table N" token (best/worst, comparisons,
# deltas, row/column lookups). Kept narrow: comparative/superlative wording
# about reported values, scores, or methods.
_TABLE_INTENT_RE = re.compile(
    r"\b(?:"
    r"which\s+(?:method|model|system|approach|variant)\s+(?:perform(?:s|ed)?|achieve(?:s|d)?|has|have|is)\s+(?:the\s+)?(?:best|highest|lowest|top|worst)"
    r"|(?:best|highest|lowest|top|worst)\s+(?:method|model|system|approach|variant|value|score|result|f1|accuracy)"
    r"|compar(?:e|ison)(?:\s+\w+){0,3}\s+(?:values?|scores?|results?|rows?|columns?|methods?|models?)"
    r"|difference\s+between\s+(?:two\s+)?(?:reported\s+)?(?:scores?|values?|results?)"
    r"|what\s+(?:is|are)\s+the\s+difference\b"
    r"|summariz(?:e|e\s+the)\s+(?:table|results)"
    r"|(?:highest|lowest)\s+(?:value|score|f1|accuracy)"
    r"|across\s+papers"
    r")\b",
    re.IGNORECASE,
)


def _is_paper_id_reference(value: str) -> bool:
    """Paper identity is not a table/figure citation reference."""
    return bool(_PAPER_ID_REFERENCE_RE.match(value or ""))


def _remove_paper_ids_from_references(plan: QueryPlan) -> QueryPlan:
    """Normalize model plans that echo a paper ID as a target reference."""
    references = [ref for ref in plan.target_references if not _is_paper_id_reference(ref)]
    tasks = [
        task.model_copy(
            update={
                "target_references": [
                    ref for ref in task.target_references if not _is_paper_id_reference(ref)
                ]
            }
        )
        for task in plan.tasks
    ]
    changed = references != plan.target_references or any(
        before.target_references != after.target_references
        for before, after in zip(plan.tasks, tasks)
    )
    return plan.model_copy(update={"target_references": references, "tasks": tasks}) if changed else plan


@dataclass(frozen=True)
class ReferenceHint:
    """One deterministic reference mention found in the question text."""

    canonical: str  # e.g. "Table 3"
    kind: str  # table | figure | section | equation


def detect_reference_hints(question: str) -> list[ReferenceHint]:
    """Extract explicit references (``Table 3``, ``Figure 5``) from the question.

    Deterministic and conservative: returns what the text literally says, in
    order of first appearance, deduplicated. No semantics attached.
    """
    found: list[tuple[int, ReferenceHint]] = []
    for kind, pattern in _REFERENCE_PATTERNS.items():
        for match in pattern.finditer(question):
            canonical = f"{_CANONICAL_PREFIX[kind]} {match.group(1)}"
            found.append((match.start(), ReferenceHint(canonical=canonical, kind=kind)))
    found.sort(key=lambda item: item[0])
    seen: set[str] = set()
    hints: list[ReferenceHint] = []
    for _, hint in found:
        if hint.canonical not in seen:
            seen.add(hint.canonical)
            hints.append(hint)
    return hints


def has_table_intent(question: str) -> bool:
    """Whether the wording needs structured table reasoning (no Table N needed)."""
    return bool(_TABLE_INTENT_RE.search(question or ""))


def default_plan(question: str, paper_ids: list[str] | None = None) -> QueryPlan:
    """Conservative fallback when the model is unavailable or unusable.

    Uses deterministic hints only and routes everything through text with a
    low confidence, so the pipeline degrades honestly (ARCHITECTURE §4.7).
    Table-intent wording additionally routes a table task (same evidence,
    honest confidence) so best/worst/comparison questions reach TableAgent.
    """
    hints = detect_reference_hints(question)
    modalities: list[str] = []
    for hint in hints:
        if hint.kind == "table" and "table" not in modalities:
            modalities.append("table")
        elif hint.kind == "figure" and "figure" not in modalities:
            modalities.append("figure")
    if not modalities:
        modalities = ["text"]
    elif "text" not in modalities:
        modalities.append("text")
    if has_table_intent(question) and "table" not in modalities:
        modalities.insert(0, "table")

    tasks = [
        AgentTask(
            task="answer from supplied evidence",
            modality=modality,  # type: ignore[arg-type]
            target_references=[h.canonical for h in hints],
        )
        for modality in modalities
    ]
    return QueryPlan(
        question_type="other",
        required_modalities=modalities,  # type: ignore[arg-type]
        tasks=tasks,
        target_references=[h.canonical for h in hints],
        requires_cross_modal=len(modalities) > 1,
        paper_scope="any",
        paper_ids=list(paper_ids or []),
        sub_questions=[],
        confidence=0.4,
    )


def _hints_text(
    hints: list[ReferenceHint],
    evidence: tuple[EvidenceItem, ...],
    *,
    table_intent: bool = False,
) -> str:
    lines = ["Deterministic reference hints found in the question:"]
    if hints:
        lines.extend(f"- {hint.canonical} ({hint.kind})" for hint in hints)
    else:
        lines.append("- none")
    # Table-intent wording is a deterministic signal too: surface it so the
    # model binds best/worst/comparison questions to the table modality even
    # without an explicit "Table N" token.
    if table_intent:
        lines.append("- table-intent wording detected (best/worst/comparison/scores)")
    lines.append("")
    lines.append("Supplied evidence (ids and labels only — full text is analyzed by other agents):")
    if evidence:
        for item in evidence:
            label = item.reference or f"page {item.page}" if item.page else item.evidence_id
            lines.append(f"- {item.evidence_id}: type={item.type}, paper={item.paper_id}, label={label}")
    else:
        lines.append("- none")
    paper_ids = sorted({item.paper_id for item in evidence})
    lines.append("")
    lines.append(f"paper_ids in evidence: {paper_ids if paper_ids else 'none'}")
    return "\n".join(lines)


class QueryAnalyzer:
    """Classifies + decomposes the question into a :class:`QueryPlan`."""

    name = AGENT_NAME

    def __init__(self, provider: ModelProvider, *, prompt_version: str = "v1") -> None:
        self._provider = provider
        self._prompt_version = prompt_version
        self._template: PromptTemplate | None = None

    @property
    def provider_name(self) -> str:
        return self._provider.name

    def _template_loaded(self) -> PromptTemplate:
        if self._template is None:
            self._template = load_prompt("query_analyzer", self._prompt_version)
        return self._template

    async def analyze(
        self,
        ctx: AgentContext,
        evidence: tuple[EvidenceItem, ...] = (),
    ) -> tuple[QueryPlan, AgentRun]:
        """Produce a :class:`QueryPlan`, falling back honestly on failure."""
        import time

        started = time.perf_counter()
        hints = detect_reference_hints(ctx.query)
        template = self._template_loaded()

        user_content = (
            f"QUESTION:\n{ctx.query}\n\n"
            f"{_hints_text(hints, evidence, table_intent=has_table_intent(ctx.query))}"
        )
        messages = assemble_three_zone(template, user_content, evidence=[])
        # The analyzer only ever sees summaries (ids/labels), never evidence
        # bodies — cheaper and a smaller injection surface (ARCHITECTURE §4.1).
        system = messages[0].content
        user = messages[1].content

        try:
            payload, response = await complete_json(
                self._provider, system=system, user=user, ctx=ctx
            )
            plan = _remove_paper_ids_from_references(QueryPlan.model_validate(payload))
        except Exception as exc:  # noqa: BLE001 - fallback path is the contract
            logger.warning(
                "analyzer_fallback",
                component="agents",
                agent=self.name,
                error=f"{type(exc).__name__}: {exc}",
            )
            plan = default_plan(
                ctx.query, paper_ids=sorted({item.paper_id for item in evidence})
            )
            return plan, new_agent_run(
                self.name,
                ctx,
                status="degraded",
                started_s=started,
                evidence_ids_used=[],
                prompt_version=f"{self.name}/{template.version}",
                error=agent_error_from(exc),
            )

        return plan, new_agent_run(
            self.name,
            ctx,
            status="ok",
            started_s=started,
            findings=[],
            evidence_ids_used=[],
            prompt_version=f"{self.name}/{template.version}",
            usage_prompt_tokens=response.usage.prompt_tokens,
            usage_completion_tokens=response.usage.completion_tokens,
        )

    async def run(self, ctx: AgentContext) -> AgentRun:
        """Protocol entrypoint: plan for ``ctx.evidence``, keep the run record."""
        _, run_record = await self.analyze(ctx, ctx.evidence)
        return run_record
