"""Error-model integration tests (API_SPEC §6)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.errors import install_exception_handlers
from app.api.middleware import RequestContextMiddleware

PROBLEM_KEYS = {"type", "title", "status", "detail", "code", "request_id", "retryable"}


def test_invalid_query_parameter_returns_problem_detail(client: TestClient) -> None:
    response = client.get("/api/v1/health", params={"deep": "not-a-boolean"})

    assert response.status_code == 400
    body = response.json()
    assert set(body) == PROBLEM_KEYS
    assert body["code"] == "INVALID_REQUEST"
    assert body["type"] == "https://researchlens.local/errors/INVALID_REQUEST"
    assert body["retryable"] is False
    assert body["request_id"] == response.headers["x-request-id"]


def test_unknown_route_returns_not_found_problem(client: TestClient) -> None:
    response = client.get("/api/v1/nope")

    assert response.status_code == 404
    body = response.json()
    assert set(body) == PROBLEM_KEYS
    assert body["code"] == "NOT_FOUND"


def test_oversized_body_returns_payload_too_large(make_client: object) -> None:
    client = make_client(max_request_bytes=256)  # type: ignore[operator]

    response = client.post(
        "/api/v1/health",
        content=b"x" * 1024,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    body = response.json()
    assert set(body) == PROBLEM_KEYS
    assert body["code"] == "PAYLOAD_TOO_LARGE"
    assert body["request_id"] == response.headers["x-request-id"]


def test_unexpected_exception_is_masked_without_stack_trace() -> None:
    """SECURITY.md §6: internal details stay in logs, clients get a stable code."""
    app = FastAPI()
    install_exception_handlers(app)
    app.add_middleware(RequestContextMiddleware)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail: sk-must-not-leak")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert set(body) == PROBLEM_KEYS
    assert body["code"] == "INTERNAL_ERROR"
    assert "Traceback" not in body["detail"]
    assert "sk-must-not-leak" not in response.text


def test_error_bodies_carry_request_id_for_correlation(client: TestClient) -> None:
    response = client.get(
        "/api/v1/nope", headers={"X-Request-ID": "corr-42"}
    )

    assert response.json()["request_id"] == "corr-42"