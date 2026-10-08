"""OpenAPI / documentation generation tests (Phase 1 §25)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_openapi_document_generates(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "ResearchLens Reasoning Service"
    assert schema["info"]["version"]


def test_openapi_contains_phase1_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/v1/health" in paths
    assert "/api/v1/models" in paths
    assert "get" in paths["/api/v1/health"]
    assert "get" in paths["/api/v1/models"]


def test_docs_are_served(client: TestClient) -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert "swagger" in response.text.lower()


def test_redoc_is_served(client: TestClient) -> None:
    assert client.get("/redoc").status_code == 200


def test_response_models_are_declared(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    components = schema.get("components", {}).get("schemas", {})

    assert "HealthResponse" in components
    assert "ModelsResponse" in components