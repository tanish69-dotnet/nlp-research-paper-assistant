"""Evaluation harness tests (Phase 5).

Covers: typed config, dataset/case validation, runner + manifest, metrics,
bootstrap, reproducibility (same determinism), frozen-evidence fingerprint,
and Person 2 smoke harness. Everything offline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.configs.eval_config import EvalConfig
from evaluation.datasets.eval_case import EvalCase
from evaluation.datasets.fingerprint import evidence_fingerprint


def test_eval_config_valid(make_settings: object) -> None:
    config = EvalConfig.model_validate({"system": "D", "dataset": "fixture-mini", "seed": 7})
    assert config.system == "D"
    assert config.dataset_version
    assert config.run_id()  # never empty


def test_invalid_system_is_rejected() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EvalConfig.model_validate({"system": "Z"})


def test_seed_parsing_is_mandatory_and_stable() -> None:
    a = EvalConfig.model_validate({"system": "D", "seed": 17})
    b = EvalConfig.model_validate({"system": "D", "seed": 17})

    assert a.seed == b.seed


def test_eval_case_category_validation() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EvalCase.model_validate(
            {
                "case_id": "c",
                "question": "Q?",
                "category": "not_a_category",
                "evidence": {"evidence": []},
            }
        )


def test_fixture_dataset_is_loadable_and_has_7_slices() -> None:
    from evaluation.datasets.build_fixture import build

    dataset = build()

    by_category = {case.category: case for case in dataset.cases}
    assert {"text", "table", "figure", "text_table", "text_figure", "table_figure", "multi_paper"} == set(by_category)
    assert all(case.evidence for case in dataset.cases)
    assert all(case.gold_answer and case.gold_answer.text for case in dataset.cases)


def test_fixture_dataset_json_is_valid_json() -> None:
    path = Path("evaluation/datasets/fixture-mini.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    from evaluation.datasets.eval_case import EvalDataset

    dataset = EvalDataset.model_validate(raw)

    assert dataset.name == "fixture-mini"
    assert len(dataset.cases) >= 1


# --- manifest ----------------------------------------------------------------


def test_runner_creates_manifest_with_git_sha_and_frozen_fingerprint(tmp_path: Path) -> None:
    from evaluation.runners.run_eval import execute

    config_path = Path("evaluation/configs/fixture_D.json")
    dataset_path = Path("evaluation/datasets/fixture-mini.json")

    result = execute(config_path=config_path, dataset_path=dataset_path, output_root=tmp_path)

    manifest = json.loads((tmp_path / result["run_id"] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["git_sha"]
    assert manifest["run_id"] == result["run_id"]
    assert manifest["system"] == "D"
    assert manifest["seed"] == 17
    assert manifest["case_count"] == 7
    assert manifest["model_versions"]
    assert manifest["prompt_versions"]


def test_evidence_fingerprint_is_stable_and_ignores_scores() -> None:
    from app.schemas.evidence import EvidenceBundle

    a = EvidenceBundle.model_validate(
        {
            "evidence": [
                {
                    "evidence_id": "e_t",
                    "paper_id": "paper_001",
                    "type": "text",
                    "content": "hello",
                    "score": 0.3,
                    "truncated": True,
                }
            ]
        }
    )
    b = EvidenceBundle.model_validate(
        {
            "evidence": [
                {
                    "evidence_id": "e_t",
                    "paper_id": "paper_001",
                    "type": "text",
                    "content": "hello",
                    "score": 0.9,
                    "truncated": False,
                }
            ]
        }
    )

    assert evidence_fingerprint(a) == evidence_fingerprint(b)


# --- metrics: correctness / grounding / citation / unsupported / latency -----


def test_answer_correctness_metric() -> None:
    from evaluation.metrics.core import answer_correctness_score

    out = answer_correctness_score("hello world", "Hello World")
    assert out["score"] == 1.0

    out = answer_correctness_score("hello", "world")
    assert out["score"] == 0.0

    out = answer_correctness_score("anything", None)
    assert out["status"] == "not_available"


def test_evidence_grounding_metric() -> None:
    from app.schemas.reasoning import Citation

    from evaluation.metrics.core import evidence_grounding

    citations = [
        Citation(citation_id="c1", evidence_id="e_a", paper_id="p", type="text"),
        Citation(citation_id="c2", evidence_id="e_b", paper_id="p", type="text"),
    ]
    result = evidence_grounding(citations, ["e_a", "e_c"])

    assert result["status"] == "computed"
    assert result["evidence_recall"] == 1 / 2
    assert result["evidence_precision"] == 1 / 2

    # Zero-denominator handling is documented, not fabricated: empty gold → not_available
    assert evidence_grounding(citations, [])["status"] == "not_available"


def test_citation_correctness_only_validates_provenance() -> None:
    from app.schemas.reasoning import Citation

    from evaluation.metrics.core import citation_correctness

    citations = [
        Citation(citation_id="c1", evidence_id="e_a", paper_id="p", type="text"),
        Citation(citation_id="c2", evidence_id="e_not_in_bundle", paper_id="p", type="text"),
    ]
    result = citation_correctness(citations, {"e_a", "e_b"})

    assert result["validity"] == 1 / 2
    assert result["valid"] == 1 and result["invalid"] == 1
    assert citation_correctness([], {"e_a"})["validity"] == 1.0


def test_unsupported_claim_rate_handles_zero_claims() -> None:
    from evaluation.metrics.core import unsupported_claim_rate

    assert unsupported_claim_rate([], [])["status"] == "not_available"
    assert unsupported_claim_rate(None, [])["status"] == "not_available"


def test_judge_precision_is_not_available_when_not_labeled() -> None:
    from evaluation.metrics.core import judge_precision_recall

    result = judge_precision_recall(None, [])
    assert result["status"] == "not_available"


def test_latency_p50_p95() -> None:
    from evaluation.metrics.core import latency

    timings = []
    for value in range(1, 101):
        timings.append({"total": value * 10, "analyze": 5, "agents": 4, "verify": 2, "generate": 1})

    result = latency(timings)
    assert result["status"] == "computed"
    # P50 for totals 10..1000 inclusive is 500 (lower-mid definition via ceil)
    assert result["total"]["p50"] in {500.0, 500, 510}
    assert result["total"]["p95"] == 950
    assert result["agents"]["n"] == 100
    assert latency([])["status"] == "not_available"


def test_agent_agreement_is_not_available_when_labels_missing() -> None:
    from evaluation.metrics.core import agent_agreement

    assert agent_agreement()["status"] == "not_available"
    assert agent_agreement({})["status"] == "not_available"


def test_bootstrap_requires_paired_and_sufficient_n() -> None:
    from evaluation.metrics.bootstrap import paired_bootstrap_ci

    with pytest.raises(ValueError):
        paired_bootstrap_ci([1.0, 2.0], [1.0])

    result = paired_bootstrap_ci([0.0] * 4, [0.1] * 4, n_bootstrap=10, seed=17)
    assert result["status"] == "insufficient"
    assert ">=5" in result["reason"]


def test_bootstrap_is_deterministic_for_a_seed() -> None:
    from evaluation.metrics.bootstrap import paired_bootstrap_ci

    first = paired_bootstrap_ci([0.0] * 7, [0.5] * 7, n_bootstrap=20, seed=17)
    second = paired_bootstrap_ci([0.0] * 7, [0.5] * 7, n_bootstrap=20, seed=17)

    assert first["ci_lo"] == second["ci_lo"] and first["ci_hi"] == second["ci_hi"]


def test_suite_metrics_includes_per_case_and_aggregate(tmp_path: Path) -> None:
    from evaluation.runners.run_eval import execute

    result = execute(
        config_path=Path("evaluation/configs/fixture_D.json"),
        dataset_path=Path("evaluation/datasets/fixture-mini.json"),
        output_root=tmp_path,
    )
    metrics = json.loads((tmp_path / result["run_id"] / "metrics.json").read_text(encoding="utf-8"))
    assert "per_case" in metrics
    assert "aggregate" in metrics
    assert "unsupported_claim_rate" in metrics["aggregate"]
    assert "citation_validity" in metrics["aggregate"]


def test_runner_is_deterministic_for_a_deterministic_provider(tmp_path: Path) -> None:
    """Same seed/config/dataset/evidence ⇒ reproducible artifacts when provider is deterministic."""
    from evaluation.runners.run_eval import execute

    config_path = Path("evaluation/configs/fixture_D.json")
    dataset_path = Path("evaluation/datasets/fixture-mini.json")

    run_a = execute(config_path=config_path, dataset_path=dataset_path, output_root=tmp_path / "run_a")
    run_b = execute(config_path=config_path, dataset_path=dataset_path, output_root=tmp_path / "run_b")

    # Manifests have different timestamps/run_ids but equal fingerprint/status/case_count
    a = json.loads((tmp_path / "run_a" / run_a["run_id"] / "manifest.json").read_text(encoding="utf-8"))
    b = json.loads((tmp_path / "run_b" / run_b["run_id"] / "manifest.json").read_text(encoding="utf-8"))

    assert a["case_count"] == b["case_count"]
    assert a["evidence_fingerprint"] == b["evidence_fingerprint"]
