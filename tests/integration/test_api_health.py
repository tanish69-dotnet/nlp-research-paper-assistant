"""Integration tests for /health and /models (Phase 1 §18).

These run the real ASGI app through TestClient. Provider calls are offline:
the mock provider for happy paths, and a closed local port for the
"Ollama is down" path.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

# A port that is virtually guaranteed to refuse connections immediately.
UNREACHABLE_OLLAMA = "http://127.0.0.1:1"


# --- /health -----------------------------------------------------------------


def test_health_shallow_returns_200_without_network(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert body["request_id"]
    assert body["checks"]["evidence_root"] in {"ok", "missing"}
    assert body["checks"]["prompts"] == "ok"
    assert body["uptime_s"] >= 0
    # shallow check performs no provider ping: reachable is explicitly null
    assert body["providers"][0]["reachable"] is None
    assert "not checked" in body["providers"][0]["detail"]


def test_health_deep_with_mock_provider_reports_reachable(client: TestClient) -> None:
    response = client.get("/api/v1/health", params={"deep": "true"})

    assert response.status_code == 200
    body = response.json()
    assert body["providers"][0]["name"] == "mock"
    assert body["providers"][0]["reachable"] is True
    assert body["status"] == "ok"


def test_health_deep_degrades_when_provider_down(make_client: object) -> None:
    client = make_client(  # type: ignore[operator]
        model_provider="ollama", ollama_base_url=UNREACHABLE_OLLAMA
    )
    response = client.get("/api/v1/health", params={"deep": "true"})

    assert response.status_code == 200  # service itself is healthy
    body = response.json()
    assert body["status"] == "degraded"
    assert body["providers"][0]["reachable"] is False


def test_request_id_is_generated_and_echoed_in_header(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.headers["x-request-id"] == response.json()["request_id"]


def test_inbound_request_id_is_preserved(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health", headers={"X-Request-ID": "trace-abc-123"}
    )

    assert response.json()["request_id"] == "trace-abc-123"
    assert response.headers["x-request-id"] == "trace-abc-123"


def test_hostile_inbound_request_id_is_replaced(client: TestClient) -> None:
    hostile = "bad id\nwith newline and <script>"
    response = client.get("/api/v1/health", headers={"X-Request-ID": hostile})

    generated = response.json()["request_id"]
    assert generated != hostile
    assert len(generated) == 32  # uuid4().hex
    assert response.headers["x-request-id"] == generated


# --- /models -----------------------------------------------------------------


def test_models_lists_all_roles_with_mock_provider(client: TestClient) -> None:
    response = client.get("/api/v1/models")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "mock"
    assert body["request_id"]

    roles = {role["role"]: role for role in body["roles"]}
    assert set(roles) == {
        "analyzer",
        "text_reasoner",
        "table_reasoner",
        "vision_reasoner",
        "judge",
        "generator",
    }
    # nothing configured in this test client -> reported, not crashed
    assert roles["judge"]["available"] is False
    assert roles["judge"]["detail"] == "model not configured"
    assert roles["vision_reasoner"]["vision"] is True
    assert roles["judge"]["vision"] is False


def test_models_marks_configured_role_available(make_client: object) -> None:
    client = make_client(text_model="some-local-model")  # type: ignore[operator]

    body = client.get("/api/v1/models").json()
    roles = {role["role"]: role for role in body["roles"]}

    assert roles["text_reasoner"]["available"] is True
    assert roles["text_reasoner"]["model"] == "some-local-model"
    assert roles["judge"]["available"] is False


def test_models_survives_ollama_downtime(make_client: object) -> None:
    """Acceptance: /models must not crash when Ollama is unavailable."""
    client = make_client(  # type: ignore[operator]
        model_provider="ollama",
        ollama_base_url=UNREACHABLE_OLLAMA,
        text_model="llama3.1:8b",
    )

    response = client.get("/api/v1/models")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "ollama"
    assert body["roles"]
    assert all(role["available"] is False for role in body["roles"])
    assert all(role["detail"] for role in body["roles"])


def test_models_never_exposes_secrets(make_client: object) -> None:
    client = make_client(  # type: ignore[operator]
        openai_compat_api_key="sk-should-never-appear"
    )

    raw = client.get("/api/v1/models").text

    assert "sk-should-never-appear" not in raw


def test_app_starts_with_ollama_unavailable(make_client: object) -> None:
    """Acceptance: startup must not depend on a running Ollama server."""
    client = make_client(  # type: ignore[operator]
        model_provider="ollama", ollama_base_url=UNREACHABLE_OLLAMA
    )

    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/models").status_code == 200