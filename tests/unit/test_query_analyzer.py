"""Query-analyzer tests (Phase 2).

The analyzer classifies questions, extracts explicit references, decomposes
multi-part questions and emits a validated QueryPlan — without answering.
"""

from __future__ import annotations

import json

from app.agents.base import AgentContext
from app.agents.query_analyzer import (
    QueryAnalyzer,
    default_plan,
    detect_reference_hints,
)
from app.models.mock import MockModelProvider
from tests.conftest import load_mock_evidence, run


def _valid_plan(**overrides: object) -> str:
    """JSON for a schema-valid QueryPlan (safe to return from the mock)."""
    base = {
        "question_type": "other",
        "required_modalities": ["text"],
        "tasks": [
            {
                "task": "answer from supplied evidence",
                "modality": "text",
                "target_references": [],
            }
        ],
        "target_references": [],
        "requires_cross_modal": False,
        "paper_scope": "any",
        "paper_ids": [],
        "sub_questions": [],
        "confidence": 0.9,
    }
    base.update(overrides)  # type: ignore[arg-type]
    return json.dumps(base)


# --- deterministic hints -----------------------------------------------------


def test_detects_table_and_figure_references() -> None:
    hints = detect_reference_hints("Which method in Table 3 beats Figure 5?")

    assert [hint.canonical for hint in hints] == ["Table 3", "Figure 5"]


def test_case_insensitive_and_abbreviations() -> None:
    hints = detect_reference_hints("As fig. 2 shows and table 4 reports…")

    assert [hint.canonical for hint in hints] == ["Figure 2", "Table 4"]


def test_section_and_equation_hints() -> None:
    hints = detect_reference_hints("See Section 4.2 and Equation 7 for context.")

    assert [hint.canonical for hint in hints] == ["Section 4.2", "Equation 7"]


def test_deduplicates_and_preserves_first_appearance() -> None:
    hints = detect_reference_hints("Table 3 then Table 3 again, then Figure 5")

    assert [hint.canonical for hint in hints] == ["Table 3", "Figure 5"]


def test_no_references_returns_empty() -> None:
    assert detect_reference_hints("What is overfitting?") == []


def test_default_plan_uses_deterministic_hints_only() -> None:
    question = "Which method performed best in Table 3, and why does Figure 5 drop?"
    plan = default_plan(question)

    assert plan.question_type == "other"
    assert "Table 3" in plan.target_references
    assert "Figure 5" in plan.target_references
    assert set(plan.required_modalities) == {"table", "figure", "text"}
    assert plan.requires_cross_modal is True
    assert plan.confidence == 0.4


def test_default_plan_without_hints_falls_back_to_text() -> None:
    plan = default_plan("What is overfitting?")

    assert plan.required_modalities == ["text"]
    assert plan.requires_cross_modal is False
    assert not plan.target_references


# --- analyzer with mock provider ---------------------------------------------

def _analyzer(provider: MockModelProvider = MockModelProvider()) -> QueryAnalyzer:
    return QueryAnalyzer(provider, prompt_version="v1")


def _ctx(
    question: str = "test question", evidence=None
) -> AgentContext:
    if evidence is None:
        evidence = tuple(load_mock_evidence()["evidence"])
        from app.schemas.evidence import EvidenceItem

        evidence = tuple(EvidenceItem.model_validate(item) for item in evidence)
    return AgentContext(
        request_id="test-1",
        query=question,
        evidence=evidence,  # type: ignore[arg-type]
        model="mock-model",
        provider_name="mock",
    )


def test_analyzer_text_question_produces_text_modality() -> None:
    provider = MockModelProvider(
        responses=[("text question", _valid_plan(question_type="definition", required_modalities=["text"]))]
    )
    ctx = _ctx("a simple text question about Abstract")
    plan, agent_run = run(QueryAnalyzer(provider).analyze(ctx, tuple(ctx.evidence)))  # type: ignore[arg-type]

    assert agent_run.status == "ok"
    assert plan.question_type == "definition"
    assert "text" in plan.required_modalities


def test_analyzer_recognizes_table_reference() -> None:
    provider = MockModelProvider(
        responses=[
            (
                "Table 4",
                _valid_plan(
                    question_type="numeric_lookup",
                    required_modalities=["table"],
                    target_references=["Table 4"],
                    requires_cross_modal=False,
                ),
            )
        ]
    )
    ctx = _ctx("What is the accuracy in Table 4?")
    plan, agent_run = run(QueryAnalyzer(provider).analyze(ctx))  # type: ignore[arg-type]

    assert agent_run.status == "ok"
    assert "table" in plan.required_modalities
    assert "Table 4" in plan.target_references


def test_analyzer_mixed_table_and_figure_is_cross_modal() -> None:
    provider = MockModelProvider(
        responses=[
            (
                "Table 3",
                _valid_plan(
                    question_type="cross_modal_comparison",
                    required_modalities=["text", "table", "figure"],
                    target_references=["Table 3", "Figure 5"],
                    requires_cross_modal=True,
                ),
            )
        ]
    )
    ctx = _ctx("Which method in Table 3 and why does Figure 5 drop?")
    plan, _ = run(QueryAnalyzer(provider).analyze(ctx))  # type: ignore[arg-type]

    assert plan.requires_cross_modal is True
    assert set(plan.target_references) == {"Table 3", "Figure 5"}


def test_analyzer_does_not_answer_the_question() -> None:
    """The plan's tasks carry instructions, not the final answer."""
    plan_text = json.dumps(
        {
            "question_type": "cross_modal_comparison",
            "required_modalities": ["table", "figure", "text"],
            "tasks": [
                {
                    "task": "compare methods in Table 3",
                    "modality": "table",
                    "target_references": ["Table 3"],
                },
                {
                    "task": "describe trend in Figure 5",
                    "modality": "figure",
                    "target_references": ["Figure 5"],
                },
            ],
            "target_references": ["Table 3", "Figure 5"],
            "requires_cross_modal": True,
            "paper_scope": "single",
            "paper_ids": ["paper_001"],
            "sub_questions": [
                {"id": "sq1", "text": "Which method performed best in Table 3?", "modalities": ["table"]},
                {"id": "sq2", "text": "Why does Figure 5 show a drop?", "modalities": ["figure", "text"]},
            ],
            "confidence": 0.85,
        }
    )
    provider = MockModelProvider(responses=[("Table 3", plan_text)])
    plan, _ = run(QueryAnalyzer(provider).analyze(_ctx("Which method in Table 3 and why Figure 5 drop?")))  # type: ignore[arg-type]

    assert all("91.4" not in task.task for task in plan.tasks), "analyzer must not copy numeric answers"


def test_analyzer_falls_back_when_model_returns_non_json() -> None:
    provider = MockModelProvider(responses=[("table", "not json at all")])
    ctx = _ctx("What is in Table 3?")
    plan, agent_run = run(QueryAnalyzer(provider).analyze(ctx))  # type: ignore[arg-type]

    assert agent_run.status == "degraded"
    assert plan.confidence == 0.4  # default plan confidence
    assert plan.target_references  # hints still captured


def test_analyzer_falls_back_on_provider_timeout() -> None:
    slow = MockModelProvider(delay_s=10.0)

    ctx = _ctx("Which method in Table 3?")
    # succeed once so fallback is observable with real evidence ids
    plan, agent_run = run(QueryAnalyzer(slow, prompt_version="v1").analyze(ctx))  # type: ignore[arg-type]

    # Mock timeout path: chat would time out given ctx.timeout_s=60, but
    # MockModelProvider timeout only fires when delay_s > ctx.timeout_s.
    # Build a ctx that will timeout quickly and a provider that delays.
    fast_timeout_ctx = AgentContext(
        request_id="t",
        query="Which method in Table 3?",
        evidence=ctx.evidence,
        model="m",
        provider_name="mock",
        timeout_s=0.05,
    )
    plan, agent_run = run(QueryAnalyzer(MockModelProvider(delay_s=0.2)).analyze(fast_timeout_ctx))  # type: ignore[arg-type]

    assert agent_run.status == "degraded"
    assert plan.question_type == "other"
