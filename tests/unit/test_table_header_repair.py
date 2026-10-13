"""Row-label header repair (KEHNN Table 4 corpus defect).

The live corpus stores Table 4 with ``headers=["R2@1", ...]`` while rows
still carry labels in ``row[0]`` and the Markdown content shows the true
columns. Deterministic metric scans treat headers/rows as aligned, so the
missing label header misattributes every metric. The adapter must restore
the label header when the Markdown header proves it was dropped.
"""

from __future__ import annotations

from app.agents.table_agent import _numeric_columns
from app.evidence.adapter import adapt_retrieval_record
from app.schemas.evidence import TableData


def _keh_table_record() -> dict:
    return {
        "paper_id": "1611.04684v1",
        "element_id": "elem_004",
        "type": "table",
        "content": (
            "Paper: Knowledge Enhanced Hybrid Neural Network for Text Matching | Type: Table\n"
            "Caption: Table 4: Evaluation results on response selection\n"
            "Context: \n\n"
            "| R2@1 | R10@1 | R10@2 | R10@5 |\n"
            "| --- | --- | --- | --- |\n"
            "| MLP | 0.651 | 0.256 | 0.380 | 0.703 |\n"
            "| KEHNN | 0.786 | 0.460 | 0.591 | 0.819 |"
        ),
        "caption": "Table 4: Evaluation results on response selection",
        "table_data": {
            "caption": "Table 4: Evaluation results on response selection",
            "headers": ["R2@1", "R10@1", "R10@2", "R10@5"],
            "rows": [
                ["MLP", "0.651", "0.256", "0.380", "0.703"],
                ["KEHNN", "0.786", "0.460", "0.591", "0.819"],
            ],
        },
    }


def test_adapter_restores_missing_row_label_header():
    item = adapt_retrieval_record(_keh_table_record(), paper_id_fallback="1611.04684v1", rank=1)

    assert item.table_data is not None
    assert len(item.table_data.headers) == 5
    assert len(item.table_data.rows[0]) == 5


def test_metric_scan_sees_all_four_metrics_after_repair():
    item = adapt_retrieval_record(_keh_table_record(), paper_id_fallback="1611.04684v1", rank=1)

    assert set(_numeric_columns(item)) == {"R2@1", "R10@1", "R10@2", "R10@5"}


def test_best_trace_uses_true_metric_columns():
    from app.agents.table_ops import best_in_column

    item = adapt_retrieval_record(_keh_table_record(), paper_id_fallback="1611.04684v1", rank=1)
    assert item.table_data is not None

    for column, expected in (("R2@1", 0.786), ("R10@5", 0.819)):
        result = best_in_column(item.table_data, item.evidence_id, column)
        assert result.succeeded
        assert result.label == "KEHNN"
        assert abs((result.value or 0.0) - expected) < 1e-9
        assert column in result.detail


def test_wellformed_table_is_left_unchanged():
    raw = {
        "paper_id": "p1",
        "element_id": "t1",
        "type": "table",
        "content": "| Model | Score |\n|---|---:|\n| KEHNN | 0.819 |",
        "caption": "Table 4: Results",
        "table_data": {
            "headers": ["Model", "Score"],
            "rows": [["KEHNN", "0.819"]],
            "caption": "Table 4: Results",
        },
    }

    item = adapt_retrieval_record(raw, paper_id_fallback="p1", rank=0)

    assert item.table_data is not None
    assert isinstance(item.table_data, TableData)
    assert item.table_data.headers == ["Model", "Score"]
