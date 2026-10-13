"""OpenAI-compatible provider (cloud inference for deployment).

Speaks the ``/chat/completions`` protocol used by OpenRouter, Together,
Groq, fireworks, local vLLM/LM Studio, and any other OpenAI-compatible
gateway, so cloud deployments are not tied to a local Ollama server.

Vision: images are sent as ``image_url`` data-URL parts (OpenAI chat format).
Only roles configured with a vision-capable model name should receive
``images`` — the caller contract is unchanged (ARCHITECTURE §5 capability
rule enforced by the registry/orchestrator, not here).

Auth: ``OPENAI_COMPAT_API_KEY`` from the environment only, never logged.
"""

from __future__ import annotations

import time

import httpx

from app.core.errors import (
    MalformedModelOutputError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from app.models.base import ChatRequest, ChatResponse, ModelProvider
from app.schemas.claims import TokenUsage
from app.schemas.health import ProviderHealth


class OpenAICompatProvider(ModelProvider):
    """Minimal ``/chat/completions`` client (JSON mode supported)."""

    name = "openai_compat"

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        default_timeout_s: float = 120.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key or ""
        self._default_timeout_s = default_timeout_s
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            self._client = httpx.AsyncClient(base_url=self._base_url, headers=headers)
        return self._client

    @staticmethod
    def _to_openai_messages(request: ChatRequest) -> list[dict]:
        messages: list[dict] = []
        for message in request.messages:
            if not message.images:
                messages.append({"role": message.role, "content": message.content})
                continue
            parts: list[dict] = [{"type": "text", "text": message.content}]
            for image in message.images:
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{image.mime};base64,{image.b64}"},
                    }
                )
            messages.append({"role": message.role, "content": parts})
        return messages

    def _payload(self, request: ChatRequest) -> dict:
        payload: dict = {
            "model": request.model,
            "messages": self._to_openai_messages(request),
            "stream": False,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        return payload

    async def chat(self, request: ChatRequest) -> ChatResponse:
        model = request.model.strip()
        if not model:
            raise ModelUnavailableError("model not configured for this role")
        timeout = request.timeout_s if request.timeout_s is not None else self._default_timeout_s
        client = await self._get_client()
        started = time.perf_counter()
        try:
            response = await client.post(
                "/chat/completions", json=self._payload(request), timeout=timeout
            )
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError(f"inference request for model '{model}' timed out") from exc
        except httpx.HTTPError as exc:
            raise ModelUnavailableError(f"inference endpoint unreachable ({type(exc).__name__})") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code >= 400:
            detail = response.text[:200] or "no detail"
            if response.status_code in (401, 403):
                raise ModelUnavailableError("inference endpoint rejected credentials")
            if response.status_code == 404:
                raise ModelUnavailableError(f"model not available on endpoint: {detail}")
            if response.status_code == 429:
                raise ModelUnavailableError(f"inference rate limited: {detail}")
            raise ModelUnavailableError(f"inference returned HTTP {response.status_code}: {detail}")
        try:
            data = response.json()
        except ValueError as exc:
            raise MalformedModelOutputError("inference returned a non-JSON body") from exc
        try:
            choice = data["choices"][0]["message"]
            content = choice.get("content")
            if isinstance(content, list):  # some gateways return content parts
                content = "".join(
                    part.get("text", "") for part in content if isinstance(part, dict)
                )
            if not isinstance(content, str) or not content:
                raise KeyError("empty content")
        except (KeyError, IndexError, TypeError) as exc:
            raise MalformedModelOutputError("inference response missing choices[0].message.content") from exc
        usage = data.get("usage") or {}
        return ChatResponse(
            text=content,
            model=str(data.get("model") or model),
            provider=self.name,
            finish_reason=(data.get("choices") or [{}])[0].get("finish_reason"),
            usage=TokenUsage(
                prompt_tokens=usage.get("prompt_tokens") if isinstance(usage.get("prompt_tokens"), int) else None,
                completion_tokens=usage.get("completion_tokens") if isinstance(usage.get("completion_tokens"), int) else None,
            ),
            latency_ms=latency_ms,
        )

    async def health(self) -> ProviderHealth:
        try:
            client = await self._get_client()
            response = await client.get("/models", timeout=10.0)
            if response.status_code in (401, 403):
                return ProviderHealth(
                    name=self.name, reachable=True, models=None,
                    detail="endpoint reachable; credentials required for /models",
                )
            response.raise_for_status()
            data = response.json()
            models: list[str] | None = None
            raw = data.get("data") if isinstance(data, dict) else None
            if isinstance(raw, list):
                models = [str(e.get("id")) for e in raw if isinstance(e, dict) and e.get("id")]
            return ProviderHealth(name=self.name, reachable=True, models=models)
        except Exception as exc:  # noqa: BLE001 - health must be total
            return ProviderHealth(
                name=self.name, reachable=False, models=None,
                detail=f"{type(exc).__name__}: {str(exc)[:120]}",
            )

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
