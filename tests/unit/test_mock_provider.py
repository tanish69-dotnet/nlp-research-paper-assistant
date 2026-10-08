"""Mock provider tests (Phase 1 §18).

Async provider calls are driven through ``run()`` from conftest — no
pytest-asyncio dependency.
"""

from __future__ import annotations

import json

import pytest

from app.core.errors import ModelTimeoutError, ModelUnavailableError
from app.models.base import ChatMessage, ChatRequest, ChatResponse
from app.models.mock import MockModelProvider
from app.schemas.errors import ErrorCode
from tests.conftest import run


def _request(content: str = "hello", **kwargs: object) -> ChatRequest:
    return ChatRequest(
        model=kwargs.pop("model", "test-model"),  # type: ignore[arg-type]
        messages=[ChatMessage(role="user", content=content)],
        **kwargs,  # type: ignore[arg-type]
    )


def test_default_plain_text_response() -> None:
    provider = MockModelProvider()

    response = run(provider.chat(_request(response_format="text")))

    assert isinstance(response, ChatResponse)
    assert response.text == "MOCK RESPONSE"
    assert response.provider == "mock"
    assert response.finish_reason == "stop"


def test_json_mode_returns_deterministic_object() -> None:
    provider = MockModelProvider()

    response = run(provider.chat(_request(response_format="json")))

    data = json.loads(response.text)
    assert data["mock"] is True
    assert data["model"] == "test-model"
    assert data["prompt_sha256"]


def test_same_input_yields_identical_output() -> None:
    """Reproducibility: no randomness, no clock in the payload."""
    provider_a = MockModelProvider()
    provider_b = MockModelProvider()

    first = run(provider_a.chat(_request("same input", response_format="json")))
    second = run(provider_b.chat(_request("same input", response_format="json")))

    assert first.text == second.text


def test_matched_needle_returns_custom_reply() -> None:
    provider = MockModelProvider(
        responses=[("table", "TABLE HANDLED"), ("figure", "FIGURE HANDLED")],
        default_text="DEFAULT",
    )

    table = run(provider.chat(_request("this is a table")))
    figure = run(provider.chat(_request("here is a figure")))
    other = run(provider.chat(_request("plain prose")))

    assert table.text == "TABLE HANDLED"
    assert figure.text == "FIGURE HANDLED"
    assert other.text == "DEFAULT"


def test_failure_then_recovery() -> None:
    provider = MockModelProvider(fail_times=2)

    with pytest.raises(ModelUnavailableError):
        run(provider.chat(_request("1")))
    with pytest.raises(ModelUnavailableError):
        run(provider.chat(_request("2")))

    recovered = run(provider.chat(_request("3")))
    assert recovered.text == "MOCK RESPONSE"


def test_timeout_failure_code() -> None:
    provider = MockModelProvider(
        fail_times=1, failure_code=ErrorCode.MODEL_TIMEOUT
    )

    with pytest.raises(ModelTimeoutError):
        run(provider.chat(_request("x")))


def test_request_timeout_is_enforced() -> None:
    provider = MockModelProvider(delay_s=0.5)

    with pytest.raises(ModelTimeoutError):
        run(provider.chat(_request("x", timeout_s=0.05)))


def test_health_reports_reachable_with_models() -> None:
    provider = MockModelProvider(reachable=True, models=["model-a", "model-b"])

    health = run(provider.health())

    assert health.reachable is True
    assert health.models == ["model-a", "model-b"]


def test_health_reports_unreachable() -> None:
    provider = MockModelProvider(reachable=False)

    health = run(provider.health())

    assert health.reachable is False
    assert health.models is None
    assert health.detail is not None


def test_call_count_increments() -> None:
    provider = MockModelProvider()

    run(provider.chat(_request("1")))
    run(provider.chat(_request("2")))

    assert provider.call_count == 2


def test_call_count_increments_on_failure() -> None:
    provider = MockModelProvider(fail_times=1)

    with pytest.raises(ModelUnavailableError):
        run(provider.chat(_request("x")))

    assert provider.call_count == 1