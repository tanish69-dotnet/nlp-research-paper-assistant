"""Shared test fixtures.

Offline-first: no network, no Ollama, no Person 2/4 (DEVELOPMENT_PLAN Phase 1).
Async calls are executed with ``asyncio.run`` via :func:`run` so the suite has
no extra test-runner dependencies.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Iterator
from pathlib import Path
from typing import Any, TypeVar

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

T = TypeVar("T")

FIXTURES = Path(__file__).parent / "fixtures"
MOCK_EVIDENCE_PATH = FIXTURES / "mock_evidence.json"

#: Environment variable names that would override test settings.
_SETTINGS_ENV_KEYS = {name.upper() for name in Settings.model_fields}


def run(awaitable: Awaitable[T]) -> T:
    """Await a coroutine from a synchronous test (no pytest-asyncio needed)."""
    return asyncio.run(awaitable)


def load_mock_evidence() -> dict[str, Any]:
    """Load the Phase 0 evidence fixture as a plain dict."""
    with MOCK_EVIDENCE_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def clear_setting_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove any shell/env overrides so tests see deterministic settings."""
    for name in list(os.environ):
        if name.upper() in _SETTINGS_ENV_KEYS:
            monkeypatch.delenv(name, raising=False)


@pytest.fixture
def make_settings(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Factory for isolated :class:`Settings` (``.env`` and env vars ignored)."""

    def _make(**overrides: Any) -> Settings:
        clear_setting_env(monkeypatch)
        base: dict[str, Any] = {
            "model_provider": "mock",
            "log_format": "console",
            "log_level": "WARNING",
        }
        base.update(overrides)
        return Settings(_env_file=None, **base)

    return _make


@pytest.fixture
def make_client(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Factory for a lifespan-managed :class:`TestClient` with clean settings."""
    entered: list[Any] = []

    def _make(**overrides: Any) -> TestClient:
        clear_setting_env(monkeypatch)
        base: dict[str, Any] = {
            "model_provider": "mock",
            "log_format": "console",
            "log_level": "WARNING",
        }
        base.update(overrides)
        settings = Settings(_env_file=None, **base)
        manager = TestClient(create_app(settings))
        client = manager.__enter__()  # run lifespan
        entered.append(manager)
        return client

    yield _make

    for manager in entered:
        manager.__exit__(None, None, None)


@pytest.fixture
def client(make_client: Any) -> Iterator[TestClient]:
    """Default client: mock provider, console logs, no env interference."""
    return make_client()
