"""Deterministic table operations (PRD §10, §6).

Small, well-scoped numeric helpers that run on structured ``TableData``
without an LLM. The LLM interprets the result — it never replaces it
(ARCHITECTURE Table reasoning hierarchy).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.schemas.evidence import TableData

# Known metric keywords that establish a direction.
_HIGHER_BETTER = frozenset(
    {
        "accuracy",
        "acc",
        "f1",
        "bleu",
        "rouge",
        "precision",
        "recall",
        "score",
        "mrr",
        "map",
        "hit",
        "ndcg",
        "auc",
        "f-measure",
        "spiqa-f1",
        "dev f1",
        "dev f1.",
        "dev-f1",
    }
)
_LOWER_BETTER = frozenset(
    {
        "loss",
        "perplexity",
        "error",
        "err",
        "latency",
        "time",
        "seconds",
        "ms",
        "params",
        "memory",
        "ppl",
        "wer",
    }
)

TC_ERROR = "table_computation_error"


@dataclass(frozen=True)
class TableResult:
    """Outcome of one deterministic table computation."""

    op: str  # best | worst | ranking | delta | lookup | error
    column: str
    evidence_id: str
    value: float | None = None
    label: str | None = None  # row header for the best/worst row
    higher_is_better: bool | None = None
    trace: list[str] = None  # type: ignore[assignment]
    detail: str = ""  # human-readable explanation
    extra: dict[str, Any] = None  # type: ignore[assignment]
    succeeded: bool = True

    def as_detail(self) -> str:
        return self.detail or self.trace[0] if self.trace else ""


def _normalize(s: str | None) -> str:
    return (s or "").strip().lower().replace("_", " ").replace("-", " ")


def _coerce_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    token = raw.strip().replace(",", "")
    # Strip common suffixes: "%", "s", "ms", etc. only when attached.
    for suffix in ("%", "s", "ms", "sec", "seconds"):
        if token.lower().endswith(suffix):
            token = token[: -len(suffix)].strip()
            break
    if token in {"", "-", "—", "n/a", "na", "none"}:
        return None
    try:
        return float(token)
    except ValueError:
        return None


def infer_metric_direction(caption: str | None, header: str | None) -> bool | None:
    """Heuristic direction inference from caption/header.

    Returns ``True`` (higher-is-better), ``False`` (lower-is-better), or
    ``None`` when ambiguous.
    """
    text = f"{_normalize(caption)} {_normalize(header)}"
    if re.fullmatch(r"r\s*\d+\s*@\s*\d+", _normalize(header)):
        return True
    if any(keyword in text for keyword in _HIGHER_BETTER):
        # disambiguate "error" vs "accuracy" when both appear — error wins
        if any(k in text for k in _LOWER_BETTER) and "error" in text:
            return False
        return True
    if any(keyword in text for keyword in _LOWER_BETTER):
        return False
    return None


def _column_index(headers: list[str], column: str) -> int | None:
    lower = column.strip().lower()
    for idx, header in enumerate(headers):
        if header.strip().lower() == lower:
            return idx
        if lower in header.strip().lower() or header.strip().lower() in lower:
            return idx
    return None


def _numeric_column_values(
    table: TableData, column: str
) -> list[tuple[int, str, float]]:
    """Return ``(row_index, row_label, value)`` for rows with a parseable number."""
    idx = _column_index(table.headers, column)
    if idx is None:
        return []
    out: list[tuple[int, str, float]] = []
    for row_idx, row in enumerate(table.rows):
        if idx >= len(row):
            continue
        numeric = _coerce_float(row[idx])
        if numeric is None:
            continue
        label = str(row[0]).strip() if row and len(row) > 0 and row[0] is not None else f"row {row_idx + 1}"
        out.append((row_idx, label, numeric))
    return out


def best_in_column(
    table: TableData,
    evidence_id: str,
    column: str,
    higher_is_better: bool | None = None,
) -> TableResult:
    """Deterministically find the extreme row in a numeric column."""
    candidates = _numeric_column_values(table, column)
    if not candidates:
        return TableResult(
            op="best",
            column=column,
            evidence_id=evidence_id,
            value=None,
            label=None,
            higher_is_better=higher_is_better,
            succeeded=False,
            detail=f"column {column!r} has no parseable numeric values",
            trace=[f"no numeric values in column {column!r}"],
            extra={},
        )

    inferred = higher_is_better
    if inferred is None:
        inferred = infer_metric_direction(table.caption, column)
    if inferred is None:
        return TableResult(
            op="best",
            column=column,
            evidence_id=evidence_id,
            value=None,
            label=None,
            higher_is_better=None,
            succeeded=False,
            detail=(
                f"metric direction for {column!r} is ambiguous — not claiming a best "
                f"value (candidates: {[label for _, label, _ in candidates]})"
            ),
            trace=["ambiguous metric direction"],
            extra={"candidates": candidates},
        )

    comparator = (lambda triple: triple[2]) if inferred else (lambda triple: -triple[2])
    row_idx, label, value = max(candidates, key=comparator) if inferred else min(candidates, key=lambda t: t[2])
    direction = "higher-is-better" if inferred else "lower-is-better"
    extra = {"row_index": row_idx, "candidates": candidates, "direction": direction}
    detail = f"{label} has the {'highest' if inferred else 'lowest'} {column} of {value:g} in {evidence_id} ({direction})"
    return TableResult(
        op="best",
        column=column,
        evidence_id=evidence_id,
        value=value,
        label=label,
        higher_is_better=inferred,
        detail=detail,
        trace=[detail],
        extra=extra,
        succeeded=True,
    )


def numeric_ranking(
    table: TableData,
    evidence_id: str,
    column: str,
    higher_is_better: bool | None = None,
) -> TableResult:
    """Order rows by a numeric column (ties preserved by row order)."""
    candidates = _numeric_column_values(table, column)
    if not candidates:
        return TableResult(
            op="ranking",
            column=column,
            evidence_id=evidence_id,
            succeeded=False,
            detail=f"cannot rank: no numeric values in {column!r}",
            trace=[f"empty numeric column {column!r}"],
            extra={},
        )

    inferred = higher_is_better if higher_is_better is not None else infer_metric_direction(table.caption, column)
    reverse = inferred if inferred is not None else True
    ordered = sorted(candidates, key=lambda triple: triple[2], reverse=reverse)
    trace = [f"{label} ({value:g})" for _, label, value in ordered]
    detail = f"ranking in {column!r} ({'desc' if reverse else 'asc'}): " + " > ".join(trace)
    return TableResult(
        op="ranking",
        column=column,
        evidence_id=evidence_id,
        higher_is_better=inferred,
        detail=detail,
        trace=trace,
        extra={"ordered": ordered},
        succeeded=True,
    )


def delta_between(
    table: TableData,
    evidence_id: str,
    column: str,
    row_label_a: str,
    row_label_b: str,
) -> TableResult:
    """Absolute and relative delta between two rows' values in ``column``."""
    idx = _column_index(table.headers, column)
    if idx is None:
        return TableResult(op="delta", column=column, evidence_id=evidence_id, succeeded=False, detail=f"column {column!r} not found", trace=[], extra={})

    a_val = _lookup_by_label(table, row_label_a, idx)
    b_val = _lookup_by_label(table, row_label_b, idx)
    if a_val is None or b_val is None:
        return TableResult(
            op="delta",
            column=column,
            evidence_id=evidence_id,
            succeeded=False,
            detail=f"one of {row_label_a!r}/{row_label_b!r} has a missing or non-numeric cell in {column!r}",
            trace=[],
            extra={},
        )

    delta = a_val - b_val
    relative = (delta / b_val * 100.0) if b_val else None
    detail = f"{row_label_a} ({a_val:g}) vs {row_label_b} ({b_val:g}) in {column!r}: delta {delta:+g}"
    if relative is not None:
        detail += f" ({relative:+.1f}%)"
    return TableResult(
        op="delta",
        column=column,
        evidence_id=evidence_id,
        value=delta,
        detail=detail,
        trace=[detail],
        extra={"a": a_val, "b": b_val, "relative_percent": relative},
        succeeded=True,
    )


def lookup_cell(
    table: TableData,
    evidence_id: str,
    column: str,
    row_label: str,
) -> TableResult:
    """Fetch a single cell by row label and column name."""
    idx = _column_index(table.headers, column)
    if idx is None:
        return TableResult(op="lookup", column=column, evidence_id=evidence_id, succeeded=False, detail=f"column {column!r} not found", trace=[], extra={})
    value = _lookup_by_label(table, row_label, idx)
    label = row_label
    found, raw = _find_row(table, row_label)
    if not found:
        return TableResult(op="lookup", column=column, evidence_id=evidence_id, succeeded=False, detail=f"row {row_label!r} not found", trace=[], extra={})
    return TableResult(
        op="lookup",
        column=column,
        evidence_id=evidence_id,
        value=value,
        label=label,
        detail=f"{label} {column!r} = {value:g}" if value is not None else f"{label} {column!r} is empty",
        trace=[],
        extra={"raw": raw},
        succeeded=value is not None,
    )


def _lookup_by_label(table: TableData, label: str, column_idx: int) -> float | None:
    for row in table.rows:
        if not row or row[0] is None:
            continue
        if _normalize(str(row[0])) == _normalize(label):
            if column_idx < len(row):
                return _coerce_float(row[column_idx])
    return None


def _find_row(table: TableData, label: str) -> tuple[bool, list[str | None]]:
    for row in table.rows:
        if row and row[0] is not None and _normalize(str(row[0])) == _normalize(label):
            return True, list(row)
    return False, []
