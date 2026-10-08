"""Category-sliced metric matrix (EVALUATION.md §13, §5).

Keeps overall and by-category slices in one artifact so a reader can tell
whether, say, TABLE degrades differently from MULTI-PAPER without hunting
through per-case files. Small function — only the runner's persisted payload
is read, never a new fetch/fetch of external data.
"""

from __future__ import annotations

from statistics import fmean
from typing import Any

from evaluation.datasets.eval_case import EvalCase


def _category_of(case: EvalCase) -> str:
    return str(case.category)


def add_category_slices(metrics: dict[str, Any], cases: list[EvalCase]) -> None:
    """Enrich a runner's ``metrics`` with per-category ``aggregate`` rows.

    Mutates ``metrics`` in place: inserts ``by_category[<category>]`` keys
    with per-case mean scores. No hallucination: when there is no gold for a
    category, rows are still emitted but with ``status: not_available``.
    """
    per_case = metrics.get("per_case", {})

    # Per-category mean answer score.
    groups: dict[str, list[float]] = {}
    for case in cases:
        entry = per_case.get(case.case_id, {})
        answer = entry.get("answer", {}) if isinstance(entry, dict) else {}
        score = answer.get("score")
        if score is None or not isinstance(score, (int, float)):
            continue
        groups.setdefault(_category_of(case), []).append(float(score))

    by_category: dict[str, Any] = {}
    for category, scores in sorted(groups.items()):
        by_category[category] = {
            "status": "computed",
            "mean_answer_score": fmean(scores) if scores else None,
            "n": len(scores),
        }

    # Also add a row with the categories that had no computable answers so the
    # matrix surfaces those as well (explicit not_available).
    for case in cases:
        category = _category_of(case)
        if category not in by_category:
            by_category[category] = {"status": "not_available", "mean_answer_score": None, "n": 0}

    metrics["by_category"] = by_category
