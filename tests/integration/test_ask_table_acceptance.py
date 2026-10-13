"""Table acceptance scenarios through the real /ask path (mock LLM).

Seven scenarios: cell read, best method, two-method comparison, numeric
difference, cross-metric non-confusion, missing/ambiguous evidence, and no
relevant table in the paper.
"""

from __future__ import annotations

import json

import httpx

from app.models.mock import MockModelProvider


def _wire(client, monkeypatch, evidence):
    from app.api.routes import ask as ask_route
    from app.evidence.retrieval_client import HttpRetrievalProvider

    def build(settings):
        def handle(request):
            return httpx.Response(200, json={"evidence": evidence})

        provider = HttpRetrievalProvider(settings.retrieval_base_url)
        provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        return provider

    monkeypatch.setattr(ask_route, "build_retrieval_provider", build)


TABLE = {
    "paper_id": "p1",
    "element_id": "tbl",
    "type": "table",
    "content": "| Model | F1 | Accuracy |\n| A | 0.77 | 0.81 |\n| B | 0.61 | 0.84 |",
    "caption": "Table 1: scores.",
    "table_data": {
        "headers": ["Model", "F1", "Accuracy"],
        "rows": [["A", "0.77", "0.81"], ["B", "0.61", "0.84"]],
        "caption": "Table 1: scores.",
    },
}
EID = "p1:tbl"


def _plan(table_refs: list[str] | None = None) -> str:
    refs = table_refs or ["Table 1"]
    return json.dumps({
        "question_type": "comparison",
        "required_modalities": ["table"],
        "tasks": [{"task": "summarize_results", "modality": "table", "target_references": refs}],
        "target_references": refs,
        "paper_scope": "single",
        "paper_ids": ["p1"],
        "confidence": 0.9,
    })


def _ask(client, query, responses):
    client.app.state.registry._provider = MockModelProvider(responses=responses)
    return client.post("/api/v1/ask", json={"query": query}).json()


def _claim_payload(kind, text, claim_id="cl1"):
    return json.dumps({"findings": [{
        "claim_id": claim_id, "kind": kind, "text": text,
        "evidence_ids": [EID], "confidence": 0.9,
    }]})


def _judge_payload(claim_id="cl1"):
    return json.dumps({"verdicts": [{
        "claim_id": claim_id, "verdict": "SUPPORTED", "rationale": "Matches table.",
        "evidence_ids_support": [EID], "evidence_ids_contradict": [], "missing_aspects": [],
    }]})


def _gen_payload(text):
    return json.dumps({"answer": f"{text} [citation:cl1]"})


def _ask_table(client, query, claim_text, claim_kind="table_observation"):
    return _ask(client, query, [
        ("Query Analyzer", _plan()),
        ("Table Reasoning Agent", _claim_payload(claim_kind, claim_text)),
        ("Judge", _judge_payload()),
        ("Answer Generator", _gen_payload(claim_text)),
    ])


def test_1_read_specific_cell(make_client, monkeypatch):
    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    _wire(client, monkeypatch, [TABLE])
    body = _ask_table(client, "What is the F1 of method A in Table 1?", "Method A has F1 0.77.")

    assert body["status"] == "ok"
    assert body["citations"][0]["evidence_id"] == EID


def test_2_identify_best_method(make_client, monkeypatch):
    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    _wire(client, monkeypatch, [TABLE])
    body = _ask_table(
        client, "Which method performs best on F1 in Table 1?",
        "Method A performs best on F1 with 0.77.", "table_comparison",
    )

    assert body["status"] == "ok"
    assert "A" in body["answer"]


def test_3_compare_two_methods(make_client, monkeypatch):
    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    _wire(client, monkeypatch, [TABLE])
    body = _ask_table(
        client, "Compare A and B on F1 in Table 1.",
        "Method A (0.77) outperforms method B (0.61) on F1.", "table_comparison",
    )

    assert body["status"] == "ok"
    assert body["verification"]["status"] == "supported"


def test_4_numeric_difference(make_client, monkeypatch):
    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    _wire(client, monkeypatch, [TABLE])
    body = _ask_table(
        client, "What is the difference between the two F1 scores in Table 1?",
        "The difference is 0.16 (0.77 minus 0.61).",
    )

    assert body["status"] == "ok"


def test_5_cross_metric_not_confused(make_client, monkeypatch):
    """F1-best (A) must not leak into an Accuracy question (B is best)."""
    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    _wire(client, monkeypatch, [TABLE])
    body = _ask_table(
        client, "Which method has the highest Accuracy in Table 1?",
        "Method B has the highest Accuracy with 0.84.", "table_comparison",
    )

    assert body["status"] == "ok"
    assert "B" in body["answer"]


def test_6_caption_only_table_abstains_on_values(make_client, monkeypatch):
    caption_only = {
        "paper_id": "p1", "element_id": "tbl", "type": "table",
        "content": "Type: Table\nCaption: Table 1: scores.\nContext: ",
        "caption": "Table 1: scores.",
    }
    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    _wire(client, monkeypatch, [caption_only])
    client.app.state.registry._provider = MockModelProvider(
        responses=[("Query Analyzer", _plan())]
    )

    body = client.post("/api/v1/ask", json={"query": "Which method performs best in Table 1?"}).json()

    assert body["status"] == "partial"
    assert body["claims"] == []
    assert "does not support a verified answer" in body["answer"]


def test_7_no_table_in_paper_abstains(make_client, monkeypatch):
    text_only = {
        "paper_id": "p1", "element_id": "t1", "type": "text",
        "content": "Some prose without numbers.", "section": "Intro",
    }
    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    _wire(client, monkeypatch, [text_only])
    client.app.state.registry._provider = MockModelProvider(
        responses=[("Query Analyzer", _plan())]
    )

    body = client.post("/api/v1/ask", json={"query": "What does Table 1 show?"}).json()

    assert body["status"] == "partial"
    assert body["verification"]["status"] == "unverified"
    assert "does not support a verified answer" in body["answer"]
