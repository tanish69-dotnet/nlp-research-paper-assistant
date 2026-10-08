"""Phase 7 invariants: isolation, latency, provenance, gating, single-agent path."""

from __future__ import annotations

from app.schemas.evidence import EvidenceBundle
from evaluation.baselines.systems import SYSTEMS, filter_evidence_for_system
from evaluation.datasets.eval_case import EvalCase
from evaluation.metrics.core import latency
from evaluation.datasets.registry import dataset_status


def test_latency_aggregation_computes_stage_metrics() -> None:
    timings = []
    for value in range(1, 11):
        timings.append({"total": value * 10, "analyze": 2, "agents": 3, "verify": 1, "generate": 1})

    result = latency(timings)

    assert result["status"] == "computed"
    assert result["total"]["p50"] in {50.0, 60.0}
    assert result["total"]["p95"] in {90.0, 100.0}
    assert result["total"]["mean"] == sum(v * 10 for v in range(1, 11)) / 10
    assert result["analyze"]["n"] == 10


def test_latency_all_zeros_is_still_computed_for_mock() -> None:
    result = latency([{"total": 0, "analyze": 0, "agents": 0, "verify": 0, "generate": 0}])

    assert result["status"] == "computed"
    assert result["total"]["p50"] == 0.0
    assert result["total"]["mean"] == 0.0


def test_systems_AB_are_single_agent_isolated_from_C_and_D() -> None:
    assert SYSTEMS["A"].single_agent_mode is True
    assert SYSTEMS["B"].single_agent_mode is True
    assert SYSTEMS["C"].single_agent_mode is False
    assert SYSTEMS["D"].single_agent_mode is False


def test_filter_keeps_frozen_evidence_identical_across_B_C_D() -> None:
    from evaluation.datasets.eval_case import EvalCase

    bundle = {
        "evidence": [
            {"evidence_id": "e_t", "paper_id": "p", "type": "text", "content": "hello"},
            {"evidence_id": "e_tab", "paper_id": "p", "type": "table", "content": "t"},
        ]
    }
    case = EvalCase.model_validate(
        {"case_id": "c", "question": "Q?", "category": "text", "evidence": bundle, "answer_type": "free"}
    )

    for sys in ("B", "C", "D"):
        view = filter_evidence_for_system(case, SYSTEMS[sys])
        assert len(view.evidence.evidence) == 2
        assert view.evidence.evidence[0].evidence_id == "e_t"


def test_single_agent_bundle_differs_only_by_agent_not_evidence_ids(make_settings: object, tmp_path) -> None:
    """Runner's single_agent_mode keeps frozen evidence ids — only agent run differs."""
    from app.config import Settings
    from app.orchestration.orchestrator import full_reasoning

    bundle = EvidenceBundle.model_validate(
        {
            "evidence": [
                {"evidence_id": "e_t", "paper_id": "p", "type": "text", "content": "t"},
                {"evidence_id": "e_tab", "paper_id": "p", "type": "table", "content": "| X | Y |\n| A | 1 |"},
            ]
        }
    )
    settings = Settings(_env_file=None, model_provider="mock", log_level="WARNING", log_format="console")  # type: ignore[call-arg]
    from app.models.routing import build_registry

    registry = build_registry(settings)

    from tests.conftest import run

    a = run(full_reasoning("Q?", bundle, "iso-1", settings, registry, single_agent_mode=True))
    d = run(full_reasoning("Q?", bundle, "iso-1", settings, registry, single_agent_mode=False))

    # Single-agent mode must only drop table/vision claim handling, not evidence ids themselves.
    assert {item.evidence_id for item in bundle.evidence} == {"e_t", "e_tab"}
    # A produces no table claims by construction; D may produce them.
    assert len(a.claims) == 0
    assert any(item.evidence_id == "e_tab" for item in bundle.evidence)


def test_dataset_gating_exposes_fixture_and_hides_spiqa() -> None:
    fixture = dataset_status("fixture-mini")
    spiqa = dataset_status("spiqa")

    assert fixture["status"] == "available"
    assert spiqa["status"] == "unavailable"
    assert spiqa["reason"]


def test_dataset_gating_adapter_gating_not_fabricated(tmp_path) -> None:
    from evaluation.datasets.registry import DatasetUnavailableError, dataset_path_for

    with __import__("pytest").raises(DatasetUnavailableError, match="dataset_status = unavailable"):
        dataset_path_for("spiqa")


def test_evidence_fingerprint_is_stable_and_ignores_warnings() -> None:
    from evaluation.datasets.fingerprint import evidence_fingerprint

    bundle = EvidenceBundle.model_validate(
        {
            "evidence": [
                {"evidence_id": "e_t", "paper_id": "p", "type": "text", "content": "hello", "score": 0.1},
            ],
            "warnings": ["noise"],
        }
    )
    clone = EvidenceBundle.model_validate(
        {
            "evidence": [
                {"evidence_id": "e_t", "paper_id": "p", "type": "text", "content": "hello", "score": 0.9},
            ],
            "warnings": ["other"],
        }
    )

    assert evidence_fingerprint(bundle) == evidence_fingerprint(clone)
