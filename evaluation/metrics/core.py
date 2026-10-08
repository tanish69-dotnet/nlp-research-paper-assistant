"""Deterministic, conservative metric suite (EVALUATION.md §6).

Where ground truth is absent — e.g. human-judged labels for §6.5, per-sentence
answer segmentation for §6.4 — a metric emits ``"not_available"`` instead of a
fabricated score. Zero denominators never produce NaN.
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Literal

from app.schemas.claims import Claim
from app.schemas.reasoning import Citation, ReasoningResponse
from app.schemas.verification import ClaimVerification, Verdict
from evaluation.datasets.eval_case import EvalCase

Status = Literal["not_available", "computed"]


def _eq(a: str, b: str) -> bool:
    return a.strip().lower() == b.strip().lower()


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    aligned = sorted(values)
    position = math.ceil(p / 100 * len(aligned)) - 1
    index = max(0, min(position, len(aligned) - 1))
    return aligned[index]


# --- 6.1 Answer correctness -------------------------------------------------


def answer_correctness_score(
    predicted: str, gold: str | None, *, alternatives: list[str] | None = None
) -> dict[str, Any]:
    """Normalised exact/mixed match against the gold answers.

    ``score: 1.0`` when ``predicted`` matches any gold form (whitespace- and
    case-insensitive); ``0.0`` otherwise. The harness also records secondary
    *presence* signals (gold present, alternatives present) so later LLM-as-
    judge or human calibration can overlay.
    """
    if gold is None:
        return {"status": "not_available", "score": None, "reason": "no gold answer"}

    candidates = [gold] + list(alternatives or [])
    correct = any(_eq(predicted, form) for form in candidates)
    return {
        "status": "computed",
        "correct": correct,
        "score": 1.0 if correct else 0.0,
        "alternatives": len(alternatives or []),
    }


def answer_correctness_for_case(case: EvalCase, response: ReasoningResponse) -> dict[str, Any]:
    gold = case.gold_answer.text if case.gold_answer else None
    alternatives = case.gold_answer.alternatives if case.gold_answer else []
    return answer_correctness_score(response.answer, gold, alternatives=alternatives)


# --- 6.2 Evidence grounding -------------------------------------------------


def evidence_grounding(
    citations: list[Citation], gold_ids: list[str], claims: list[Claim] | None = None
) -> dict[str, Any]:
    """Evidence Recall/Precision against ``gold_evidence_ids`` (EVALUATION.md §6.2).

    ``Grounded-Claim-Ratio`` is (``SUPPORTED / total claims``) where
    ``Claim.verification`` is populated (judge path).
    """
    if not gold_ids:
        evidence_section: dict[str, Any] = {
            "status": "not_available",
            "evidence_recall": None,
            "evidence_precision": None,
            "gold_size": 0,
            "cited_size": len(citations),
        }
    else:
        cited = {citation.evidence_id for citation in citations}
        gold = set(gold_ids)
        recalled = len(cited & gold)
        evidence_section = {
            "status": "computed",
            "evidence_recall": recalled / len(gold) if gold else None,
            "evidence_precision": (recalled / len(cited)) if cited else 0.0,
            "gold_size": len(gold),
            "cited_size": len(cited),
            "recall_hits": recalled,
        }

    if claims is not None and claims:
        supported = sum(1 for claim in claims if claim.verification is not None and claim.verification.verdict == "SUPPORTED")
        evidence_section["grounded_claim_ratio"] = supported / len(claims)
        evidence_section["supported_claims"] = supported
        evidence_section["claim_count"] = len(claims)
    elif claims is not None:
        evidence_section["grounded_claim_ratio"] = None
        evidence_section["claim_count"] = 0

    return evidence_section


# --- 6.3 Citation correctness -----------------------------------------------


def citation_correctness(citations: list[Citation], bundle_ids: set[str]) -> dict[str, Any]:
    """Validity: every citation refers to evidence that was supplied (§6.3).

    Support scoring requires human/judge labels and is not fabricated here.
    """
    if not citations:
        return {"status": "computed", "validity": 1.0, "total": 0, "valid": 0, "invalid": 0}
    valid = sum(1 for citation in citations if citation.evidence_id in bundle_ids)
    return {
        "status": "computed",
        "validity": valid / len(citations) if citations else 1.0,
        "total": len(citations),
        "valid": valid,
        "invalid": len(citations) - valid,
    }


# --- 6.4 Unsupported-claim rate ---------------------------------------------


def unsupported_claim_rate(
    verifications: list[ClaimVerification] | None,
    claims: list[Claim] | None,
) -> dict[str, Any]:
    """Fraction of claims that failed verification (§6.4, UCR/AHR proxy).

    When verification is absent (pre-judge runs), the harness returns
    ``not_available`` rather than inventing a rate.
    """
    source = verifications
    if source is None and claims is not None:
        source = [claim.verification for claim in claims if claim.verification is not None]  # type: ignore[assignment]

    if not source:
        return {"status": "not_available", "ucr": None, "total": 0, "unsupported": 0, "contradicted": 0}

    total = len(source)
    contradicted = sum(1 for v in source if v.verdict == "CONTRADICTED")  # type: ignore[attr-defined]
    unsupported = sum(1 for v in source if v.verdict == "UNSUPPORTED")  # type: ignore[attr-defined]
    return {
        "status": "computed",
        "ucr": (unsupported + contradicted) / total if total else None,
        "unsupported_rate": unsupported / total if total else None,
        "contradicted_rate": contradicted / total if total else None,
        "total": total,
        "unsupported": unsupported,
        "contradicted": contradicted,
    }


# --- 6.5 Judge precision/recall ---------------------------------------------


def judge_precision_recall(
    gold_verdicts: dict[str, Verdict] | None,
    predicted: list[ClaimVerification],
) -> dict[str, Any]:
    """Precision/recall per verdict class against a gold subset (§6.5).

    Expected there to be *no* gold — until a human labeling pass has been run.
    """
    if gold_verdicts is None or not predicted:
        return {"status": "not_available", "per_class": {}, "micro": None, "total": len(predicted)}

    per_class: dict[str, dict[str, Any]] = {}
    overall_tp = 0
    overall_mismatch = 0

    for verdict_class in ("SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONTRADICTED"):
        tp = sum(1 for v in predicted if gold_verdicts.get(v.claim_id) == verdict_class and v.verdict == verdict_class)
        predicted_n = sum(1 for v in predicted if v.verdict == verdict_class)
        gold_n = sum(1 for v in gold_verdicts.values() if v == verdict_class)
        overall_tp += tp
        overall_mismatch += predicted_n - tp
        per_class[verdict_class] = {
            "tp": tp,
            "predicted": predicted_n,
            "gold": gold_n,
            "precision": tp / predicted_n if predicted_n else None,
            "recall": tp / gold_n if gold_n else None,
        }

    return {
        "status": "computed",
        "per_class": per_class,
        "micro": overall_tp / (overall_tp + overall_mismatch) if (overall_tp + overall_mismatch) else None,
        "total": len(predicted),
    }


# --- 6.6 Latency / cost ------------------------------------------------------


def latency(timings_ms: list[dict[str, int]]) -> dict[str, Any]:
    """Collect per-stage and total p50/p95 as well as token hints (§6.6).

    ``timings_ms`` is typically ``[result.metadata.timings_ms for result in responses]``.
    """
    if not timings_ms:
        return {"status": "not_available"}

    totals = [int(v) for v in [int(entry.get("total", 0)) for entry in timings_ms] if v is not None]
    analyze = [int(v) for v in [int(entry.get("analyze", 0)) for entry in timings_ms] if v is not None]
    agents = [int(v) for v in [int(entry.get("agents", 0)) for entry in timings_ms] if v is not None]
    verify = [int(v) for v in [int(entry.get("verify", 0)) for entry in timings_ms] if v is not None]
    generate = [int(v) for v in [int(entry.get("generate", 0)) for entry in timings_ms] if v is not None]

    def _block(values: list[int]) -> dict[str, Any]:
        non_negative = [max(0, value) for value in values]
        if not non_negative:
            return {"p50": None, "p95": None, "mean": None, "n": len(values)}
        # Keep p50/p95 meaningful on tiny fixture wall_ms; ``all==0`` is still a
        # legitimate measurement (mock is fast), not "not_available".
        return {
            "p50": _percentile([float(value) for value in non_negative], 50),
            "p95": _percentile([float(value) for value in non_negative], 95),
            "mean": statistics.fmean(non_negative) if sum(non_negative) >= 0 else None,
            "n": len(values),
        }

    return {
        "status": "computed",
        "total": _block(totals),
        "analyze": _block(analyze),
        "agents": _block(agents),
        "verify": _block(verify),
        "generate": _block(generate),
    }


# --- 6.7 Agent agreement (Cohen/Fleiss surrogate) ---------------------------


def agent_agreement(
    claim_counts_by_agent: dict[str, int] | None = None,
    *,  # when a gold-consistent label is unavailable, report gracefully
    status_reason: str | None = None,
) -> dict[str, Any]:
    """Minimal agreement signal.

    Real kappa statistics require overlapping decisions; until per-claim labels
    carry a second source, the harness exposes ``claim_counts_by_agent`` counts
    instead of a fabricated kappa.
    """
    if not claim_counts_by_agent:
        return {"status": "not_available", "reason": status_reason or "no per-claim labels yet"}
    return {"status": "computed", "claim_counts_by_agent": claim_counts_by_agent}


# --- aggregate for a suite ---------------------------------------------------


def suite_metrics(
    cases: list[EvalCase],
    predictions: list[ReasoningResponse],
    bundle_ids_by_case: dict[str, set[str]] | None = None,
    *,
    gold_verdicts_by_case: dict[str, dict[str, Verdict]] | None = None,
    seed: int = 17,
) -> dict[str, Any]:
    """Assemble the EVALUATION.md §6 metric matrix for a full run."""
    per_case: dict[str, Any] = {}

    # Bundle ids per run — fallback to the case's own bundle.
    evidence_bundle_ids_by_case: dict[str, set[str]] = bundle_ids_by_case or {}
    for case in cases:
        ids = {item.evidence_id for item in case.evidence.evidence}
        evidence_bundle_ids_by_case.setdefault(case.case_id, ids)

    # Per-case entries (also useful for a per-case CSV export).
    for case in cases:
        predicted = next(
            (prediction for prediction in predictions if prediction.request_id.startswith(case.case_id) or prediction.request_id == case.case_id),
            None,
        )
        if predicted is None:
            continue
        per_case[case.case_id] = {
            "answer": answer_correctness_for_case(case, predicted),
            "grounding": evidence_grounding(predicted.citations, case.gold_evidence_ids, predicted.claims),
            "citation_validity": citation_correctness(
                predicted.citations, evidence_bundle_ids_by_case[case.case_id]
            ),
        }

    # Aggregate: macro mean answer score; unsupported rate across all claims, etc.
    answer_scores = [
        entry["answer"]["score"] for entry in per_case.values() if entry["answer"].get("status") == "computed" and entry["answer"].get("score") is not None
    ]
    all_verifications: list[ClaimVerification] = []
    all_claims: list[Claim] = []
    all_timings: list[dict[str, int]] = []
    for prediction in predictions:
        all_claims.extend(list(prediction.claims))
        all_verifications.extend(list(prediction.verification.verdict if hasattr(prediction.verification, "verdict") else []))  # noqa: E501 type: ignore[arg-type]
        if hasattr(prediction, "metadata") and prediction.metadata:
            timings_ms = prediction.metadata.timings_ms or {}  # type: ignore[attr-defined]
            if timings_ms:
                all_timings.append(dict(timings_ms))

    return {
        "per_case": per_case,
        "aggregate": {
            "answer_correctness": {
                "status": "computed" if answer_scores else "not_available",
                "mean_score": statistics.fmean(answer_scores) if answer_scores else None,
                "n": len(answer_scores),
            },
            "unsupported_claim_rate": unsupported_claim_rate(
                [item.verification for item in all_claims if item.verification is not None],  # type: ignore[arg-type]
                all_claims,
            ),
            "citation_validity": citation_correctness(
                [citation for prediction in predictions for citation in prediction.citations],
                {eid for ids in evidence_bundle_ids_by_case.values() for eid in ids},
            ),
            "latency": latency(all_timings),
        }
    }
