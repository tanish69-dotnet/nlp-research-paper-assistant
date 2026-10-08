"""System adapters (EVALUATION.md §2/§3) — four systems sharing one code path."""

from __future__ import annotations

from dataclasses import dataclass

from evaluation.datasets.eval_case import Category, EvalCase
from evaluation.configs.eval_config import SystemId
from app.config import Settings

# Systems:
# A: text-only (flat chunks): runner strips table+figure evidence.
# B: multimodal RAG + single LLM: treated here as multi-agent prompt that
#    runs without the judge (same as C with judge off — spec line for B is a
#    future more general generic LLM path; today the harness exposes it via
#    "B as C with judge omitted" which matches the control point).
# C: multimodal multi-agent without judge
# D: multimodal multi-agent with judge


@dataclass(frozen=True)
class SystemDefinition:
    id: SystemId
    evidence: str  # text_only | multimodal
    multi_agent: bool
    judge: bool
    label: str
    # Phase 7: whether the run is effectively single-LLM (no multi-agent).
    single_agent_mode: bool = False

    @property
    def evidence_frozen_label(self) -> str:
        return f"system={self.id} evidence={self.evidence} multi_agent={self.multi_agent} judge={self.judge}" + (" single" if self.single_agent_mode else "")


SYSTEMS: dict[SystemId, SystemDefinition] = {
    "A": SystemDefinition("A", "text_only", False, False, "Baseline: text-only + single LLM", single_agent_mode=True),
    "B": SystemDefinition("B", "multimodal", False, False, "Multimodal RAG + single-LLM reasoning", single_agent_mode=True),
    "C": SystemDefinition("C", "multimodal", True, False, "Multimodal + multi-agent (no judge)"),
    "D": SystemDefinition("D", "multimodal", True, True, "Multimodal + multi-agent + judge"),
}

# Phase 6 ablations: each is a small, focused removal over D's frozen inputs.
ABLATIONS: dict[str, dict[str, object]] = {
    # id : {remove, label}
    "AB-T": {
        "remove": "text",
        "label": "Ablation AB-T — TextAgent removed",
        "expectation": "drop on text/definition/causal questions",
    },
    "AB-Tab": {
        "remove": "table",
        "label": "Ablation AB-Tab — TableAgent removed",
        "expectation": "drop on numeric/table questions",
    },
    "AB-V": {
        "remove": "figure",
        "label": "Ablation AB-V — VisionAgent removed",
        "expectation": "drop on figure/trend questions",
    },
    "AB-J": {
        "remove": "judge",
        "label": "Ablation AB-J — Judge removed (no verification)",
        "expectation": "hallucination and citation errors increase, latency decreases",
    },
    "AB-O": {
        "remove": "orchestration",
        "label": "Ablation AB-O — Multi-LLM orchestration removed (single generic LLM)",
        "expectation": "reproduces system B within noise",
    },
}

CATEGORY_SLICES: dict[Category, set[Category]] = {
    "text": {"text"},
    "table": {"table"},
    "figure": {"figure"},
    "text_table": {"text", "table"},
    "text_figure": {"text", "figure"},
    "table_figure": {"table", "figure"},
    "multi_paper": {"text", "table", "figure"},
}


def filter_evidence_for_system(case: EvalCase, system: SystemDefinition) -> EvalCase:
    """Map the case's evidence to the evidence view that system sees.

    Frozen: the *case*'s evidence stays the same object between conceptual
    systems; only the *view* differs (no re-retrieval).
    """
    if system.evidence == "multimodal":
        return case
    # A: text_only — drop multimodal types
    filtered = [item for item in case.evidence.evidence if item.type == "text"]
    from app.schemas.evidence import EvidenceBundle

    bundle = EvidenceBundle(
        query=case.evidence.query,
        papers=list(case.evidence.papers),
        evidence=filtered,
        retrieval=case.evidence.retrieval,
        warnings=list(case.evidence.warnings) + ["system A: multimodal types filtered as text_only"],
    )
    return EvalCase(
        case_id=case.case_id,
        question=case.question,
        category=case.category,
        evidence=bundle,
        papers=list(case.papers),
        gold_answer=case.gold_answer.model_copy() if case.gold_answer else None,
        gold_evidence_ids=list(case.gold_evidence_ids),
        gold_claims=list(case.gold_claims),
        answer_type=case.answer_type,  # type: ignore[arg-type]
        metadata=dict(case.metadata),
    )


def system_slice_contains(system: SystemDefinition, category: Category) -> bool:
    """Whether ``system`` is expected to see evidence that covers ``category``."""
    return True
