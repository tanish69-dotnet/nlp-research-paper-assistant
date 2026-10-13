"""Role-based model routing (ARCHITECTURE §5).

Maps logical roles (``judge``, ``vision_reasoner``, ...) to configured model
names and to a concrete provider. This is the only place that knows which
environment variable backs which role — agent code asks for a *role*.
"""

from __future__ import annotations

import logging
from enum import StrEnum

from app.config import Settings
from app.models.base import ModelProvider
from app.models.mock import MockModelProvider
from app.models.ollama import OllamaModelProvider
from app.models.openai_compat import OpenAICompatProvider
from app.schemas.health import ProviderHealth, RoleInfo

logger = logging.getLogger(__name__)


class ModelRole(StrEnum):
    """Logical reasons to call a model."""

    ANALYZER = "analyzer"
    TEXT_REASONER = "text_reasoner"
    TABLE_REASONER = "table_reasoner"
    VISION_REASONER = "vision_reasoner"
    JUDGE = "judge"
    GENERATOR = "generator"


#: role -> ``Settings`` attribute holding its model name.
ROLE_MODEL_FIELDS: dict[ModelRole, str] = {
    ModelRole.ANALYZER: "analyzer_model",
    ModelRole.TEXT_REASONER: "text_model",
    ModelRole.TABLE_REASONER: "table_model",
    ModelRole.VISION_REASONER: "vision_model",
    ModelRole.JUDGE: "judge_model",
    ModelRole.GENERATOR: "generator_model",
}


def resolve_model(role: ModelRole, settings: Settings) -> str:
    """Configured model name for ``role`` (``""`` when not configured)."""
    field = ROLE_MODEL_FIELDS[role]
    return str(getattr(settings, field)).strip()


def role_supports_vision(role: ModelRole) -> bool:
    """Whether a role consumes images.

    Only the vision reasoner is guaranteed a VLM; other roles degrade to
    text-only for image items (ARCHITECTURE §5 capability rule).
    """
    return role is ModelRole.VISION_REASONER


def build_provider(settings: Settings) -> ModelProvider:
    """Instantiate the configured provider. No network I/O happens here."""
    if settings.model_provider == "mock":
        return MockModelProvider()
    if settings.model_provider == "ollama":
        return OllamaModelProvider(
            base_url=settings.ollama_base_url,
            default_timeout_s=settings.provider_timeout_ms / 1000.0,
        )
    if settings.model_provider == "openai_compat":
        if not settings.openai_compat_base_url:
            raise ValueError(
                "OPENAI_COMPAT_BASE_URL must be set when MODEL_PROVIDER=openai_compat"
            )
        api_key = settings.openai_compat_api_key.get_secret_value() if settings.openai_compat_api_key else None
        return OpenAICompatProvider(
            base_url=settings.openai_compat_base_url,
            api_key=api_key,
            default_timeout_s=settings.provider_timeout_ms / 1000.0,
        )
    raise ValueError(f"unsupported MODEL_PROVIDER: {settings.model_provider!r}")


class ModelRegistry:
    """Resolves roles to models and reports availability for one provider."""

    def __init__(self, provider: ModelProvider, settings: Settings) -> None:
        self._provider = provider
        self._settings = settings

    @property
    def provider(self) -> ModelProvider:
        return self._provider

    @property
    def settings(self) -> Settings:
        return self._settings

    def model_for(self, role: ModelRole) -> str:
        return resolve_model(role, self._settings)

    async def provider_health(self) -> ProviderHealth:
        """Provider health, with a safety net so ``/health`` cannot crash."""
        try:
            return await self._provider.health()
        except Exception as exc:  # noqa: BLE001 - health endpoint must be total
            logger.warning(
                "provider health check raised",
                extra={"provider": self._provider.name, "error": type(exc).__name__},
            )
            return ProviderHealth(
                name=self._provider.name,
                reachable=False,
                models=None,
                detail=f"health check failed: {type(exc).__name__}",
            )

    async def roles(self) -> list[RoleInfo]:
        """One :class:`RoleInfo` per configured role, with availability detail."""
        health = await self.provider_health()
        return [
            _role_info(role, self.model_for(role), health) for role in ModelRole
        ]

    async def aclose(self) -> None:
        await self._provider.aclose()


def _role_info(role: ModelRole, model: str, health: ProviderHealth) -> RoleInfo:
    vision = role_supports_vision(role)
    if health.reachable is not True:
        return RoleInfo(
            role=role.value,
            model=model,
            vision=vision,
            available=False,
            detail=health.detail or "provider unreachable",
        )
    if not model:
        return RoleInfo(
            role=role.value,
            model="",
            vision=vision,
            available=False,
            detail="model not configured",
        )
    if health.models is not None and model not in health.models:
        return RoleInfo(
            role=role.value,
            model=model,
            vision=vision,
            available=False,
            detail="model not installed on provider",
        )
    return RoleInfo(role=role.value, model=model, vision=vision, available=True)


def build_registry(settings: Settings) -> ModelRegistry:
    """Build the registry used by the API layer (no network I/O at build time)."""
    return ModelRegistry(build_provider(settings), settings)
