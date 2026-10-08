"""Agent base: protocol, run context, and validated-JSON completion.

All agents are async, stateless, and depend only on the ``ModelProvider``
interface. Model output is parsed, schema-validated, and then semantically
validated — malformed output becomes a controlled ``AgentRun`` with status
``error`` or ``degraded``, never an uncaught exception (ARCHITECTURE §4.7).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

import structlog

from app.core.errors import (
    MalformedModelOutputError,
    ModelTimeoutError,
    ModelUnavailableError,
    ReasoningError,
)
from app.models.base import ChatMessage, ChatRequest, ChatResponse, ModelProvider
from app.models.routing import ModelRole
from app.schemas.claims import AgentError, AgentRun
from app.schemas.common import AgentStatus
from app.schemas.evidence import EvidenceItem

logger = structlog.get_logger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class AgentContext:
    """Everything an agent needs for one invocation (no hidden globals)."""

    request_id: str
    query: str
    evidence: tuple[EvidenceItem, ...] = ()
    model: str = ""
    provider_name: str = ""
    timeout_s: float = 60.0
    temperature: float = 0.0
    max_tokens: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class Agent(Protocol):
    """Structural contract every agent implements."""

    name: str

    async def run(self, ctx: AgentContext) -> AgentRun:
        """Run the agent once and return a fully populated :class:`AgentRun`."""


def new_agent_run(
    agent_name: str,
    ctx: AgentContext,
    *,
    status: AgentStatus,
    started_s: float,
    findings: list[str] | None = None,
    evidence_ids_used: list[str] | None = None,
    prompt_version: str = "unversioned",
    usage_prompt_tokens: int | None = None,
    usage_completion_tokens: int | None = None,
    error: AgentError | None = None,
) -> AgentRun:
    """Build an :class:`AgentRun` with latency computed from ``started_s``."""
    return AgentRun(
        agent=agent_name,
        model=ctx.model,
        provider=ctx.provider_name,
        prompt_version=prompt_version,
        status=status,
        latency_ms=max(0, int((time.perf_counter() - started_s) * 1000)),
        evidence_ids_used=list(evidence_ids_used or []),
        findings=list(findings or []),
        usage={
            "prompt_tokens": usage_prompt_tokens,
            "completion_tokens": usage_completion_tokens,
        },
        error=error,
    )


def agent_error_from(exc: Exception, attempts: int = 1) -> AgentError:
    """Translate any failure into a structured :class:`AgentError`."""
    if isinstance(exc, ReasoningError):
        return AgentError(
            code=exc.code, message=exc.detail, retriable=exc.retryable, attempts=attempts
        )
    return AgentError(
        code="INTERNAL_ERROR",
        message=f"{type(exc).__name__}: {exc}",
        retriable=False,
        attempts=attempts,
    )


async def complete_json(
    provider: ModelProvider,
    *,
    system: str,
    user: str,
    ctx: AgentContext,
    model: str | None = None,
    repair_attempts: int = 1,
) -> tuple[dict[str, Any], ChatResponse]:
    """Ask the provider for JSON and return the parsed object.

    One repair attempt ("reply with valid JSON only") is made when the first
    response does not parse; persistent garbage raises
    :class:`MalformedModelOutputError` (ARCHITECTURE §4.7).
    """
    model_name = model or ctx.model
    timeout = ctx.timeout_s

    def build(messages_extra: str = "") -> ChatRequest:
        user_content = user + messages_extra
        return ChatRequest(
            model=model_name,
            messages=[
                ChatMessage(role="system", content=system),
                ChatMessage(role="user", content=user_content),
            ],
            temperature=ctx.temperature,
            max_tokens=ctx.max_tokens,
            timeout_s=timeout,
            response_format="json",
            metadata={"request_id": ctx.request_id},
        )

    response = await provider.chat(build())
    try:
        return json.loads(response.text), response
    except (json.JSONDecodeError, TypeError) as first_exc:
        if repair_attempts <= 0:
            raise MalformedModelOutputError(
                "model did not return valid JSON"
            ) from first_exc
        logger.info("agent_json_repair", component="agents", attempt=1)
        repaired = await provider.chat(
            build("\n\nYour previous reply was not valid JSON. Reply with a single valid JSON object only.")
        )
        try:
            return json.loads(repaired.text), repaired
        except (json.JSONDecodeError, TypeError) as second_exc:
            raise MalformedModelOutputError(
                "model did not return valid JSON after repair"
            ) from second_exc
