"""Deterministic mock provider for offline tests, CI and demos.

Behaviour is fully reproducible: no randomness, no clock dependence in the
payload. Tests can simulate provider failure and timeouts explicitly.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Sequence

from app.core.errors import ModelTimeoutError, ModelUnavailableError, ReasoningError
from app.models.base import ChatRequest, ChatResponse, ModelProvider
from app.schemas.errors import ErrorCode
from app.schemas.health import ProviderHealth

DEFAULT_PLAIN_TEXT = "MOCK RESPONSE"


class MockModelProvider(ModelProvider):
    """Deterministic :class:`ModelProvider` double.

    Args:
        responses: ``(needle, reply)`` pairs; the first pair whose needle
            appears in the concatenated prompt wins.
        default_text: reply used when nothing matches (plain-text mode).
        fail_times: fail the first N calls (simulates transient outage, then
            recovery — useful for retry tests).
        failure_code: which typed error the simulated failure raises.
        delay_s: artificial latency, used to exercise timeout handling.
        reachable: value reported by :meth:`health`.
        models: models reported by :meth:"health"; ``None`` = "cannot enumerate".
    """

    name = "mock"

    def __init__(
        self,
        *,
        responses: Sequence[tuple[str, str]] = (),
        default_text: str = DEFAULT_PLAIN_TEXT,
        fail_times: int = 0,
        failure_code: ErrorCode = ErrorCode.MODEL_UNAVAILABLE,
        delay_s: float = 0.0,
        reachable: bool = True,
        models: list[str] | None = None,
    ) -> None:
        self._responses = list(responses)
        self._default_text = default_text
        self._fail_remaining = fail_times
        self._failure_code = failure_code
        self._delay_s = delay_s
        self._reachable = reachable
        self._models = models
        self.call_count = 0

    # --- internals ---------------------------------------------------------
    def _prompt_text(self, request: ChatRequest) -> str:
        return "\n".join(message.content for message in request.messages)

    def _build_text(self, request: ChatRequest) -> str:
        prompt = self._prompt_text(request)
        for needle, reply in self._responses:
            if needle in prompt:
                return reply
        if request.response_format == "json":
            digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
            return json.dumps(
                {
                    "mock": True,
                    "model": request.model,
                    "prompt_sha256": digest,
                    "messages": len(request.messages),
                }
            )
        return self._default_text

    async def _produce(self, request: ChatRequest) -> ChatResponse:
        if self._delay_s > 0:
            await asyncio.sleep(self._delay_s)
        if self._fail_remaining > 0:
            self._fail_remaining -= 1
            if self._failure_code is ErrorCode.MODEL_TIMEOUT:
                raise ModelTimeoutError("simulated provider timeout")
            raise ModelUnavailableError("simulated provider outage")
        return ChatResponse(
            text=self._build_text(request),
            model=request.model,
            provider=self.name,
            finish_reason="stop",
            latency_ms=int(self._delay_s * 1000),
        )

    # --- interface ---------------------------------------------------------
    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.call_count += 1
        timeout = request.timeout_s
        if timeout is None:
            return await self._produce(request)
        try:
            # Providers own timeout enforcement (ARCHITECTURE §6).
            return await asyncio.wait_for(self._produce(request), timeout=timeout)
        except TimeoutError as exc:  # asyncio.TimeoutError is TimeoutError on 3.11+
            raise ModelTimeoutError(
                f"mock provider exceeded timeout of {timeout:.2f}s"
            ) from exc
        except ReasoningError:
            raise

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            reachable=self._reachable,
            models=self._models,
            detail=None if self._reachable else "mock provider reported unreachable",
        )
