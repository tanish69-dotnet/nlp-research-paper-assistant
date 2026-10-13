"""Table-intent routing tests (explicit refs, paraphrases, comparisons).

Verifies that table-needing questions reach the table modality through both
the deterministic fallback (default_plan) and the intent signal surfaced to
the model (_hints_text), while text-only questions stay text-only.
"""

from __future__ import annotations

from app.agents.query_analyzer import (
    _hints_text,
    default_plan,
    detect_reference_hints,
    has_table_intent,
)


def test_explicit_table_reference_routes_table():
    plan = default_plan("What does Table 1 show?")

    assert "table" in plan.required_modalities
    assert "Table 1" in plan.target_references


def test_paraphrased_best_method_routes_table():
    plan = default_plan("Which method performs best?")

    assert "table" in plan.required_modalities


def test_implicit_comparison_routes_table():
    plan = default_plan("Compare the values in the two rows.")

    assert "table" in plan.required_modalities


def test_score_difference_routes_table():
    plan = default_plan("What is the difference between the two reported scores?")

    assert "table" in plan.required_modalities


def test_highest_lowest_routes_table():
    assert "table" in default_plan("Which method has the highest value?").required_modalities
    assert "table" in default_plan("Which method has the lowest F1?").required_modalities


def test_summarize_results_routes_table():
    plan = default_plan("Summarize the table results.")

    assert "table" in plan.required_modalities


def test_cross_paper_comparison_routes_table():
    plan = default_plan("Compare table results across papers.")

    assert "table" in plan.required_modalities


def test_text_only_question_stays_text():
    plan = default_plan("What is overfitting?")

    assert plan.required_modalities == ["text"]
    assert not plan.target_references


def test_definition_question_stays_text():
    assert not has_table_intent("What does attention mean in this context?")
    assert not has_table_intent("Explain the encoder architecture.")


def test_number_without_table_context_stays_text():
    # A bare number with no comparative/table wording must not route to table.
    assert not has_table_intent("What year was the paper published?")
    assert not has_table_intent("How many authors are listed?")


def test_hints_text_surfaces_table_intent():
    text = _hints_text(detect_reference_hints("Which method performs best?"), (), table_intent=True)

    assert "table-intent" in text


def test_hints_text_without_intent_has_no_table_line():
    text = _hints_text(detect_reference_hints("What is overfitting?"), ())

    assert "table-intent" not in text


def test_mixed_figure_table_question_routes_both():
    plan = default_plan("Compare Table 1 results with the trend in Figure 2.")

    assert "table" in plan.required_modalities
    assert "figure" in plan.required_modalities


def test_insufficient_table_evidence_marks_task_skipped():
    """Planner marks table tasks skipped (not failed) when no table evidence."""
    from app.orchestration.planner import plan_tasks
    from app.schemas.evidence import EvidenceBundle, EvidenceItem
    from app.config import Settings

    bundle = EvidenceBundle(
        evidence=[
            EvidenceItem(
                evidence_id="e_t",
                paper_id="p",
                type="text",
                content="Some prose without numbers.",
            )
        ]
    )
    plan = default_plan("Which method performs best?")
    settings = Settings(_env_file=None)

    tasks = plan_tasks(plan, bundle, settings)
    table_tasks = [t for t in tasks if t.modality == "table"]

    assert table_tasks
    assert all(t.status in {"skipped", "deferred"} for t in table_tasks)
    assert all("text_reasoner" != t.agent for t in table_tasks)
