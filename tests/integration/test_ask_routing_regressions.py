"""Routing regressions through the real /ask path (mock retrieval + mock LLM).

Covers: paraphrased table questions, explicit references, mixed table+figure
questions, ambiguous/numeric wording that must stay text-only, and
insufficient-evidence abstention. Routing is asserted on the /ask response
(plan modalities + agent_status), never on isolated analyzer helpers alone.
"""

from __future__ import annotations

import json

import httpx

from app.models.mock import MockModelProvider


def _wire_retrieval(client, monkeypatch, evidence):
    from app.api.routes import ask as ask_route
    from app.evidence.retrieval_client import HttpRetrievalProvider

    def build(settings):
        def handle(request):
            return httpx.Response(200, json={"evidence": evidence})

        provider = HttpRetrievalProvider(settings.retrieval_base_url)
        provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        return provider

    monkeypatch.setattr(ask_route, "build_retrieval_provider", build)


def _table_evidence(paper="p1", eid="p1:tbl1"):
    return {
        "paper_id": paper,
        "element_id": "tbl1",
        "type": "table",
        "content": "| Model | F1 |\n| A | 0.77 |\n| B | 0.61 |",
        "caption": "Table 1: scores.",
        "table_data": {
            "headers": ["Model", "F1"],
            "rows": [["A", "0.77"], ["B", "0.61"]],
            "caption": "Table 1: scores.",
        },
    }


def _figure_evidence(paper="p1", eid="p1:fig1"):
    return {
        "paper_id": paper,
        "element_id": "fig1",
        "type": "figure",
        "content": "",
        "caption": "Figure 1: architecture.",
        "image": {"b64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR4nGNgYGBgAAAABQABDQottQAAAABJRU5ErkJggg=="},
    }


def _text_evidence(paper="p1"):
    return {
        "paper_id": paper,
        "element_id": "t1",
        "type": "text",
        "content": "The paper proposes a hybrid method for text matching.",
        "section": "Abstract",
    }


def _plan_for(modality: str, refs: list[str] | None = None) -> str:
    targets = list(refs or [])
    return json.dumps({
        "question_type": "lookup",
        "required_modalities": [modality],
        "tasks": [{"task": "answer from evidence", "modality": modality, "target_references": targets}],
        "target_references": targets,
        "paper_scope": "single",
        "paper_ids": ["p1"],
        "confidence": 0.9,
    })


def _supported_claim_roundtrip(eid: str, *, agent: str, text: str, claim_id: str = "cl1"):
    kind = {
        "text_reasoner": "author_claim",
        "table_reasoner": "table_observation",
        "vision_reasoner": "figure_observation",
    }[agent]
    return [
        ("Text Reasoning Agent" if agent == "text_reasoner" else
         "Table Reasoning Agent" if agent == "table_reasoner" else "Vision",
         json.dumps({"findings": [{
             "claim_id": claim_id, "kind": kind, "text": text,
             "evidence_ids": [eid], "confidence": 0.9,
         }]})),
        ("Judge", json.dumps({"verdicts": [{
            "claim_id": claim_id, "verdict": "SUPPORTED", "rationale": "Matches supplied evidence.",
            "evidence_ids_support": [eid], "evidence_ids_contradict": [], "missing_aspects": [],
        }]})),
        ("Answer Generator", json.dumps({"answer": f"{text} [citation:{claim_id}]"})),
    ]


def test_paraphrased_best_method_reaches_table_agent(make_client, monkeypatch):
    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    _wire_retrieval(client, monkeypatch, [_table_evidence()])
    provider = MockModelProvider(responses=[("Query Analyzer", _plan_for("table"))])
    client.app.state.registry._provider = provider

    body = client.post("/api/v1/ask", json={"query": "Which method performs best?"}).json()

    assert "table" in body["plan"]["required_modalities"]
    assert body["metadata"]["agent_status"].get("table_reasoner") in {"ok", "partial", "error", "no_evidence"}


def test_explicit_table_reference_routes_table(make_client, monkeypatch):
    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    _wire_retrieval(client, monkeypatch, [_table_evidence()])
    provider = MockModelProvider(
        responses=[("Query Analyzer", _plan_for("table", ["Table 1"]))]
        + _supported_claim_roundtrip("p1:tbl1", agent="table_reasoner", text="A scores 0.77 F1.")
    )
    client.app.state.registry._provider = provider

    body = client.post("/api/v1/ask", json={"query": "What does Table 1 show?"}).json()

    assert "table" in body["plan"]["required_modalities"]
    assert "Table 1" in body["plan"]["target_references"]
    assert body["status"] == "ok"


def test_mixed_table_figure_question_routes_both(make_client, monkeypatch):
    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    _wire_retrieval(client, monkeypatch, [_table_evidence(), _figure_evidence()])
    plan = json.dumps({
        "question_type": "comparison",
        "required_modalities": ["table", "figure"],
        "tasks": [
            {"task": "compare table", "modality": "table", "target_references": ["Table 1"]},
            {"task": "describe figure", "modality": "figure", "target_references": ["Figure 1"]},
        ],
        "target_references": ["Table 1", "Figure 1"],
        "paper_scope": "single",
        "paper_ids": ["p1"],
        "confidence": 0.85,
    })
    client.app.state.registry._provider = MockModelProvider(responses=[("Query Analyzer", plan)])

    body = client.post(
        "/api/v1/ask",
        json={"query": "Compare Table 1 results with the trend in Figure 1."},
    ).json()

    assert "table" in body["plan"]["required_modalities"]
    assert "figure" in body["plan"]["required_modalities"]


def test_bare_number_question_stays_text(make_client, monkeypatch):
    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    _wire_retrieval(client, monkeypatch, [_text_evidence()])
    provider = MockModelProvider(
        responses=[("Query Analyzer", _plan_for("text"))]
        + _supported_claim_roundtrip("p1:t1", agent="text_reasoner", text="The paper lists three authors.")
    )
    client.app.state.registry._provider = provider

    body = client.post("/api/v1/ask", json={"query": "How many authors are listed?"}).json()

    assert body["plan"]["required_modalities"] == ["text"]
    assert "table_reasoner" not in body["metadata"]["agent_status"]


def test_table_question_without_tables_abstains(make_client, monkeypatch):
    # Table-only task with text-only evidence: the planner marks the table
    # task skipped, so no table agent ever runs and nothing is verified.
    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    _wire_retrieval(client, monkeypatch, [_text_evidence()])
    provider = MockModelProvider(responses=[("Query Analyzer", _plan_for("table"))])
    client.app.state.registry._provider = provider

    body = client.post("/api/v1/ask", json={"query": "Which method performs best?"}).json()

    assert body["status"] == "partial"
    assert body["claims"] == []
    assert "table_reasoner" not in body["metadata"]["agent_status"]
    assert body["plan"]["required_modalities"] == ["table"]
    assert "does not support a verified answer" in body["answer"]


def test_model_plan_without_table_intent_is_kept_by_determinism(make_client, monkeypatch):
    """A text-only analyzer plan for best/worst wording must still route table."""
    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    _wire_retrieval(client, monkeypatch, [_table_evidence()])
    client.app.state.registry._provider = MockModelProvider(
        responses=[("Query Analyzer", _plan_for("text"))]
    )

    body = client.post("/api/v1/ask", json={"query": "Which method performs best?"}).json()

    assert "table" in body["plan"]["required_modalities"]
