"""Ollama provider — local, free, default backend (ARCHITECTURE §5).

Design rules for this Phase:
- startup never depends on Ollama being reachable,
- no model is assumed to be installed and nothing is ever auto-downloaded,
- every transport/parsing failure is translated into a typed domain error.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.errors import (
    MalformedModelOutputError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from app.models.base import ChatRequest, ChatResponse, ChatMessage, ModelProvider
from app.schemas.claims import TokenUsage
from app.schemas.health import ProviderHealth


class OllamaModelProvider(ModelProvider):
    """Talks to an Ollama server's HTTP API (``/api/chat``, ``/api/tags``)."""

    name = "ollama"

    def __init__(
        self,
        base_url: str,
        *,
        default_timeout_s: float = 45.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_timeout_s = default_timeout_s
        self._client = client
        self._owns_client = client is None

    # --- transport ---------------------------------------------------------
    async def _get_client(self) -> httpx.AsyncClient:
        # Lazy: constructing the provider must not open sockets (app startup
        # stays healthy when Ollama is down).
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._base_url)
        return self._client

    @staticmethod
    def _payload(request: ChatRequest) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        for message in request.messages:
            entry: dict[str, Any] = {"role": message.role, "content": message.content}
            if message.images:
                entry["images"] = [image.b64 for image in message.images]
            messages.append(entry)

        options: dict[str, Any] = {}
        if request.temperature is not None:
            options["temperature"] = request.temperature
        if request.max_tokens is not None:
            options["num_predict"] = request.max_tokens

        payload: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "stream": False,
        }
        if options:
            payload["options"] = options
        if request.response_format == "json":
            payload["format"] = "json"
        return payload

    @staticmethod
    def _translate(exc: Exception, model: str) -> Exception:
        if isinstance(exc, httpx.TimeoutException):
            return ModelTimeoutError(f"ollama request for model '{model}' timed out")
        if isinstance(exc, httpx.HTTPError):
            return ModelUnavailableError(
                f"ollama unreachable ({type(exc).__name__})"
            )
        return exc  # pragma: no cover - defensive

    # --- interface ---------------------------------------------------------
    async def chat(self, request: ChatRequest) -> ChatResponse:
        model = request.model.strip()
        if not model:
            raise ModelUnavailableError("model not configured for this role")

        timeout = request.timeout_s if request.timeout_s is not None else self._default_timeout_s
        client = await self._get_client()
        started = time.perf_counter()

        try:
            response = await client.post(
                "/api/chat", json=self._payload(request), timeout=timeout
            )
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            raise self._translate(exc, model) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)

        if response.status_code >= 400:
            detail = self._error_detail(response)
            if response.status_code == 404 or "not found" in detail.lower():
                raise ModelUnavailableError(f"model not available on ollama: {detail}")
            raise ModelUnavailableError(
                f"ollama returned HTTP {response.status_code}: {detail}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise MalformedModelOutputError(
                "ollama returned a non-JSON body"
            ) from exc

        if not isinstance(data, dict):
            raise MalformedModelOutputError("ollama returned an unexpected JSON shape")

        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise MalformedModelOutputError(
                "ollama response is missing message.content"
            )

        usage = TokenUsage(
            prompt_tokens=_as_int(data.get("prompt_eval_count")),
            completion_tokens=_as_int(data.get("eval_count")),
        )
        return ChatResponse(
            text=content,
            model=str(data.get("model") or model),
            provider=self.name,
            finish_reason=data.get("done_reason"),
            usage=usage,
            latency_ms=latency_ms,
        )

    async def health(self) -> ProviderHealth:
        """Never raises: reachability problems are reported, not thrown."""
        try:
            client = await self._get_client()
            response = await client.get("/api/tags", timeout=5.0)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001 - health must be total
            return ProviderHealth(
                name=self.name,
                reachable=False,
                models=None,
                detail=f"{type(exc).__name__}: {str(exc)[:120]}",
            )

        models: list[str] = []
        raw_models = data.get("models") if isinstance(data, dict) else None
        if isinstance(raw_models, list):
            for entry in raw_models:
                if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                    models.append(entry["name"])
        return ProviderHealth(name=self.name, reachable=True, models=models)

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            body = response.json()
            if isinstance(body, dict) and isinstance(body.get("error"), str):
                return body["error"]
        except ValueError:
            pass
        return response.text[:200] or "no detail"


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
