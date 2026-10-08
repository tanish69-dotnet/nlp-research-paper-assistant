"""Representative-failure artifact (Phase 6 §19) + category slices.

Produced from (cases + predictions + metrics.json) tuples that the runner has
already emitted — nothing new is fetched. Failure buckets derive from the
existing hallucination/judge tables (not from a fabricated LLM synthesis).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def top_failures(
    cases_path: Path,
    predictions_path: Path,
    metrics_path: Path,
    *,
    take: int = 10,
) -> list[dict[str, Any]]:
    """Map predictions that missed on a category to an artifact table."""
    cases = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    predictions = [json.loads(line) for line in predictions_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    per_case = metrics.get("per_case", {})

    failures: list[dict[str, Any]] = []
    for case in cases:
        prediction = next(
            (p for p in predictions if p.get("request_id") == case.get("case_id")),
            None,
        )
        bucket = per_case.get(case["case_id"], {}).get("answer", {})
        if not prediction or bucket.get("score") in {1.0, None}:
            continue
        failures.append(
            {
                "case_id": case["case_id"],
                "category": case.get("category"),
                "question": case.get("question"),
                "gold": case.get("gold_answer", {}).get("text"),
                "evidence_ids": case.get("gold_evidence_ids", []),
                "answer": prediction.get("answer"),
                "verification_status": prediction.get("verification", {}).get("status"),
                "error_type": bucket.get("status", "computed"),
            }
        )
    return failures[:take]


def write_error_analysis(run_dir: Path, *, take: int = 10) -> dict[str, Any]:
    """Collectors of the run's ``error_analysis.json`` (and its ``error_cases.jsonl`` slice)."""
    cases_path = run_dir / "cases.jsonl"
    predictions_path = run_dir / "predictions.jsonl"
    metrics_path = run_dir / "metrics.json"

    failures = top_failures(cases_path, predictions_path, metrics_path, take=take)
    by_category = Counter(entry["category"] for entry in failures)
    bundle = {
        "run_id": run_dir.name,
        "failures": failures,
        "by_category": dict(by_category),
        "n": len(failures),
    }

    (run_dir / "error_analysis.json").write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    (run_dir / "error_cases.jsonl").write_text(
        "\n".join(json.dumps(entry, ensure_ascii=False) for entry in failures), encoding="utf-8"
    )
    return bundle
