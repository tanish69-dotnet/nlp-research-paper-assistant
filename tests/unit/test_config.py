"""Configuration tests (Phase 1 §18)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings
from tests.conftest import clear_setting_env


def test_defaults_load(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_setting_env(monkeypatch)
    settings = Settings(_env_file=None)

    assert settings.api_port == 8001
    assert settings.model_provider == "ollama"
    assert settings.ollama_base_url == "http://127.0.0.1:11434"
    assert settings.cors_origins == ["http://localhost:5173"]
    assert settings.request_timeout_ms == 120_000
    assert settings.log_format == "json"
    assert settings.enable_eval_api is False


def test_environment_overrides_are_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_setting_env(monkeypatch)
    monkeypatch.setenv("REASONING_ENV", "test")
    monkeypatch.setenv("API_PORT", "9001")
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    monkeypatch.setenv("CORS_ORIGINS", '["http://a.test", "http://b.test"]')

    settings = Settings(_env_file=None)

    assert settings.reasoning_env == "test"
    assert settings.api_port == 9001
    assert settings.model_provider == "mock"
    assert settings.cors_origins == ["http://a.test", "http://b.test"]


def test_invalid_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_setting_env(monkeypatch)
    monkeypatch.setenv("MODEL_PROVIDER", "definitely-not-a-provider")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_out_of_range_values_are_rejected(
    monkeypatch: pytest.MonkeyPatch, make_settings: object
) -> None:
    with pytest.raises(ValidationError):
        make_settings(api_port=0)  # type: ignore[operator]
    with pytest.raises(ValidationError):
        make_settings(model_temperature=3.5)  # type: ignore[operator]
    with pytest.raises(ValidationError):
        make_settings(confidence_threshold=1.5)  # type: ignore[operator]


def test_malformed_base_url_is_rejected(make_settings: object) -> None:
    with pytest.raises(ValidationError):
        make_settings(ollama_base_url="127.0.0.1:11434")  # type: ignore[operator]


def test_unrelated_environment_variables_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_setting_env(monkeypatch)
    monkeypatch.setenv("SOME_UNRELATED_TOOL_VAR", "hello")

    settings = Settings(_env_file=None)

    assert settings.api_port == 8001


def test_evidence_root_defaults_under_project(make_settings: object) -> None:
    settings = make_settings()  # type: ignore[operator]

    root = settings.evidence_root_path
    assert root.is_absolute()
    assert root.name == "evidence"


def test_evidence_root_absolute_path_is_honoured(
    make_settings: object, tmp_path: object
) -> None:
    settings = make_settings(evidence_root=str(tmp_path))  # type: ignore[operator]

    assert settings.evidence_root_path == tmp_path.resolve()  # type: ignore[arg-type]


def test_no_secrets_have_hardcoded_defaults() -> None:
    """SECURITY.md §8: no credentials in source, only env-provided values."""
    settings = Settings(_env_file=None, model_provider="ollama")  # type: ignore[call-arg]

    assert settings.openai_compat_api_key is None
    assert settings.openai_compat_base_url is None
