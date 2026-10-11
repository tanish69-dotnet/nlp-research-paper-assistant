"""Offline HTTP/agent regressions; these do not claim live corpus success."""

from __future__ import annotations

import json

import httpx
import pytest

from app.api.routes import ask as ask_route
from app.evidence.retrieval_client import HttpRetrievalProvider
from app.models.mock import MockModelProvider


PAPER = "1611.04684v1"
TEXT_QUERY = f"What is the main contribution of the paper {PAPER}?"
TABLE_QUERY = (
    f"According to Table 4 in paper {PAPER}, which model performs best for "
    "response selection, and how can we tell?"
)
CAPTION_RECORD = {
    "rank": 1,
    "score": 0.6001,
    "paper_id": PAPER,
    "element_id": "elem_004",
    "type": "table",
    "page": None,
    "section": "",
    "content": "Type: Table\nCaption: Table 4: Evaluation results on response selection\nContext: ",
    "caption": "Table 4: Evaluation results on response selection",
    "context": "",
    "image_path": None,
}


def wire_http(client, monkeypatch, evidence):
    """Run the actual HTTP retrieval client and adapter against a fake transport."""
    captured = []

    def build(settings):
        def handle(request):
            assert str(request.url) == "http://127.0.0.1:8000/retrieve"
            assert request.method == "POST"
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={"evidence": evidence})

        provider = HttpRetrievalProvider(settings.retrieval_base_url)
        provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        return provider

    monkeypatch.setattr(ask_route, "build_retrieval_provider", build)
    return captured


def plan(modality):
    return json.dumps({
        "question_type": "lookup" if modality == "table" else "definition",
        "required_modalities": [modality],
        "tasks": [{
            "task": "answer from evidence", "modality": modality,
            "target_references": [PAPER, "Table 4"] if modality == "table" else [PAPER],
        }],
        "target_references": [PAPER, "Table 4"] if modality == "table" else [PAPER],
        "paper_scope": "single", "paper_ids": [PAPER], "confidence": 0.9,
    })


@pytest.mark.parametrize("query,modality", [(TEXT_QUERY, "text"), (TABLE_QUERY, "table")])
def test_caption_only_retrieval_cannot_answer_either_question(make_client, monkeypatch, query, modality):
    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    captured = wire_http(client, monkeypatch, [CAPTION_RECORD])
    provider = MockModelProvider(responses=[("Query Analyzer", plan(modality))])
    client.app.state.registry._provider = provider

    response = client.post("/api/v1/ask", json={"query": query})

    assert response.status_code == 200
    body = response.json()
    assert captured == [{"query": query, "top_k": 5, "paper_ids": [PAPER]}]
    assert body["status"] == "partial"
    assert body["claims"] == body["citations"] == []
    assert body["verification"]["status"] == "unverified"
    assert "does not support a verified answer" in body["answer"]
    assert body["metadata"]["evidence_total"] == 1
    assert body["metadata"]["evidence_used"] == []
    assert PAPER not in body["plan"]["target_references"]
    assert provider.call_count == 1  # no text/table/Judge/generator inference
    if modality == "table":
        assert body["metadata"]["agent_status"]["table_reasoner"] == "no_evidence"


@pytest.mark.parametrize("paper_ids,expected", [(["another_paper"], ["another_paper"]), ([], None)])
def test_explicit_scope_overrides_query_inference(make_client, monkeypatch, paper_ids, expected):
    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    captured = wire_http(client, monkeypatch, [])

    response = client.post("/api/v1/ask", json={"query": TEXT_QUERY, "paper_ids": paper_ids})

    assert response.status_code == 400  # no fabricated evidence on an empty result
    assert captured[0].get("paper_ids") == expected


@pytest.mark.parametrize("paper_ids", [[" "], [""], [7], ["x"] * 51])
def test_invalid_explicit_scope_is_rejected(make_client, paper_ids):
    client = make_client(retrieval_mode="http")
    response = client.post("/api/v1/ask", json={"query": TEXT_QUERY, "paper_ids": paper_ids})
    # The API's installed exception handlers expose request-schema failures as
    # the stable INVALID_REQUEST 400 response.
    assert response.status_code == 400


def test_retrieved_text_reaches_agent_judge_and_citation(make_client, monkeypatch):
    # Illustrative test evidence, NOT an artifact currently returned by Person 2.
    text = "The paper proposes a knowledge enhanced hybrid neural network for text matching."
    record = {
        "paper_id": PAPER, "element_id": "abstract_test", "type": "text",
        "content": text, "page": None, "section": "Abstract", "score": 0.9,
    }
    eid = f"{PAPER}:abstract_test"
    responses = [
        ("Query Analyzer", plan("text")),
        ("Text Reasoning Agent", json.dumps({"findings": [{
            "claim_id": "cl_text", "kind": "author_claim", "text": text,
            "evidence_ids": [eid], "confidence": 0.9,
        }]})),
        ("Judge", json.dumps({"verdicts": [{
            "claim_id": "cl_text", "verdict": "SUPPORTED", "rationale": "Matches supplied text.",
            "evidence_ids_support": [eid], "evidence_ids_contradict": [], "missing_aspects": [],
        }]})),
        ("Answer Generator", json.dumps({"answer": text + " [citation:cl_text]"})),
    ]
    requests = []

    class CaptureModel(MockModelProvider):
        async def chat(self, request):
            requests.append(request)
            return await super().chat(request)

    client = make_client(retrieval_mode="http", retrieval_base_url="http://127.0.0.1:8000")
    captured = wire_http(client, monkeypatch, [record])
    client.app.state.registry._provider = CaptureModel(responses=responses)

    body = client.post("/api/v1/ask", json={"query": TEXT_QUERY}).json()

    assert captured[0]["paper_ids"] == [PAPER]
    assert body["status"] == "ok"
    assert body["verification"]["status"] == "supported"
    assert len(body["claims"]) == len(body["citations"]) == 1
    assert body["citations"][0]["paper_id"] == PAPER
    assert body["citations"][0]["evidence_id"] == eid
    assert body["citations"][0]["page"] is None
    assert body["answer"] == text + " [citation:cl_text]"
    assert len(requests) == 4
    # Check actual prompts, not just the canned model output.
    assert text in requests[1].messages[1].content
    assert eid in requests[1].messages[1].content
    assert text in requests[2].messages[1].content
    assert "VERIFIED CLAIMS" in requests[3].messages[1].content
