"""Integration tests for Person 2 retrieval + reasoning pipeline.

Start the app with RETRIEVAL_MODE=mock or http; hit POST /ask with a question.
Behind the scenes, /ask asks the remote retriever, validates, maps,
then drives the same validated multi-LLM pipeline used by /reason.
All tests below run entirely offline via mocked HTTP — no network/GPU.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_ask_rejects_when_disabled(client: TestClient) -> None:
    r = client.post("/api/v1/ask", json={"query": "Which model performs best?"})
    assert r.status_code in (503, 500)
    body = r.json()
    assert body["code"] in ("MODEL_UNAVAILABLE", "INTERNAL_ERROR")
