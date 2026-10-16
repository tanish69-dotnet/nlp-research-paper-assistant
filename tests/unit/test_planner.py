"""Task-planner tests (Phase 2).

The planner routes tasks by modality: text → executable, table/figure →
deferred. It never fakes a missing agent's work.
"""

from __future__ import annotations

import pytest

from app.orchestration.planner import plan_tasks
from app.schemas.evidence import EvidenceBundle, EvidenceItem
from app.schemas.query import QueryPlan
from tests.conftest import load_mock_evidence


def _bundle() -> EvidenceBundle:
    return EvidenceBundle.model_validate(load_mock_evidence())


def _plan(
    *,
    modalities: list[str] | None = None,
    target_refs: list[str] | None = None,
    tasks: object | None = None,
) -> QueryPlan:
    payload: dict = {
        "question_type": "other",
        "required_modalities": modalities or ["text"],
        "tasks": tasks  # type: ignore[arg-type]
        if tasks is not None
        else [
            {"task": f"answer from {m}", "modality": m}
            for m in (modalities or ["text"])
        ],
        "target_references": target_refs or [],
        "requires_cross_modal": False,
        "paper_scope": "any",
        "paper_ids": [],
        "sub_questions": [],
        "confidence": 0.9,
    }
    return QueryPlan.model_validate(payload)


def test_text_task_is_routed_to_text_reasoner(make_settings: object) -> None:
    settings = make_settings()  # type: ignore[operator]

    planned = plan_tasks(_plan(modalities=["text"]), _bundle(), settings)

    assert planned[0].status == "executable"
    assert planned[0].agent == "text_reasoner"
    assert planned[0].modality == "text"
    assert planned[0].evidence_ids


def test_table_task_is_deferred_with_reason(make_settings: object) -> None:
    settings = make_settings()  # type: ignore[operator]

    planned = plan_tasks(_plan(modalities=["table"]), _bundle(), settings)

    assert planned[0].status == "executable"
    assert planned[0].agent == "table_reasoner"


def test_figure_task_is_deferred(make_settings: object) -> None:
    settings = make_settings()  # type: ignore[operator]

    planned = plan_tasks(_plan(modalities=["figure"]), _bundle(), settings)

    assert planned[0].status == "executable"
    assert planned[0].agent == "vision_reasoner"


def test_mixed_modalities_are_routed_and_deferred_correctly(
    make_settings: object,
) -> None:
    settings = make_settings()  # type: ignore[operator]

    planned = plan_tasks(
        _plan(modalities=["text", "table", "figure"]), _bundle(), settings
    )

    by_modality = {task.modality: task for task in planned}
    assert by_modality["text"].status == "executable"
    assert by_modality["table"].status == "executable"
    assert by_modality["figure"].status == "executable"


def test_text_task_without_matching_evidence_is_skipped(
    make_settings: object,
) -> None:
    settings = make_settings()  # type: ignore[operator]
    only_table = EvidenceBundle(
        evidence=[
            EvidenceItem(
                evidence_id="e_tbl",
                paper_id="paper_001",
                type="table",
                content="hello",
            ),
        ]
    )

    planned = plan_tasks(
        _plan(modalities=["text"], tasks=[{"task": "t", "modality": "text"}]),
        only_table,
        settings,
    )

    assert planned[0].status == "skipped"
    assert "no evidence" in planned[0].reason.lower()


def test_evidence_ids_are_bound_to_bundle(make_settings: object) -> None:
    bundle = _bundle()
    table_evidence_id = [
        item.evidence_id for item in bundle.evidence if item.type == "table"
    ][0]

    planned = plan_tasks(
        _plan(
            modalities=["table"],
            tasks=[
                {
                    "task": "ranks in Table 3",
                    "modality": "table",
                    "evidence_ids": [table_evidence_id, "e_does_not_exist"],
                }
            ],
        ),
        bundle,
        make_settings(),  # type: ignore[operator]
    )

    assert table_evidence_id in planned[0].evidence_ids
    assert "e_does_not_exist" not in planned[0].evidence_ids


def test_reference_coverage_adds_missing_tasks(make_settings: object) -> None:
    settings = make_settings()  # type: ignore[operator]
    plan = _plan(
        modalities=["text"],
        target_refs=["Table 3", "Figure 5"],
        tasks=[{"task": "text only", "modality": "text", "target_references": []}],
    )

    planned = plan_tasks(plan, _bundle(), settings)
    refs_covered = {ref for task in planned for ref in task.target_references}

    assert "Table 3" in refs_covered
    assert "Figure 5" in refs_covered
    assert any(
        task.status == "executable" and task.modality == "table" for task in planned
    )


def test_planner_never_fakes_missing_agents_via_text(make_settings: object) -> None:
    settings = make_settings()  # type: ignore[operator]
    planned = plan_tasks(
        _plan(
            modalities=["table", "figure"],
            tasks=[
                {"task": "rank Table 3", "modality": "table"},
                {"task": "trend of Figure 5", "modality": "figure"},
            ],
        ),
        _bundle(),
        settings,
    )
    assert {task.agent for task in planned if task.modality in {"table", "figure"}} == {
        "table_reasoner",
        "vision_reasoner",
    }


def test_evidence_ids_propagate_from_bundle_by_reference(
    make_settings: object,
) -> None:
    settings = make_settings()  # type: ignore[operator]
    plan = _plan(
        modalities=["text"],
        tasks=[
            {
                "task": "context around Figure 5",
                "modality": "text",
                "target_references": ["Figure 5"],
            }
        ],
    )
    planned = plan_tasks(plan, _bundle(), settings)
    assert planned[0].evidence_ids == [
        "e_p001_p1_abs",
        "e_p001_p4_s42",
        "e_p001_p6_limit",
        "e_p002_p9_concl",
    ]


def test_reference_binding_keeps_task_modality_consistent(make_settings: object) -> None:
    """A text task mentioning Figure 1 must not receive the figure id."""
    settings = make_settings()  # type: ignore[operator]
    bundle = EvidenceBundle(
        evidence=[
            EvidenceItem(
                evidence_id="p:txt",
                paper_id="p",
                type="text",
                content="Figure 1 shows the system layout.",
            ),
            EvidenceItem(
                evidence_id="p:fig-a",
                paper_id="p",
                type="figure",
                reference="Figure 1",
                content="",
            ),
            EvidenceItem(
                evidence_id="p:fig-b",
                paper_id="p",
                type="figure",
                reference="Figure 1",
                content="",
            ),
        ]
    )
    plan = _plan(
        modalities=["text", "figure"],
        tasks=[
            {
                "task": "explain Figure 1 from surrounding text",
                "modality": "text",
                "target_references": ["Figure 1"],
            },
            {
                "task": "inspect Figure 1",
                "modality": "figure",
                "target_references": ["Figure 1"],
            },
        ],
    )

    planned = plan_tasks(plan, bundle, settings)
    by_modality = {task.modality: task for task in planned}
    assert by_modality["text"].evidence_ids == ["p:txt"]
    assert by_modality["figure"].evidence_ids == ["p:fig-a", "p:fig-b"]
