"""Model provider abstraction (ARCHITECTURE §5).

Agents depend only on :class:`ModelProvider`; concrete backends (Ollama,
future OpenAI-compatible/vLLM, tests) plug in behind this interface. Nothing in
the agent layer may import a provider SDK directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.claims import TokenUsage
from app.schemas.health import ProviderHealth

ImageFormat = Literal["image/png", "image/jpeg", "image/webp", "image/gif"]


class ImagePayload(BaseModel):
    """A VLM image already validated/encoded by the caller.

    Base64 payloads are redacted from logs (SECURITY.md §7).
    """

    model_config = ConfigDict(extra="forbid")

    b64: str = Field(min_length=1)
    mime: ImageFormat = "image/png"


class ChatMessage(BaseModel):
    """One message in a provider request.

    The three roles mirror the three-zone prompt architecture (SECURITY.md §2):
    ``system`` is trusted template text, ``user`` carries the question, and
    evidence is supplied as user content delimited by the prompt builder.
    """

    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str
    images: list[ImagePayload] = Field(default_factory=list)


class ChatRequest(BaseModel):
    """Provider-agnostic completion request."""

    model_config = ConfigDict(extra="forbid")

    model: str
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    timeout_s: float | None = Field(default=None, gt=0)
    response_format: Literal["json", "text"] = "text"
    metadata: dict[str, str] = Field(default_factory=dict)  # request_id, agent, ...


class ChatResponse(BaseModel):
    """Provider-agnostic completion response.

    Raw provider payloads are intentionally not retained (SECURITY.md §7).
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    model: str
    provider: str
    finish_reason: str | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    latency_ms: int = Field(default=0, ge=0)


class ModelProvider(ABC):
    """Single interface every model backend implements.

    Contract:
    - ``chat`` raises typed :class:`ReasoningError` subclasses
      (``ModelUnavailableError`` / ``ModelTimeoutError`` /
      ``MalformedModelOutputError``) — never raw transport exceptions.
    - ``health`` never raises; it reports reachability instead.
    - ``aclose`` releases any owned network resources.
    """

    name: ClassVar[str]

    @abstractmethod
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Run one completion request."""

    @abstractmethod
    async def health(self) -> ProviderHealth:
        """Report reachability and (if known) installed models. Must not raise."""

    async def aclose(self) -> None:
        """Release owned resources (no-op by default)."""
