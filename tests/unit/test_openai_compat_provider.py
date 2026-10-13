"""OpenAI-compatible provider tests (deployment inference path).

Offline: a fake httpx transport stands in for the gateway. Covers JSON-mode
payloads, vision image_url parts, typed errors, and health reporting.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.errors import ModelTimeoutError, ModelUnavailableError
from app.models.base import ChatMessage, ChatRequest, ImagePayload
from app.models.openai_compat import OpenAICompatProvider
from tests.conftest import run


def _provider(handler, **kwargs) -> OpenAICompatProvider:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://gateway.example"
    )
    return OpenAICompatProvider("https://gateway.example/v1", client=client, **kwargs)


def _request(**overrides) -> ChatRequest:
    base = {
        "model": "qwen2.5:1.5b",
        "messages": [ChatMessage(role="user", content="Say hi in JSON.")],
        "response_format": "json",
    }
    base.update(overrides)
    return ChatRequest(**base)


def _completion(text: str, model: str = "qwen2.5:1.5b") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": model,
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


def test_chat_sends_json_mode_and_parses_reply():
    seen: dict = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return _completion('{"findings": []}')

    response = run(_provider(handle).chat(_request()))

    assert response.text == '{"findings": []}'
    assert seen["model"] == "qwen2.5:1.5b"
    assert seen["response_format"] == {"type": "json_object"}
    assert response.provider == "openai_compat"


def test_vision_images_become_image_url_parts():
    seen: dict = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return _completion('{"findings": []}')

    request = _request(messages=[
        ChatMessage(
            role="user",
            content="Describe it.",
            images=[ImagePayload(b64="QUJD", mime="image/png")],
        )
    ])
    run(_provider(handle).chat(request))

    parts = seen["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "Describe it."}
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,QUJD")


def test_auth_failure_is_unavailable_not_crash():
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad key")

    with pytest.raises(ModelUnavailableError):
        run(_provider(handle).chat(_request()))


def test_timeout_maps_to_typed_error():
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(ModelTimeoutError):
        run(_provider(handle, default_timeout_s=1.0).chat(_request()))


def test_health_lists_models():
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "qwen2.5:1.5b"}]})

    health = run(_provider(handle).health())

    assert health.reachable is True
    assert health.models == ["qwen2.5:1.5b"]


def test_health_never_raises():
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    health = run(_provider(handle).health())

    assert health.reachable is False
