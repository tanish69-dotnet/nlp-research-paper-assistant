"""Regression tests for the real retrieval-backed reasoning path."""

from __future__ import annotations

import json

import httpx

from app.api.routes import ask as ask_route
from app.evidence.retrieval_client import HttpRetrievalProvider
from app.models.mock import MockModelProvider


PAPER = "1611.04684v1"
TABLE_ID = f"{PAPER}:table_1"


def _wire_retrieval(client, monkeypatch, records):
    def build(settings):
        def handle(request):
            return httpx.Response(200, json={"evidence": records})

        provider = HttpRetrievalProvider(settings.retrieval_base_url)
        provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        return provider

    monkeypatch.setattr(ask_route, "build_retrieval_provider", build)


def _text_only_plan() -> str:
    return json.dumps(
        {
            "question_type": "other",
            "required_modalities": ["text"],
            "tasks": [{"task": "answer from prose", "modality": "text"}],
            "target_references": [],
            "requires_cross_modal": False,
            "paper_scope": "any",
            "paper_ids": [],
            "sub_questions": [],
            "confidence": 0.8,
        }
    )


def _table_record() -> dict:
    return {
        "paper_id": PAPER,
        "element_id": "table_1",
        "type": "table",
        "page": 4,
        "caption": "Table 1: Results",
        "content": "| Model | Accuracy |\n|---|---:|\n| A | 0.71 |\n| B | 0.83 |",
        "table_data": {
            "headers": ["Model", "Accuracy"],
            "rows": [["A", "0.71"], ["B", "0.83"]],
        },
    }


def test_ask_adds_table_route_when_model_returns_text_only(make_client, monkeypatch):
    client = make_client(retrieval_mode="http", retrieval_base_url="http://retriever")
    _wire_retrieval(client, monkeypatch, [_table_record()])
    provider = MockModelProvider(
        responses=[
            ("Query Analyzer", _text_only_plan()),
            (
                "Table Reasoning Agent",
                json.dumps(
                    {
                        "findings": [
                            {
                                "claim_id": "best",
                                "kind": "table_comparison",
                                "text": "B has the highest Accuracy at 0.83.",
                                "evidence_ids": [TABLE_ID],
                                "confidence": 0.9,
                            }
                        ]
                    }
                ),
            ),
            (
                "Judge",
                json.dumps(
                    {
                        "verdicts": [
                            {
                                "claim_id": "best",
                                "verdict": "SUPPORTED",
                                "rationale": "The cited row and value are present.",
                                "evidence_ids_support": [TABLE_ID],
                            }
                        ]
                    }
                ),
            ),
            ("Answer Generator", json.dumps({"answer": "B is best."})),
        ]
    )
    client.app.state.registry._provider = provider

    response = client.post("/api/v1/ask", json={"query": "Which method performs best?"})

    assert response.status_code == 200
    body = response.json()
    assert "table" in body["plan"]["required_modalities"]
    assert body["metadata"]["agent_status"]["table_reasoner"] == "ok"
    assert body["verification"]["status"] == "supported"
    assert body["citations"][0]["evidence_id"] == TABLE_ID


def test_ask_reports_partial_when_claims_are_all_unsupported(make_client, monkeypatch):
    client = make_client(retrieval_mode="http", retrieval_base_url="http://retriever")
    _wire_retrieval(
        client,
        monkeypatch,
        [{"paper_id": PAPER, "element_id": "text_1", "type": "text", "content": "Only context."}],
    )
    provider = MockModelProvider(
        responses=[
            ("Query Analyzer", _text_only_plan()),
            (
                "Text Reasoning Agent",
                json.dumps(
                    {
                        "findings": [
                            {
                                "claim_id": "unsupported",
                                "kind": "author_claim",
                                "text": "The paper contains an undocumented pixel width of 77.",
                                "evidence_ids": [f"{PAPER}:text_1"],
                                "confidence": 0.8,
                            }
                        ]
                    }
                ),
            ),
            (
                "Judge",
                json.dumps(
                    {
                        "verdicts": [
                            {
                                "claim_id": "unsupported",
                                "verdict": "UNSUPPORTED",
                                "rationale": "The evidence does not mention the measurement.",
                                "evidence_ids_support": [],
                            }
                        ]
                    }
                ),
            ),
        ]
    )
    client.app.state.registry._provider = provider

    body = client.post("/api/v1/ask", json={"query": "What is the pixel width?"}).json()

    assert body["status"] == "partial"
    assert body["verification"]["status"] == "unsupported"
    assert body["citations"] == []
    assert "does not support" in body["answer"].lower()
