"""Ollama provider tests — mocked HTTP only (offline-first, Phase 1 §18).

Uses ``httpx.MockTransport`` (ships with httpx): no network, no Ollama server,
no extra dependencies.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.errors import (
    MalformedModelOutputError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from app.models.base import ChatMessage, ChatRequest, ChatResponse, ImagePayload
from app.models.ollama import OllamaModelProvider
from tests.conftest import run

Handler = Any  # (httpx.Request) -> httpx.Response


def _provider(handler: Handler, **kwargs: Any) -> OllamaModelProvider:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://ollama.test",
    )
    return OllamaModelProvider(base_url="http://ollama.test", client=client, **kwargs)


def _request(**overrides: Any) -> ChatRequest:
    payload: dict[str, Any] = {
        "model": "test-model",
        "messages": [ChatMessage(role="user", content="hi")],
    }
    payload.update(overrides)
    return ChatRequest(**payload)


# --- success -----------------------------------------------------------------


def test_chat_success_parses_message_and_usage() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json_loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "message": {"role": "assistant", "content": "hello from ollama"},
                "done_reason": "stop",
                "prompt_eval_count": 12,
                "eval_count": 34,
            },
        )

    response = run(_provider(handler).chat(_request()))

    assert isinstance(response, ChatResponse)
    assert response.text == "hello from ollama"
    assert response.model == "test-model"
    assert response.provider == "ollama"
    assert response.finish_reason == "stop"
    assert response.usage.prompt_tokens == 12
    assert response.usage.completion_tokens == 34
    assert response.latency_ms >= 0
    # request shape
    assert captured["json"]["model"] == "test-model"
    assert captured["json"]["stream"] is False
    assert captured["json"]["messages"][0] == {"role": "user", "content": "hi"}


def test_chat_json_mode_sets_format_field() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json_loads(request.content)
        return httpx.Response(
            200, json={"message": {"role": "assistant", "content": "{}"}, "done": True}
        )

    run(_provider(handler).chat(_request(response_format="json")))

    assert captured["json"]["format"] == "json"


def test_chat_forwards_images_and_options() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json_loads(request.content)
        return httpx.Response(
            200, json={"message": {"role": "assistant", "content": "described"}}
        )

    run(
        _provider(handler).chat(
            _request(
                messages=[
                    ChatMessage(
                        role="user",
                        content="describe",
                        images=[ImagePayload(b64="QUJD")],
                    )
                ],
                temperature=0.2,
                max_tokens=128,
            )
        )
    )

    message = captured["json"]["messages"][0]
    assert message["images"] == ["QUJD"]
    assert captured["json"]["options"] == {"temperature": 0.2, "num_predict": 128}


# --- failure paths -----------------------------------------------------------


def test_connection_error_maps_to_model_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(ModelUnavailableError, match="ollama unreachable") as excinfo:
        run(_provider(handler).chat(_request()))

    assert excinfo.value.code.value == "MODEL_UNAVAILABLE"
    assert excinfo.value.retryable is True


def test_timeout_maps_to_model_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(ModelTimeoutError, match="timed out") as excinfo:
        run(_provider(handler).chat(_request()))

    assert excinfo.value.code.value == "MODEL_TIMEOUT"
    assert excinfo.value.retryable is True


def test_model_not_found_maps_to_model_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'ghost' not found"})

    with pytest.raises(ModelUnavailableError, match="not available on ollama"):
        run(_provider(handler).chat(_request()))


def test_server_error_maps_to_model_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "server exploded"})

    with pytest.raises(ModelUnavailableError, match="HTTP 500"):
        run(_provider(handler).chat(_request()))


def test_malformed_response_missing_message_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"done": True, "model": "test-model"})

    with pytest.raises(MalformedModelOutputError, match="message.content"):
        run(_provider(handler).chat(_request()))


def test_non_json_body_is_malformed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway error</html>")

    with pytest.raises(MalformedModelOutputError, match="non-JSON body"):
        run(_provider(handler).chat(_request()))


def test_unconfigured_model_is_rejected_locally() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no HTTP call should be made")

    with pytest.raises(ModelUnavailableError, match="model not configured"):
        run(_provider(handler).chat(_request(model="   ")))


# --- health ------------------------------------------------------------------


def test_health_lists_installed_models() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "llama3.1:8b", "size": 1},
                    {"name": "llama3.2-vision:latest", "size": 2},
                ]
            },
        )

    health = run(_provider(handler).health())

    assert health.reachable is True
    assert health.models == ["llama3.1:8b", "llama3.2-vision:latest"]


def test_health_never_raises_when_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    health = run(_provider(handler).health())

    assert health.reachable is False
    assert health.models is None
    assert health.detail is not None
    assert "ConnectError" in health.detail


def test_health_malformed_payload_is_graceful() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    health = run(_provider(handler).health())

    assert health.reachable is False


def json_loads(content: bytes) -> Any:
    import json

    return json.loads(content)