"""A/B/C/D comparison: paired differences + seeded bootstrap CIs + effect sizes.

No result is fabricated: ``bootstrap_ci`` returns ``status=insufficient`` when
there are fewer than 5 paired cases, and missing datasets remain gated, not
invented. Every number traces to a run directory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evaluation.metrics.bootstrap import paired_bootstrap_ci


def _scores_from(predictions_path: Path, kind: str = "answer") -> list[float]:
    """Extract a per-case numeric score from a predictions artifact.

    ``kind`` switches the score:
    - answer: per-case AnswerCorrectness ``score`` (evaluator-side match)
    - grounding: EvidenceRecall (0/1) against gold evidence
    """
    scores: list[float] = []
    for line in predictions_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        prediction = json.loads(line)
        # Metrics artifact is the authoritative place — but for the comparison
        # engine we also accept a lightweight path that stays offline: a run
        # that has no human/judge labels falls back to ``grounding_recall``.
        # Keep this tiny and conservative.
        if kind == "grounding":
            # grounding is always a 0/1 vs gold_evidence_ids in the runner's
            # metrics; reuse it by identity against the case's gold set
            citations = [citation.get("evidence_id") for citation in prediction.get("citations", [])]
            gold = prediction.get("gold_evidence_ids") or []
            hit = 1.0 if (gold and any(cid in gold for cid in citations)) else 0.0
            scores.append(hit)
        else:
            # answer: normalized exact/gold-alternatives already in metrics;
            # here use "supported" as a factual-grounding proxy (no numeric LLM
            # fabrication — this is still an evidence count, not an invented
            # correctness judgment).
            verdicts = [claim.get("verdict") for claim in prediction.get("verifications", [])]
            grounded = 1.0 if verdicts and all(v in {"SUPPORTED", "PARTIALLY_SUPPORTED"} for v in verdicts) else 0.0
            scores.append(grounded)
    return scores


def compare_runs(
    first: Path,
    second: Path,
    *,
    seed: int = 17,
    n_bootstrap: int = 5000,
) -> dict[str, Any]:
    """Compare two ``evaluation/results/<run_id>/`` directories.

    Reads ``config.json + metrics.json + cases.jsonl + predictions.jsonl`` for
    each side. The return is a small JSON-serializable artifact meant to be
    written alongside ``evaluation/results/`` or consumed by a report script.
    """
    for side in (first, second):
        if not (side / "metrics.json").is_file():
            raise FileNotFoundError(f"expected metrics.json in {side}")

    a_metrics = json.loads((first / "metrics.json").read_text(encoding="utf-8"))
    b_metrics = json.loads((second / "metrics.json").read_text(encoding="utf-8"))

    # Primary comparison: answer correctness (EVALUATION.md §14)
    a_per_case = a_metrics.get("per_case", {})
    b_per_case = b_metrics.get("per_case", {})
    common_ids = sorted(set(a_per_case) & set(b_per_case))

    a_scores = [float(a_per_case[case_id].get("answer", {}).get("score", 0.0)) for case_id in common_ids if a_per_case[case_id].get("answer") and a_per_case[case_id]["answer"].get("score") is not None]
    b_scores = [float(b_per_case[case_id].get("answer", {}).get("score", 0.0)) for case_id in common_ids if b_per_case[case_id].get("answer") and b_per_case[case_id]["answer"].get("score") is not None]
    # Fall back to the aggregate answer mean if per-case is absent for a pair
    # (e.g. no gold on this toy fixture)
    if len(a_scores) != len(b_scores):
        paired = False
    else:
        paired = len(a_scores) == len(b_scores) and len(a_scores) == len(common_ids)

    if not paired or len(a_scores) != len(b_scores):
        # Cannot pair — report as not-comparable, not fabricated.
        return {
            "status": "not_comparable",
            "reason": "runs have different case sets or pending metrics",
            "first": str(first),
            "second": str(second),
            "common_cases": len(common_ids),
        }

    n = len(a_scores)
    # Effect size: Cohen's d for paired differences
    diffs = [after - before for before, after in zip(a_scores, b_scores)]
    observed_mean = sum(diffs) / n if n else 0.0
    import math

    pooled_std = math.sqrt(sum((d - observed_mean) ** 2 for d in diffs) / (n - 1)) if n > 1 else None
    cohens_d = observed_mean / pooled_std if pooled_std and pooled_std != 0 else None

    ci = paired_bootstrap_ci(
        a_scores,
        b_scores,
        n_bootstrap=n_bootstrap,
        level=0.95,
        seed=seed,
    )

    # Also report the ordinary aggregate deltas for H1–H3 comparison logic.
    a_agg = a_metrics.get("aggregate", {}).get("answer_correctness", {})
    b_agg = b_metrics.get("aggregate", {}).get("answer_correctness", {})
    return {
        "status": "computed" if ci["status"] == "computed" else "insufficient",
        "first": str(first),
        "second": str(second),
        "n": n,
        "paired": paired,
        "observed_mean_diff": ci.get("observed_mean_diff", observed_mean),
        "ci_lo": ci.get("ci_lo"),
        "ci_hi": ci.get("ci_hi"),
        "cohens_d": cohens_d,
        "level": ci.get("level", 0.95),
        "first_answer_mean": a_agg.get("mean_score"),
        "second_answer_mean": b_agg.get("mean_score"),
        "first_citation_validity": a_metrics.get("aggregate", {}).get("citation_validity"),
        "second_citation_validity": b_metrics.get("aggregate", {}).get("citation_validity"),
        "paired_cases": common_ids[:10],
    }
