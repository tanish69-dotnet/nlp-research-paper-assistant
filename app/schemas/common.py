"""Shared contract primitives used across several schema modules.

Kept in one place so agents, providers and routes cannot drift apart on a
field name (API_SPEC §2).
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, BaseModel

EvidenceType = Literal["text", "table", "figure", "equation", "metadata"]
Modality = Literal["text", "table", "figure", "equation", "metadata"]
AgentStatus = Literal[
    "ok", "partial", "no_evidence", "timeout", "error", "skipped", "degraded"
]


class TokenUsage(BaseModel):
    """Token accounting reported by a provider (unknown fields stay ``None``)."""

    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
