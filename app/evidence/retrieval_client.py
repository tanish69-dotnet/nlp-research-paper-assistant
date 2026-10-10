"""Retrieval provider abstraction (Phase 8).

Mirrors the ``ModelProvider`` pattern: an abstract interface with concrete
backends (HTTP, mock, disabled). The reasoning pipeline only depends on the
protocol; swapping backends changes config, not orchestration logic.
"""

from __future__ import annotations

import asyncio
import time
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings
from app.schemas.evidence import EvidenceBundle
from app.core.errors import ModelTimeoutError, ModelUnavailableError


@dataclass(frozen=True)
class RetrievalRequest:
    """Request sent to a retrieval backend."""

    query: str
    top_k: int
    timeout_s: float


@dataclass
class RetrievalResponse:
    """Response from a retrieval backend.

    ``bundle`` is already an ``EvidenceBundle`` (our canonical contract).
    """

    bundle: EvidenceBundle
    latency_ms: int = 0
    provider: str = ""


class RetrievalProvider(ABC):
    """Single interface every retrieval backend implements."""

    name: str = "retrieval"

    @abstractmethod
    async def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        """Run one retrieval request."""

    @abstractmethod
    async def health(self) -> bool:
        """Report reachability without raising; ``False`` means unavailable."""

    async def aclose(self) -> None:
        """Release owned resources (no-op by default)."""


class DisabledProvider(RetrievalProvider):
    """Placeholder used when ``RETRIEVAL_MODE=disabled``."""

    name = "disabled"

    async def retrieve(self, request) -> RetrievalResponse:
        # This path should never be hit — the router guards against it.
        raise RuntimeError("retrieval is disabled in configuration")

    async def health(self) -> bool:
        return False


class MockRetrievalProvider(RetrievalProvider):
    """Deterministic provider for offline tests and development."""

    name = "mock"

    def __init__(
        self,
        *,
        responses: list[tuple[str, dict]] = (),
        default_evidence: list[dict] = (),
        delay_s: float = 0.0,
    ) -> None:
        self._responses = list(responses)
        self._default_evidence = default_evidence
        self._delay_s = delay_s
        self._call_count = 0

    async def retrieve(self, request) -> RetrievalResponse:  # type: ignore[override]
        self._call_count += 1
        if self._delay_s > 0:
            await asyncio.sleep(self._delay_s)

        for needle, body in self._responses:
            if needle in request.query:
                return RetrievalResponse(
                    bundle=EvidenceBundle(evidence=body, query=request.query, papers=[]),
                    latency_ms=int(self._delay_s * 1000),
                    provider=self.name,
                )
        # Default: return the first fixture evidence list (or empty)
        return RetrievalResponse(
            bundle=EvidenceBundle(evidence=self._default_evidence, query=request.query, papers=[]),
            latency_ms=int(self._delay_s * 1000),
            provider=self.name,
        )

    async def health(self) -> bool:
        return True


class HttpRetrievalProvider(RetrievalProvider):
    """Calls Person 2's HTTP ``/retrieve`` endpoint.

    Uses ``httpx.AsyncClient`` with a per-request timeout. All transport/
    protocol errors are translated into our domain errors.
    """

    name = "http"

    def __init__(
        self,
        base_url: str,
        *,
        default_timeout_s: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_timeout_s = default_timeout_s
        self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._base_url)
        return self._client

    async def retrieve(self, request) -> RetrievalResponse:
        from app.evidence.adapter import adapt_retrieval_response

        client = await self._get_client()
        timeout = request.timeout_s if request.timeout_s > 0 else self._default_timeout_s
        started = time.perf_counter()

        try:
            response = await client.post(
                "/retrieve",
                json={"query": request.query, "top_k": request.top_k},
                timeout=timeout,
            )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise ModelTimeoutError("retrieval timeout") from exc
        except httpx.HTTPError as exc:
            raise ModelUnavailableError(f"retrieval unreachable: {exc}") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)

        if response.status_code >= 400:
            # Treat 4xx/5xx as service errors, not model unavailability
            raise ModelUnavailableError(
                f"retrieval returned HTTP {response.status_code}: {response.text[:200]}"
            )

        try:
            payload = response.json()
        except Exception as exc:
            raise ModelUnavailableError("retrieval returned non-JSON") from exc

        # Phase 8 adapter: any envelope -> our EvidenceBundle contract
        bundle = adapt_retrieval_response(payload)
        return RetrievalResponse(
            bundle=bundle,
            latency_ms=latency_ms,
            provider=self.name,
        )

    async def health(self) -> bool:
        try:
            client = await self._get_client()
            response = await client.get("/health", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def build_retrieval_provider(settings: Settings) -> RetrievalProvider:
    """Instantiate the configured provider. No network I/O happens here."""
    if settings.retrieval_mode == "disabled":
        return DisabledProvider()
    if settings.retrieval_mode == "mock":
        return MockRetrievalProvider()
    if settings.retrieval_mode == "http":
        return HttpRetrievalProvider(
            base_url=settings.retrieval_base_url,
            default_timeout_s=settings.retrieval_timeout_s,
        )
    raise ValueError(f"unsupported RETRIEVAL_MODE: {settings.retrieval_mode!r}")


def build_retrieval_provider_from_settings(settings: Settings) -> RetrievalProvider:
    """Alias for clarity at call sites (Phase 8 wiring)."""
    return build_retrieval_provider(settings)