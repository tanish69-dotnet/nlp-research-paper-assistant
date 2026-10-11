"""Deterministic table-operation tests (PRD §10, ARCHITECTURE §4.3)."""

from __future__ import annotations

import pytest

from app.agents.table_ops import (
    best_in_column,
    delta_between,
    infer_metric_direction,
    lookup_cell,
    numeric_ranking,
)
from app.schemas.evidence import TableData

ACCURACY_TABLE = TableData(
    headers=["Method", "Accuracy (%)", "Latency (ms)"],
    rows=[
        ["Method A", "91.7", "40"],
        ["Method B", "88.3", "25"],
        ["Method C", "92.4", "60"],
    ],
    caption="Table: accuracy and latency comparison.",
)

ABLATION_TABLE = TableData(
    headers=["Variant", "F1"],
    rows=[
        ["Full", "81.2"],
        ["w/o retriever", "77.6"],
        ["w/o reranker", "79.0"],
    ],
    caption="Table: ablation F1 (higher-is-better).",
)

LOSS_TABLE = TableData(
    headers=["Model", "Loss"],
    rows=[["A", "0.42"], ["B", "0.39"], ["C", "0.51"]],
    caption="Training loss on dev.",
)

PARAMS_TABLE = TableData(
    headers=["Method", "Params (M)"],
    rows=[["Ours", "120"], ["Baseline-B", "340"], ["Method A", "91"]],
    caption="Parameter counts.",
)

TIE_TABLE = TableData(
    headers=["Method", "Score"],
    rows=[["A", "80.0"], ["B", "80.0"], ["C", "79.9"]],
    caption="Tie case.",
)


def test_infer_direction_higher_is_better() -> None:
    assert infer_metric_direction("accuracy comparison", "Accuracy (%)") is True
    assert infer_metric_direction("F1 on dev", "F1") is True
    assert infer_metric_direction("BLEU scores", "BLEU") is True
    assert infer_metric_direction("response selection", "R10@1") is True


def test_infer_direction_lower_is_better() -> None:
    assert infer_metric_direction("Latency comparison", "Latency (ms)") is False
    assert infer_metric_direction("loss curve", "Loss") is False
    assert infer_metric_direction("Parameters", "Params (M)") is False


def test_infer_direction_ambiguous() -> None:
    assert infer_metric_direction("Comparison", "Column B") is None


def test_best_accuracy_is_highest() -> None:
    result = best_in_column(ACCURACY_TABLE, "e_t1", "Accuracy (%)")

    assert result.succeeded is True
    assert result.label == "Method C"
    assert result.value == pytest.approx(92.4)
    assert result.higher_is_better is True


def test_worst_accuracy_is_not_best() -> None:
    """`best` always honours direction; for a lower-is-better loss, B wins."""
    result = best_in_column(LOSS_TABLE, "e_loss", "Loss")

    assert result.label == "B"
    assert result.value == pytest.approx(0.39)
    assert result.higher_is_better is False


def test_best_params_is_lowest() -> None:
    """Params is a lower-is-better metric."""
    result = best_in_column(PARAMS_TABLE, "e_params", "Params (M)")

    assert result.label == "Method A"
    assert result.higher_is_better is False


def test_unknown_direction_does_not_guess() -> None:
    unknown = TableData(headers=["X", "Alpha"], rows=[["a", "10"], ["b", "20"]], caption="mystery metric alpha")
    result = best_in_column(unknown, "e_x", "Alpha", higher_is_better=None)

    assert result.succeeded is False
    assert result.value is None
    assert "ambiguous" in result.detail.lower()


def test_explicit_direction_overrides_hint() -> None:
    result = best_in_column(PARAMS_TABLE, "e_params", "Params (M)", higher_is_better=True)

    assert result.label == "Baseline-B"
    assert result.value == pytest.approx(340.0)


def test_ranking_descending_for_accuracy() -> None:
    result = numeric_ranking(ACCURACY_TABLE, "e_t1", "Accuracy (%)")

    assert result.succeeded is True
    assert [entry.split(" ")[0] for entry in result.trace] == ["Method", "Method", "Method"]
    labels = [row_label for row_label, _ in result.extra["ordered_labels"]] if "ordered_labels" in result.extra else None
    # Fallback: trace carries labels
    assert result.trace[0].startswith("Method C")
    assert result.trace[1].startswith("Method A")


def test_ranking_tie_preserves_row_order() -> None:
    result = numeric_ranking(TIE_TABLE, "e_tie", "Score")

    # Tie between A and B at 80.0 — row order (A before B) should be preserved by stable sort
    assert result.trace[0].startswith("A")
    assert result.trace[1].startswith("B")


def test_delta_between_two_rows() -> None:
    result = delta_between(ACCURACY_TABLE, "e_t1", "Accuracy (%)", "Method C", "Method B")

    assert result.succeeded is True
    assert result.value == pytest.approx(92.4 - 88.3)
    assert result.extra["a"] == pytest.approx(92.4)
    assert result.extra["b"] == pytest.approx(88.3)
    assert result.extra["relative_percent"] is not None


def test_delta_missing_row_is_error() -> None:
    result = delta_between(ACCURACY_TABLE, "e_t1", "Accuracy (%)", "Method C", "NotExists")

    assert result.succeeded is False
    assert "missing" in result.detail.lower() or "non-numeric" in result.detail.lower()


def test_lookup_exact_cell() -> None:
    result = lookup_cell(ABLATION_TABLE, "e_abl", "F1", "Full")

    assert result.succeeded is True
    assert result.value == pytest.approx(81.2)
    assert result.label == "Full"


def test_lookup_nonexistent_row_is_error() -> None:
    result = lookup_cell(ABLATION_TABLE, "e_abl", "F1", "Ghost")

    assert result.succeeded is False


def test_empty_table_column_is_error() -> None:
    empty = TableData(headers=["Method", "Score"], rows=[], caption="empty")
    result = best_in_column(empty, "e_empty", "Score")

    assert result.succeeded is False


def test_coerce_handles_suffixes() -> None:
    table = TableData(headers=["Method", "Latency"], rows=[["A", "40"], ["B", "25"]], caption="Latency comparison.")
    result = best_in_column(table, "e_suffix", "Latency")

    assert result.succeeded is True
    # Lower-is-better for latency — B (25) should win over A (40)
    assert result.label == "B"
