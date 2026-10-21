"""Regression tests: retrieval-mode configuration loading.

Verifies the exact failure scenario from the HTTP 503 / MODEL_UNAVAILABLE
bug:  the /ask endpoint must honour RETRIEVAL_MODE from the environment (and
.env), and never silently default to "disabled" when the operator intended
"http" mode.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.evidence.retrieval_client import (
    DisabledProvider,
    HttpRetrievalProvider,
    MockRetrievalProvider,
    build_retrieval_provider,
)
from tests.conftest import clear_setting_env

pytestmark = pytest.mark.unit


# -- Settings picks up RETRIEVAL_MODE from the environment --------------------


def test_retrieval_mode_env_override_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """RETRIEVAL_MODE=http in env must override the 'disabled' default."""
    clear_setting_env(monkeypatch)
    monkeypatch.setenv("RETRIEVAL_MODE", "http")
    monkeypatch.setenv("RETRIEVAL_BASE_URL", "http://127.0.0.1:8000")

    settings = Settings(_env_file=None)

    assert settings.retrieval_mode == "http"
    assert settings.retrieval_base_url == "http://127.0.0.1:8000"


def test_retrieval_mode_env_override_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """RETRIEVAL_MODE=mock in env must override the 'disabled' default."""
    clear_setting_env(monkeypatch)
    monkeypatch.setenv("RETRIEVAL_MODE", "mock")

    settings = Settings(_env_file=None)

    assert settings.retrieval_mode == "mock"


def test_retrieval_mode_default_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without env var the default is 'disabled' (by design)."""
    clear_setting_env(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.retrieval_mode == "disabled"


def test_retrieval_mode_invalid_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unrecognised RETRIEVAL_MODE must fail loudly at startup."""
    clear_setting_env(monkeypatch)
    monkeypatch.setenv("RETRIEVAL_MODE", "banana")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


# -- build_retrieval_provider wiring ------------------------------------------


def test_build_provider_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """http mode builds an HttpRetrievalProvider with the configured URL."""
    clear_setting_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        retrieval_mode="http",
        retrieval_base_url="http://127.0.0.1:8000",
        model_provider="mock",
    )

    provider = build_retrieval_provider(settings)

    assert isinstance(provider, HttpRetrievalProvider)
    assert provider._base_url == "http://127.0.0.1:8000"


def test_build_provider_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_setting_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        retrieval_mode="mock",
        model_provider="mock",
    )

    provider = build_retrieval_provider(settings)

    assert isinstance(provider, MockRetrievalProvider)


def test_build_provider_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_setting_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        retrieval_mode="disabled",
        model_provider="mock",
    )

    provider = build_retrieval_provider(settings)

    assert isinstance(provider, DisabledProvider)


# -- /ask endpoint rejects disabled mode with 503 ----------------------------


def test_ask_returns_503_when_disabled(make_client) -> None:
    """The exact 503 scenario: /ask with retrieval_mode=disabled must return
    503 MODEL_UNAVAILABLE, not a silent failure or a fake answer."""
    client = make_client(retrieval_mode="disabled")

    response = client.post("/api/v1/ask", json={"query": "test question"})

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "MODEL_UNAVAILABLE"
    assert "retrieval is disabled" in body["detail"].lower()


def test_ask_accepts_http_mode(make_client) -> None:
    """When retrieval_mode=http the /ask endpoint must NOT reject the request
    with a disabled-mode error.  (It will fail with a connection error to
    the mock URL, which is fine — we only check it gets past the guard.)"""
    client = make_client(
        retrieval_mode="http",
        retrieval_base_url="http://127.0.0.1:59999",  # unreachable on purpose
    )

    response = client.post("/api/v1/ask", json={"query": "test question"})

    # Should NOT be the disabled-mode 503
    assert response.status_code != 503 or "retrieval is disabled" not in response.text.lower()


# -- .env file loading -------------------------------------------------------


def test_env_file_retrieval_mode(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A .env file with RETRIEVAL_MODE=http must be picked up by Settings."""
    clear_setting_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text("RETRIEVAL_MODE=http\nRETRIEVAL_BASE_URL=http://127.0.0.1:8000\n")

    settings = Settings(_env_file=str(env_file))

    assert settings.retrieval_mode == "http"
