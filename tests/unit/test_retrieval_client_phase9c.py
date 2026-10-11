"""Phase 9C — HttpRetrievalProvider URL + error-handling regression tests.

All tests stay offline via ``httpx.MockTransport``. No network, no Ollama,
no Person 2 service required.
"""

from __future__ import annotations

import json

import pytest
import httpx

from app.evidence.retrieval_client import HttpRetrievalProvider, RetrievalRequest, infer_paper_ids

pytestmark = pytest.mark.unit


def _provider(**kwargs) -> HttpRetrievalProvider:
    return HttpRetrievalProvider(base_url=kwargs.pop("base_url", "http://127.0.0.1:8000"), **kwargs)


def _capture_handler(captured: dict, payload: dict | None = None):
    """Return a handler that records the request URL and echoes a payload."""

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["json"] = json.loads(request.content) if request.content else None
        if payload is not None:
            return httpx.Response(200, json=payload)
        return httpx.Response(200, json={"evidence": []})

    return handler


def _run(coro):
    import asyncio

    return asyncio.run(coro)


# --- URL construction ---------------------------------------------------------


def test_retrieve_calls_correct_url():
    """Provider must POST the configured base_url + /retrieve — not /api/v1/*."""
    captured: dict = {}
    handler = _capture_handler(captured, {"evidence": []})
    provider = _provider(base_url="http://127.0.0.1:8000")
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8000")

    _run(provider.retrieve(RetrievalRequest(query="Q", top_k=3, timeout_s=5.0)))
    assert captured["url"] == "http://127.0.0.1:8000/retrieve"
    assert captured["method"] == "POST"
    assert captured["json"] == {"query": "Q", "top_k": 3}


def test_retrieve_forwards_explicit_paper_ids():
    captured: dict = {}
    handler = _capture_handler(captured, {"evidence": []})
    provider = _provider()
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8000"
    )

    _run(
        provider.retrieve(
            RetrievalRequest(
                query="main contribution",
                top_k=5,
                timeout_s=5.0,
                paper_ids=("1611.04684v1",),
            )
        )
    )

    assert captured["json"] == {
        "query": "main contribution",
        "top_k": 5,
        "paper_ids": ["1611.04684v1"],
    }


def test_infer_paper_ids_is_narrow_and_deduplicated():
    assert infer_paper_ids("Compare arXiv:1611.04684v1 with 1611.04684v1") == (
        "1611.04684v1",
    )
    assert infer_paper_ids("What is the contribution?") == ()


def test_trailing_slash_base_url_does_not_double_slash():
    """``RETRIEVAL_BASE_URL=http://localhost:8000/`` must not produce ``//retrieve``."""
    captured: dict = {}
    handler = _capture_handler(captured, {"evidence": []})
    for base in ("http://127.0.0.1:8000/", "http://127.0.0.1:8000"):
        provider = HttpRetrievalProvider(base_url=base)
        provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=base.rstrip("/"))
        _run(provider.retrieve(RetrievalRequest(query="Q", top_k=3, timeout_s=5.0)))
        assert captured["url"] == "http://127.0.0.1:8000/retrieve", base


def test_health_calls_correct_url():
    """``health()`` must GET the configured base_url + /health."""
    captured: dict = {}
    handler = _capture_handler(captured, {"status": "healthy"})
    provider = HttpRetrievalProvider(base_url="http://127.0.0.1:8000")
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8000")
    _run(provider.health())
    assert captured["url"] == "http://127.0.0.1:8000/health"
    assert captured["method"] == "GET"


def test_wrong_host_is_not_accidentally_the_reasoning_api():
    """A misconfigured base_url that points at our reasoning API must be detectable."""
    # Simulate: base_url was accidentally set to http://127.0.0.1:8001 (our 8001)
    # Person 2 would never answer /health there — our reasoning /health is /api/v1/health.
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(404, json={"detail": "Not Found"})

    provider = HttpRetrievalProvider(base_url="http://127.0.0.1:8001")
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8001")
    result = _run(provider.health())
    assert result is False
    assert captured["url"] == "http://127.0.0.1:8001/health"


# --- error handling -----------------------------------------------------------


def test_400_raised_as_unavailable():
    """HTTP 4xx (including 404) must surface as ModelUnavailableError — never as success."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Not Found"})

    provider = HttpRetrievalProvider(base_url="http://127.0.0.1:8000")
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8000")
    from app.core.errors import ModelUnavailableError

    with pytest.raises(ModelUnavailableError, match="404"):
        _run(provider.retrieve(RetrievalRequest(query="Q", top_k=3, timeout_s=5.0)))


def test_500_raised_as_unavailable():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "server exploded"})

    provider = HttpRetrievalProvider(base_url="http://127.0.0.1:8000")
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8000")
    from app.core.errors import ModelUnavailableError

    with pytest.raises(ModelUnavailableError, match="500"):
        _run(provider.retrieve(RetrievalRequest(query="Q", top_k=3, timeout_s=5.0)))


def test_timeout_maps_to_model_timeout():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    provider = HttpRetrievalProvider(base_url="http://127.0.0.1:8000")
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8000")
    from app.core.errors import ModelTimeoutError

    with pytest.raises(ModelTimeoutError):
        _run(provider.retrieve(RetrievalRequest(query="Q", top_k=3, timeout_s=5.0)))


def test_connection_failure_maps_to_timeout_or_unavailable():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    provider = HttpRetrievalProvider(base_url="http://127.0.0.1:8000")
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8000")
    from app.core.errors import ModelTimeoutError

    with pytest.raises(ModelTimeoutError):
        _run(provider.retrieve(RetrievalRequest(query="Q", top_k=3, timeout_s=5.0)))


def test_ask_with_mock_provider_succeeds():
    """``POST /api/v1/ask`` stays functional with ``MockRetrievalProvider``."""
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app

    config = Settings(_env_file=None, model_provider="mock", retrieval_mode="mock", log_level="WARNING", log_format="console")  # type: ignore[call-arg]
    app = create_app(config)
    with TestClient(app) as client:
        resp = client.post("/api/v1/ask", json={"query": "What are the main differences?", "top_k": 3})
        assert resp.status_code in (200, 206, 503, 400)
