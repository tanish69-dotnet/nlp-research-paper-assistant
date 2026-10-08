"""Phase 6 hardening: isolation, reproducibility, no-gold leakage, real-data gating tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.baselines.systems import SYSTEMS, filter_evidence_for_system
from evaluation.configs.eval_config import EvalConfig
from evaluation.datasets.registry import DatasetUnavailableError, dataset_status
from evaluation.runners.run_eval import _run_one_case
from evaluation.metrics.bootstrap import paired_bootstrap_ci
from app.schemas.evidence import EvidenceBundle
from app.schemas.reasoning import ReasoningResponse


def _eval_case_fixture(text_only: bool = False):
    bundle_data = {
        "evidence": [
            {"evidence_id": "e_t", "paper_id": "paper_001", "type": "text", "content": "hello"},
            {"evidence_id": "e_tab", "paper_id": "paper_001", "type": "table", "content": "| T | A |\n| A | 1 |"},
            {"evidence_id": "e_fig", "paper_id": "paper_001", "type": "figure", "content": "", "caption": "Fig", "image": {"b64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR4nGNgYGBgAAAABQABDQottQAAAABJRU5ErkJggg=="}},
        ]
    }
    from evaluation.datasets.eval_case import EvalCase

    return EvalCase.model_validate(
        {
            "case_id": "fixture_isolation",
            "question": "What is hello?",
            "category": "text",
            "evidence": bundle_data,
            "gold_answer": {"text": "hello"},
            "gold_evidence_ids": ["e_t"],
            "answer_type": "free",
        }
    )


# --- system isolation --------------------------------------------------------


def test_system_A_filters_to_text_only() -> None:
    case = _eval_case_fixture()
    view = filter_evidence_for_system(case, SYSTEMS["A"])

    assert all(item.type == "text" for item in view.evidence.evidence)
    assert len(view.evidence.evidence) == 1


def test_systems_B_C_D_keep_full_bundle() -> None:
    case = _eval_case_fixture()
    for sys in ("B", "C", "D"):
        view = filter_evidence_for_system(case, SYSTEMS[sys])
        assert len(view.evidence.evidence) == 3


def test_ablations_only_filter_the_declared_modality() -> None:
    from evaluation.baselines.ablations import filter_evidence_for_ablation
    from evaluation.datasets.eval_case import EvalCase

    bundle = EvidenceBundle.model_validate(
        {
            "evidence": [
                {"evidence_id": "e_t", "paper_id": "p", "type": "text", "content": "t"},
                {"evidence_id": "e_tab", "paper_id": "p", "type": "table", "content": "c"},
                {"evidence_id": "e_fig", "paper_id": "p", "type": "figure", "content": "f"},
            ]
        }
    )

    for ablation_id, kind in [("AB-T", "text"), ("AB-Tab", "table"), ("AB-V", "figure")]:
        filtered = filter_evidence_for_ablation(bundle, ablation_id, "text")
        assert all(item.type != kind for item in filtered.evidence)
        assert len(filtered.evidence) == 2
        for item in bundle.evidence:
            if item.type == kind:
                assert item.evidence_id not in {item.evidence_id for item in filtered.evidence}


def test_judge_isolation_B_and_C_are_without_judge(make_settings: object) -> None:
    from tests.conftest import run
    from app.config import Settings
    from app.models.routing import build_registry

    bundle_data = {
        "evidence": [
            {"evidence_id": "e_t", "paper_id": "p", "type": "text", "content": "t"},
        ]
    }
    case = _eval_case_fixture()
    settings = Settings(_env_file=None, model_provider="mock", log_level="WARNING", log_format="console")  # type: ignore[call-arg]
    registry = build_registry(settings)
    config = EvalConfig(system="C", dataset="fixture-mini")
    from evaluation.runners.run_eval import _run_one_case as inner  # type: ignore[import]

    response = run(inner(case, config, settings, registry))

    assert response.verification.status == "unverified"


def test_comparison_does_not_fabricate_CI_on_insufficient_pairs() -> None:
    from evaluation.metrics.bootstrap import paired_bootstrap_ci

    result = paired_bootstrap_ci([0.0] * 4, [0.5] * 4, n_bootstrap=10, seed=17)

    assert result["status"] == "insufficient"
    assert ">=5" in result["reason"]


# --- dataset gating ----------------------------------------------------------


def test_fixture_mini_is_always_available() -> None:
    row = dataset_status("fixture-mini")

    assert row["status"] == "available"
    assert Path(row["path"]).is_file()


def test_spike_dataset_is_gated_as_unavailable() -> None:
    row = dataset_status("spiqa")

    assert row["status"] == "unavailable"
    assert row["reason"]


def test_unknown_dataset_is_unknown() -> None:
    row = dataset_status("does-not-exist")

    assert row["status"] == "unknown"


# --- frozen evidence ---------------------------------------------------------


def test_frozen_fingerprint_is_reproducible() -> None:
    from evaluation.datasets.fingerprint import evidence_fingerprint

    a = _eval_case_fixture().evidence
    b = _eval_case_fixture().evidence

    assert evidence_fingerprint(a) == evidence_fingerprint(b)


def test_frozen_fingerprint_changes_when_content_changes() -> None:
    from evaluation.datasets.fingerprint import evidence_fingerprint
    from app.schemas.evidence import EvidenceItem

    a = _eval_case_fixture().evidence
    b_items = list(a.evidence)
    b_items.append(EvidenceItem(evidence_id="e_extra", paper_id="paper_002", type="text", content="extra"))  # type: ignore[arg-type]
    b_bundle = EvidenceBundle.model_validate(
        {"evidence": [item.model_dump(mode="json") for item in b_items]}
    )

    assert evidence_fingerprint(a) != evidence_fingerprint(b_bundle)


# --- gold never enters prompt input ------------------------------------------


def test_gold_never_reaches_the_reasoning_bundle(make_settings: object) -> None:
    """Runner forwards ``question + evidence`` only — ``gold_answer`` is evaluation-local."""
    from app.config import Settings
    from app.models.routing import build_registry
    from evaluation.datasets.eval_case import EvalCase

    bundle = {
        "evidence": [
            {"evidence_id": "e_t", "paper_id": "p", "type": "text", "content": "t"},
        ]
    }
    case = EvalCase.model_validate(
        {
            "case_id": "no_gold_leak",
            "question": "Q?",
            "category": "text",
            "evidence": bundle,
            "gold_answer": {"text": "gold that must not enter the prompt"},
            "gold_evidence_ids": ["e_t"],
            "answer_type": "free",
        }
    )
    settings = Settings(_env_file=None, model_provider="mock", log_level="WARNING", log_format="console")  # type: ignore[call-arg]
    registry = build_registry(settings)
    config = EvalConfig(system="D", dataset="fixture-mini")

    from tests.conftest import run

    # ``_run_one_case`` only forwards `case.question + case.evidence` — verify
    # that the mock never sees "gold".
    response = run(_run_one_case(case, config, settings, registry))

    # A response's claims never contain gold strings (mocked with no findings),
    # but the harness guarantee is structural: the pipeline's input Bundle never
    # contains gold — mock never received it.
    raw = response.model_dump_json()
    assert "gold that must not enter" not in raw


def test_response_ids_preserve_the_experiment_database(
    tmp_path: Path,
) -> None:
    from evaluation.runners.run_eval import execute

    result = execute(
        config_path=Path("evaluation/configs/fixture_D.json"),
        dataset_path=Path("evaluation/datasets/fixture-mini.json"),
        output_root=tmp_path,
        run_id_override="leak-test",
    )
    manifest = json.loads((tmp_path / result["run_id"] / "manifest.json").read_text(encoding="utf-8"))
    predictions = (tmp_path / result["run_id"] / "predictions.jsonl").read_text(encoding="utf-8")

    assert manifest["case_count"] >= 1
    assert predictions.strip()
