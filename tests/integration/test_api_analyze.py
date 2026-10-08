"""``POST /api/v1/analyze`` integration tests (Phase 2).

The endpoint is exercised through the real ASGI app (FastAPI TestClient).
All network/model calls stay offline via :class:`MockModelProvider`.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import load_mock_evidence


def _valid_plan(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "question_type": "other",
        "required_modalities": ["text"],
        "tasks": [{"task": "answer from text", "modality": "text"}],
        "target_references": [],
        "requires_cross_modal": False,
        "paper_scope": "any",
        "paper_ids": [],
        "sub_questions": [],
        "confidence": 0.9,
    }
    base.update(overrides)
    return base


def _valid_text_findings(evidence_ids: list[str] | None = None) -> dict[str, Any]:
    evidence_ids = evidence_ids or ["e_p001_p1_abs"]
    return {
        "findings": [
            {
                "claim_id": "cl1",
                "kind": "author_claim",
                "text": "We evaluate on SPIQA.",
                "evidence_ids": evidence_ids,
                "confidence": 0.9,
            }
        ]
    }


def _payload(
    query: str = "Which method performed best in Table 3?",
    evidence: object | None = None,
    *,
    query_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal, schema-valid ``AnalyzeRequest`` payload."""
    payload: dict[str, Any] = {
        "query": query,
        "evidence": evidence if evidence is not None else load_mock_evidence(),
    }
    if query_overrides is not None:
        payload["query"] = query_overrides.get("query", query)
    return payload


# --- happy paths -------------------------------------------------------------


def test_analyze_text_query_returns_plan_and_claims(make_client: Any) -> None:
    client: TestClient = make_client()  # type: ignore[operator]

    # Patch the mock provider's responses for this test via the app's registry.
    # Each request's mock provider is freshly constructed from Settings, so we
    # override the provider after creation (a small, self-contained shim).
    from app.models.mock import MockModelProvider
    from app.schemas.evidence import EvidenceBundle

    def text_override(request):  # type: ignore[no-untyped-def]
        band = request.model
        body = json.loads(request.content)
        if isinstance(body, dict) and "Query Analyzer" in str(body):
            return json.dumps(_valid_plan())
        return json.dumps(_valid_text_findings())

    # Replace with a provider that knows both payloads.
    class DualMock(MockModelProvider):
        name = "mock"

        def __init__(self) -> None:
            super().__init__(
                responses=[
                    ("Query Analyzer", json.dumps(_valid_plan())),
                    ("Text Reasoning Agent", json.dumps(_valid_text_findings())),
                ]
            )

    dual = DualMock()
    client.app.state.registry._provider = dual  # short-circuit for this test

    response = client.post("/api/v1/analyze", json=_payload("simple text question"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "partial"}
    assert body["request_id"] == response.headers["x-request-id"]
    assert body["plan"] is not None
    assert body["tasks"]
    assert body["plan"]["question_type"]
    # at least the text reasoning run plus the analyzer run
    assert [run["agent"] for run in body["agent_outputs"]] == ["query_analyzer", "text_reasoner"]


def test_analyze_mixed_query_defers_table_and_figure(make_client: Any) -> None:
    from app.models.mock import MockModelProvider

    dual = MockModelProvider(
        responses=[
            (
                "Mixed",
                json.dumps(
                    _valid_plan(
                        question_type="cross_modal_comparison",
                        required_modalities=["text", "table", "figure"],
                        tasks=[
                            {"task": "compare Table 3", "modality": "table"},
                            {"task": "trend Figure 5", "modality": "figure"},
                            {"task": "explain", "modality": "text"},
                        ],
                        target_references=["Table 3", "Figure 5"],
                    )
                ),
            ),
            ("Text Reasoning Agent", json.dumps(_valid_text_findings())),
        ]
    )
    client: TestClient = make_client()  # type: ignore[operator]
    client.app.state.registry._provider = dual  # type: ignore[attr-defined]

    response = client.post(
        "/api/v1/analyze",
        json=_payload("Mixed text/table/figure question"),
    )

    assert response.status_code == 200
    body = response.json()
    by_modality = {task["modality"]: task for task in body["tasks"]}
    assert by_modality["text"]["status"] == "executable"
    assert by_modality["table"]["status"] == "deferred"
    assert by_modality["figure"]["status"] == "deferred"
    assert all("Phase 3" in task["reason"] for task in body["tasks"] if task["modality"] in {"table", "figure"})


def test_analyze_returns_malformed_model_output_as_degraded(make_client: Any) -> None:
    from app.models.mock import MockModelProvider

    provider = MockModelProvider(responses=[("table", "not json at all")])
    client: TestClient = make_client()  # type: ignore[operator]
    client.app.state.registry._provider = provider  # type: ignore[attr-defined]

    response = client.post("/api/v1/analyze", json=_payload("What is in Table 3?"))

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] is not None
    assert any(run["status"] == "degraded" for run in body["agent_outputs"])


def test_analyze_with_insufficient_text_evidence_returns_empty_claims(
    make_client: Any,
) -> None:
    from app.models.mock import MockModelProvider

    provider = MockModelProvider(
        responses=[
            ("no support", json.dumps(_valid_plan())),
            ("Text Reasoning Agent", json.dumps({"findings": []})),
        ]
    )
    client: TestClient = make_client()  # type: ignore[operator]
    client.app.state.registry._provider = provider  # type: ignore[attr-defined]

    response = client.post(
        "/api/v1/analyze", json=_payload("question with no support")
    )

    assert response.status_code == 200
    assert response.json()["claims"] == []


def test_request_id_is_propagated_and_echoed(make_client: Any) -> None:
    from app.models.mock import MockModelProvider

    provider = MockModelProvider(
        responses=[
            ("Q", json.dumps(_valid_plan())),
            ("Text Reasoning Agent", json.dumps({"findings": []})),
        ]
    )
    client: TestClient = make_client()  # type: ignore[operator]
    client.app.state.registry._provider = provider  # type: ignore[attr-defined]

    response = client.post(
        "/api/v1/analyze",
        json=_payload("Q"),
        headers={"X-Request-ID": "phase2-trace"},
    )

    assert response.headers["x-request-id"] == "phase2-trace"
    assert response.json()["request_id"] == "phase2-trace"


# --- error paths -------------------------------------------------------------


def test_analyze_rejects_empty_evidence(make_client: Any) -> None:
    client: TestClient = make_client()  # type: ignore[operator]
    payload = _payload(evidence={"papers": [], "evidence": []})

    response = client.post("/api/v1/analyze", json=payload)

    assert response.status_code == 400
    assert response.json()["code"] == "EVIDENCE_EMPTY"
    assert response.json()["request_id"]


def test_analyze_rejects_image_path_traversal(make_client: Any) -> None:
    client: TestClient = make_client()  # type: ignore[operator]
    bundle = load_mock_evidence()
    bundle["evidence"][0]["image"] = {"path": "../../etc/passwd"}

    response = client.post("/api/v1/analyze", json=_payload(evidence=bundle))

    assert response.status_code == 400
    assert response.json()["code"] == "IMAGE_PATH_FORBIDDEN"


def test_analyze_rejects_schema_invalid_evidence(make_client: Any) -> None:
    client: TestClient = make_client()  # type: ignore[operator]
    bundle = load_mock_evidence()
    bundle["evidence"][0]["type"] = "unknown"

    response = client.post("/api/v1/analyze", json=_payload(evidence=bundle))

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"


def test_analyze_malformed_body_is_400(make_client: Any) -> None:
    client: TestClient = make_client()  # type: ignore[operator]

    response = client.post(
        "/api/v1/analyze", json={"nonsense": True}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"


def test_analyze_exposes_openapi(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    path = schema["paths"]["/api/v1/analyze"]

    assert "post" in path
    assert "AnalyzeRequest" in str(schema["components"]["schemas"])
    assert "AnalyzeResponse" in str(schema["components"]["schemas"])


def test_analyze_never_fakes_table_findings_for_a_table_question(
    make_client: Any,
) -> None:
    """Table-only questions must be left as deferred — no text-agent claims."""
    from app.models.mock import MockModelProvider

    provider = MockModelProvider(
        responses=[
            (
                "Table",
                json.dumps(
                    _valid_plan(
                        required_modalities=["table"],
                        tasks=[{"task": "rank Table 5", "modality": "table"}],
                    )
                ),
            )
        ]
    )
    client: TestClient = make_client()  # type: ignore[operator]
    client.app.state.registry._provider = provider  # type: ignore[attr-defined]

    response = client.post("/api/v1/analyze", json=_payload("only Table 5"))

    assert response.status_code == 200
    body = response.json()
    assert not body["claims"], "no text-agent claims should exist for a table-only task"
    # The only produced task is for the table modality — it must be deferred.
    table_tasks = [task for task in body["tasks"] if task["modality"] == "table"]
    assert table_tasks and all(task["status"] == "deferred" for task in table_tasks)


def test_analyze_evidence_ids_are_within_the_bundle(make_client: Any) -> None:
    """Every generated claim's evidence_ids ⊆ the supplied ids."""
    from app.models.mock import MockModelProvider

    known_ids = {item["evidence_id"] for item in load_mock_evidence()["evidence"]}
    provider = MockModelProvider(
        responses=[
            ("happy path", json.dumps(_valid_plan())),
            (
                "Text Reasoning Agent",
                json.dumps(
                    {
                        "findings": [
                            {
                                "claim_id": "cl1",
                                "kind": "author_claim",
                                "text": "honest claim",
                                "evidence_ids": list(known_ids)[:2],
                                "confidence": 0.9,
                            }
                        ]
                    }
                ),
            ),
        ]
    )
    client: TestClient = make_client()  # type: ignore[operator]
    client.app.state.registry._provider = provider  # type: ignore[attr-defined]

    response = client.post("/api/v1/analyze", json=_payload("happy path"))

    assert response.status_code == 200
    for claim in response.json()["claims"]:
        assert set(claim["evidence_ids"]) <= known_ids


def test_analyze_drop_on_unknown_evidence_id_is_honest(make_client: Any) -> None:
    """A claim citing an unknown id is dropped, not fabricated."""
    from app.models.mock import MockModelProvider

    provider = MockModelProvider(
        responses=[
            ("Q", json.dumps(_valid_plan())),
            (
                "Text Reasoning Agent",
                json.dumps(
                    {
                        "findings": [
                            {
                                "claim_id": "bad",
                                "kind": "author_claim",
                                "text": "bad claim",
                                "evidence_ids": ["e_does_not_exist"],
                                "confidence": 0.9,
                            }
                        ]
                    }
                ),
            ),
        ]
    )
    client: TestClient = make_client()  # type: ignore[operator]
    client.app.state.registry._provider = provider  # type: ignore[attr-defined]

    response = client.post("/api/v1/analyze", json=_payload("Q"))

    assert response.status_code == 200
    assert response.json()["claims"] == []
