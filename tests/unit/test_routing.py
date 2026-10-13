"""Role routing and registry tests (ARCHITECTURE §5)."""

from __future__ import annotations

import pytest

from app.core.errors import ReasoningError
from app.models.mock import MockModelProvider
from app.models.ollama import OllamaModelProvider
from app.models.routing import (
    ROLE_MODEL_FIELDS,
    ModelRole,
    build_provider,
    build_registry,
    resolve_model,
    role_supports_vision,
)
from tests.conftest import run


def test_every_role_has_a_model_field() -> None:
    assert set(ROLE_MODEL_FIELDS) == set(ModelRole)
    assert ROLE_MODEL_FIELDS[ModelRole.JUDGE] == "judge_model"
    assert ROLE_MODEL_FIELDS[ModelRole.VISION_REASONER] == "vision_model"


def test_resolve_model_reads_settings(make_settings: object) -> None:
    settings = make_settings(text_model="text-x", judge_model="judge-y", analyzer_model="")  # type: ignore[operator]

    assert resolve_model(ModelRole.TEXT_REASONER, settings) == "text-x"
    assert resolve_model(ModelRole.JUDGE, settings) == "judge-y"
    assert resolve_model(ModelRole.ANALYZER, settings) == ""  # unset -> empty


def test_only_vision_role_requires_vision_capability() -> None:
    assert role_supports_vision(ModelRole.VISION_REASONER) is True
    assert role_supports_vision(ModelRole.TABLE_REASONER) is False
    assert role_supports_vision(ModelRole.TEXT_REASONER) is False
    assert role_supports_vision(ModelRole.JUDGE) is False


def test_build_provider_selects_backend(make_settings: object) -> None:
    assert isinstance(build_provider(make_settings(model_provider="mock")), MockModelProvider)  # type: ignore[arg-type]
    ollama = build_provider(make_settings(model_provider="ollama"))  # type: ignore[arg-type]
    assert isinstance(ollama, OllamaModelProvider)


def test_openai_compat_requires_base_url(make_settings: object) -> None:
    with pytest.raises(ValueError, match="OPENAI_COMPAT_BASE_URL"):
        build_provider(make_settings(model_provider="openai_compat"))  # type: ignore[arg-type]


def test_openai_compat_builds_with_base_url(make_settings: object) -> None:
    from app.models.openai_compat import OpenAICompatProvider

    provider = build_provider(
        make_settings(  # type: ignore[arg-type]
            model_provider="openai_compat",
            openai_compat_base_url="https://gateway.example/v1",
        )
    )

    assert isinstance(provider, OpenAICompatProvider)


# --- registry availability ---------------------------------------------------


def test_role_available_when_provider_reachable_and_inventory_unknown(
    make_settings: object,
) -> None:
    settings = make_settings(model_provider="mock", text_model="some-model")  # type: ignore[arg-type]
    registry = build_registry(settings)

    # MockModelProvider has models=None ("cannot enumerate") by default.
    roles = run(registry.roles())
    by_role = {role.role: role for role in roles}

    assert by_role["text_reasoner"].available is True
    assert by_role["text_reasoner"].detail is None
    # Explicitly unconfigured roles must report a reason, not crash
    unconfigured = make_settings(model_provider="mock", judge_model="")  # type: ignore[operator]
    judged = {role.role: role for role in run(build_registry(unconfigured).roles())}
    assert judged["judge"].available is False
    assert judged["judge"].detail == "model not configured"


def test_role_unavailable_when_model_not_installed(make_settings: object) -> None:
    settings = make_settings(model_provider="mock", text_model="missing-model")  # type: ignore[arg-type]
    from app.models.mock import MockModelProvider

    registry = type(build_registry(settings))(
        MockModelProvider(models=["other-model"]), settings
    )
    by_role = {role.role: role for role in run(registry.roles())}

    assert by_role["text_reasoner"].available is False
    assert by_role["text_reasoner"].detail == "model not installed on provider"


def test_roles_unavailable_when_provider_unreachable(make_settings: object) -> None:
    settings = make_settings(model_provider="mock", text_model="m")  # type: ignore[arg-type]
    from app.models.mock import MockModelProvider
    from app.models.routing import ModelRegistry

    registry = ModelRegistry(MockModelProvider(reachable=False), settings)
    roles = run(registry.roles())

    assert roles
    assert all(role.available is False for role in roles)
    assert all(role.detail for role in roles)


def test_registry_health_swallows_provider_errors(make_settings: object) -> None:
    """Health must be total: a raising provider degrades, never 500s."""
    from app.models.base import ModelProvider
    from app.models.routing import ModelRegistry
    from app.schemas.health import ProviderHealth

    class ExplodingProvider(ModelProvider):
        name = "exploding"

        async def chat(self, request):  # pragma: no cover
            raise AssertionError("not used")

        async def health(self) -> ProviderHealth:
            raise RuntimeError("boom")

    registry = ModelRegistry(ExplodingProvider(), make_settings())  # type: ignore[arg-type]
    health = run(registry.provider_health())

    assert health.reachable is False
    assert "RuntimeError" in (health.detail or "")


def test_registry_aclose_propagates(make_settings: object) -> None:
    registry = build_registry(make_settings(model_provider="mock"))  # type: ignore[arg-type]

    run(registry.aclose())  # must not raise