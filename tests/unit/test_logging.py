"""Logging scrubber tests (SECURITY.md §7 — never log secrets or payloads)."""

from __future__ import annotations

from app.observability.logging import MAX_LOG_VALUE_CHARS, scrub


def test_sensitive_keys_are_redacted() -> None:
    event = {
        "api_key": "sk-super-secret",
        "OPENAI_COMPAT_API_KEY": "sk-another",
        "password": "hunter2",
        "auth_token": "abc",
        "b64": "iVBORw0KGgo=",
        "image_b64": "AAAABBBB",
        "path": "/safe/value",
    }

    result = scrub(None, "event", dict(event))

    assert result["api_key"] == "[REDACTED]"
    assert result["OPENAI_COMPAT_API_KEY"] == "[REDACTED]"
    assert result["password"] == "[REDACTED]"
    assert result["auth_token"] == "[REDACTED]"
    assert result["b64"] == "[REDACTED]"
    assert result["image_b64"] == "[REDACTED]"
    assert result["path"] == "/safe/value"


def test_nested_sensitive_keys_are_redacted() -> None:
    event = {"options": {"api_key": "sk-1", "temperature": 0.0}}

    result = scrub(None, "event", dict(event))

    assert result["options"]["api_key"] == "[REDACTED]"
    assert result["options"]["temperature"] == 0.0


def test_long_values_are_truncated() -> None:
    long_text = "paper body " * 5_000

    result = scrub(None, "event", {"content": long_text})

    assert len(result["content"]) < len(long_text)
    assert "chars]" in result["content"]
    assert result["content"].startswith(long_text[:MAX_LOG_VALUE_CHARS])


def test_short_values_pass_through_unchanged() -> None:
    event = {"component": "http", "status": 200, "duration_ms": 12.5}

    assert scrub(None, "event", dict(event)) == event