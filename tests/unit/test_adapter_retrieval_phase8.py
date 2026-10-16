"""Unit tests for retrieval adapter + retrieval_provider contract."""

from __future__ import annotations

import pytest

from app.evidence.adapter import adapt_retrieval_record, adapt_retrieval_response


def test_adapter_maps_text_record_to_evidence_item():
    raw = {"type": "text", "content": "hello", "page": 3, "section": "3.1"}
    item = adapt_retrieval_record(raw, paper_id_fallback="p1", rank=0)
    assert item.paper_id == "p1"
    assert item.type == "text"
    assert item.page == 3


def test_adapter_generates_deterministic_evidence_id():
    raw = {"type": "table", "caption": "Table 1", "page": 5}
    a = adapt_retrieval_record(raw, paper_id_fallback="p1", rank=0)
    b = adapt_retrieval_record(raw, paper_id_fallback="p1", rank=0)
    assert a.evidence_id == b.evidence_id
    c = adapt_retrieval_record(raw, paper_id_fallback="p1", rank=1)
    assert a.evidence_id != c.evidence_id


def test_adapter_extracts_envelope_variants():
    payload = {"evidence": [{"type": "text", "content": "hi"}]}
    bundle = adapt_retrieval_response(payload)
    assert len(bundle.evidence) == 1

    payload2 = {"results": [{"type": "text", "content": "hi"}]}
    bundle2 = adapt_retrieval_response(payload2)
    assert len(bundle2.evidence) == 1

    payload3 = [{"type": "text", "content": "hi"}]
    bundle3 = adapt_retrieval_response(payload3)
    assert len(bundle3.evidence) == 1


def test_adapter_preserves_cross_ref_provenance():
    raw = {"type": "table", "content": "| A | B |", "expanded_via_cross_ref": True, "paper_id": "p1"}
    item = adapt_retrieval_record(raw, paper_id_fallback="p1", rank=0)
    assert item.metadata["expanded_via_cross_ref"] is True


def test_adapter_normalizes_abbreviated_figure_reference():
    item = adapt_retrieval_record(
        {
            "paper_id": "pdf_first_experimental_results_of_space_object_detec_8e992c9fa7ca",
            "element_id": "fig_p3_01",
            "type": "figure",
            "caption": "Fig. 1: Wide-field view of the antenna system",
        },
        "retrieved",
        0,
    )

    assert item.reference == "Figure 1"


def test_adapter_marks_caption_only_table_as_incomplete():
    raw = {
        "paper_id": "1611.04684v1",
        "element_id": "elem_004",
        "type": "table",
        "content": "Type: Table\nCaption: Table 4: Evaluation results on response selection\nContext: ",
        "caption": "Table 4: Evaluation results on response selection",
        "page": None,
        "image_path": None,
    }

    item = adapt_retrieval_record(raw, paper_id_fallback="retrieved", rank=0)

    assert item.table_data is None
    assert item.metadata["table_evidence_status"] == "caption_only"
    assert item.reference == "Table 4"
    assert item.page is None


def test_adapter_preserves_complete_structured_table_data():
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
    assert item.table_data.rows == [["KEHNN", "0.819"]]
    assert item.metadata["table_evidence_status"] == "complete"


def test_adapter_preserves_partial_table_extraction_as_incomplete():
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
        "metadata": {"table_extraction": "partial"},
    }

    item = adapt_retrieval_record(raw, paper_id_fallback="p1", rank=0)

    assert item.metadata["table_extraction"] == "partial"
    assert item.metadata["table_evidence_status"] == "incomplete"


def test_adapter_rejects_none_payload():
    with pytest.raises(ValueError):
        adapt_retrieval_response(None)


def test_retrieval_provider_builds_from_settings():
    from app.config import Settings
    from app.evidence.retrieval_client import build_retrieval_provider

    s = Settings(_env_file=None, retrieval_mode="disabled")  # type: ignore[call-arg]
    p = build_retrieval_provider(s)
    assert p.name == "disabled"

    s = Settings(_env_file=None, retrieval_mode="mock")  # type: ignore[call-arg]
    p = build_retrieval_provider(s)
    assert p.name == "mock"

    s = Settings(_env_file=None, retrieval_mode="http", retrieval_base_url="http://localhost:8000")  # type: ignore[call-arg]
    p = build_retrieval_provider(s)
    assert p.name == "http"


def test_mock_provider_returns_evidence():
    from app.evidence.retrieval_client import MockRetrievalProvider, RetrievalRequest

    p = MockRetrievalProvider(default_evidence=[{"evidence_id": "e_p1", "paper_id": "p1", "type": "text", "content": "hello"}])
    # Need to run async - use asyncio
    import asyncio
    result = asyncio.run(p.retrieve(RetrievalRequest(query="test", top_k=5, timeout_s=5)))
    assert len(result.bundle.evidence) == 1
    assert result.bundle.evidence[0].content == "hello"
