"""Model provider layer: abstraction, concrete backends, role routing."""

from app.models.base import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ImagePayload,
    ModelProvider,
)
from app.models.mock import MockModelProvider
from app.models.ollama import OllamaModelProvider
from app.models.routing import (
    ROLE_MODEL_FIELDS,
    ModelRegistry,
    ModelRole,
    build_provider,
    build_registry,
    resolve_model,
    role_supports_vision,
)

__all__ = [
    "ROLE_MODEL_FIELDS",
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "ImagePayload",
    "MockModelProvider",
    "ModelProvider",
    "ModelRegistry",
    "ModelRole",
    "OllamaModelProvider",
    "build_provider",
    "build_registry",
    "resolve_model",
    "role_supports_vision",
]
