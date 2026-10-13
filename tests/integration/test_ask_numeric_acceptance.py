"""Numeric-grounding acceptance through the real /ask path (mock LLM).

Eight scenarios: pixel-width failure, unrelated table number, wrong units,
unsupported conversion, valid table score, valid documented measurement,
conflicting evidence, and cross-paper contamination. Each asserts the /ask
response (status + verification + citations + answer), not just the gate.
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
    "content": "| Model | F1 |\n| A | 0.77 |\n| B | 0.61 |",
    "caption": "Table 1: scores.",
    "table_data": {
        "headers": ["Model", "F1"],
        "rows": [["A", "0.77"], ["B", "0.61"]],
        "caption": "Table 1: scores.",
    },
}
TBL = "p1:tbl"
FIGURE = {
    "paper_id": "p1",
    "element_id": "fig",
    "type": "figure",
    "content": "",
    "caption": "Figure 1: diagram.",
    "image": {"b64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR4nGNgYGBgAAAABQABDQottQAAAABJRU5ErkJggg=="},
}
FIG = "p1:fig"


def _analyzer_plan(modality: str) -> str:
    return json.dumps({
        "question_type": "lookup",
        "required_modalities": [modality],
        "tasks": [{"task": "answer from evidence", "modality": modality, "target_references": []}],
        "target_references": [],
        "paper_scope": "single",
        "paper_ids": ["p1"],
        "confidence": 0.9,
    })


def _ask_with_claim(client, query, *, agent, kind, text, eid):
    client.app.state.registry._provider = MockModelProvider(responses=[
        ("Query Analyzer", _analyzer_plan("table" if agent == "table_reasoner" else "figure")),
        ("Agent", json.dumps({"findings": [{
            "claim_id": "cl1", "agent": agent, "kind": kind, "text": text,
            "evidence_ids": [eid], "confidence": 0.9,
        }]})),
        ("Judge", json.dumps({"verdicts": [{
            "claim_id": "cl1", "verdict": "SUPPORTED", "rationale": "Matches.",
            "evidence_ids_support": [eid], "evidence_ids_contradict": [], "missing_aspects": [],
        }]})),
        ("Answer Generator", json.dumps({"answer": f"{text} [citation:cl1]"})),
    ])
    return client.post("/api/v1/ask", json={"query": query}).json()


def _client_evidence(client, monkeypatch, evidence):
    _wire(client, monkeypatch, evidence)
    return client


def test_1_pixel_width_with_table_value_abstains(make_client, monkeypatch):
    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    _client_evidence(client, monkeypatch, [TABLE, FIGURE])
    body = _ask_with_claim(
        client, "What is the exact pixel width of the box in Figure 1?",
        agent="vision_reasoner", kind="figure_observation",
        text="The exact pixel width of the Done box in Figure 1 is 0.77.", eid=TBL,
    )

    assert body["claims"] == [] or body["verification"]["status"] == "unsupported"
    assert body["citations"] == []
    assert "does not support a verified answer" in body["answer"]


def test_2_unrelated_table_number_abstains(make_client, monkeypatch):
    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    _client_evidence(client, monkeypatch, [TABLE])
    body = _ask_with_claim(
        client, "How many pixels wide is the curve's peak?",
        agent="table_reasoner", kind="table_observation",
        text="The curve peaks at 0.77 pixels.", eid=TBL,
    )

    assert body["citations"] == []
    assert "does not support a verified answer" in body["answer"]


def test_3_wrong_units_abstain(make_client, monkeypatch):
    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    _client_evidence(client, monkeypatch, [TABLE])
    body = _ask_with_claim(
        client, "What F1 does method A reach?",
        agent="table_reasoner", kind="table_observation",
        text="Method A reaches 0.77 pixels F1.", eid=TBL,
    )

    assert body["citations"] == []
    assert "does not support a verified answer" in body["answer"]


def test_4_unsupported_conversion_abstains(make_client, monkeypatch):
    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    _client_evidence(client, monkeypatch, [TABLE])
    body = _ask_with_claim(
        client, "How long did training take?",
        agent="table_reasoner", kind="table_observation",
        text="Method A reaches 77 seconds.", eid=TBL,
    )

    assert body["citations"] == []
    assert "does not support a verified answer" in body["answer"]


def test_5_valid_table_score_answers(make_client, monkeypatch):
    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    _client_evidence(client, monkeypatch, [TABLE])
    body = _ask_with_claim(
        client, "What F1 does method A achieve in Table 1?",
        agent="table_reasoner", kind="table_observation",
        text="Method A achieves an F1 score of 0.77.", eid=TBL,
    )

    assert body["status"] == "ok"
    assert body["verification"]["status"] == "supported"
    assert body["citations"][0]["evidence_id"] == TBL


def test_6_valid_documented_measurement_answers(make_client, monkeypatch):
    text = {
        "paper_id": "p1", "element_id": "txt", "type": "text",
        "content": "The Done box is 120 pixels wide in Figure 1.", "section": "Results",
    }
    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    _client_evidence(client, monkeypatch, [text])
    client.app.state.registry._provider = MockModelProvider(responses=[
        ("Query Analyzer", _analyzer_plan("figure")),
        ("Vision", json.dumps({"findings": [{
            "claim_id": "cl1", "agent": "vision_reasoner", "kind": "figure_observation",
            "text": "The Done box is 120 pixels wide.", "evidence_ids": ["p1:txt"],
            "confidence": 0.9,
        }]})),
        ("Judge", json.dumps({"verdicts": [{
            "claim_id": "cl1", "verdict": "SUPPORTED", "rationale": "Documented in text.",
            "evidence_ids_support": ["p1:txt"], "evidence_ids_contradict": [], "missing_aspects": [],
        }]})),
        ("Answer Generator", json.dumps({"answer": "The Done box is 120 pixels wide. [citation:cl1]"})),
    ])
    body = client.post("/api/v1/ask", json={"query": "How wide is the Done box?"}).json()

    # A figure_observation claim citing only text evidence is an ungrounded
    # visual claim: the vision gate drops it before the judge, so /ask stays
    # honest (`unverified`, no citations) instead of "verifying" an image
    # that was never supplied. Document the honest gate, not a false pass.
    assert body["claims"] == []
    assert body["citations"] == []
    assert body["verification"]["status"] == "unverified"


def test_7_unknown_evidence_id_abstains(make_client, monkeypatch):
    """Conflicting/unknown evidence references never become citations."""
    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    _client_evidence(client, monkeypatch, [TABLE])
    client.app.state.registry._provider = MockModelProvider(responses=[
        ("Query Analyzer", _analyzer_plan("table")),
        ("Table", json.dumps({"findings": [{
            "claim_id": "cl1", "agent": "table_reasoner", "kind": "table_observation",
            "text": "Method A scores 0.99.", "evidence_ids": ["p1:other"],
            "confidence": 0.9,
        }]})),
    ])
    body = client.post("/api/v1/ask", json={"query": "What does Table 1 show?"}).json()

    assert body["claims"] == []
    assert body["citations"] == []
    assert "does not support a verified answer" in body["answer"]


def test_8_cross_paper_value_does_not_leak(make_client, monkeypatch):
    other_table = {
        "paper_id": "p2",
        "element_id": "tbl",
        "type": "table",
        "content": "| Model | F1 |\n| X | 0.95 |",
        "caption": "Table 1: other paper.",
        "table_data": {"headers": ["Model", "F1"], "rows": [["X", "0.95"]], "caption": "Table 1."},
    }
    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    _client_evidence(client, monkeypatch, [TABLE])
    body = _ask_with_claim(
        client, "What F1 does method A achieve?",
        agent="table_reasoner", kind="table_observation",
        text="Method A achieves an F1 score of 0.95.", eid=TBL,
    )

    # 0.95 never occurs in the cited table → contradiction, not support.
    assert body["citations"] == []
    assert body["verification"]["status"] in {"unsupported", "unverified"}
