"""Health / capability contracts (API_SPEC §3.1, §3.2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

HealthStatus = Literal["ok", "degraded", "error"]


class ProviderHealth(BaseModel):
    """Provider reachability.

    ``reachable=None`` means "not checked" (shallow ``/health`` performs no
    network I/O); ``models=None`` means the provider cannot enumerate its
    installed models.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    reachable: bool | None = None
    models: list[str] | None = None
    detail: str | None = None


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: HealthStatus
    version: str
    request_id: str
    providers: list[ProviderHealth]
    checks: dict[str, str]
    uptime_s: float = Field(ge=0.0)


class RoleInfo(BaseModel):
    """One configured model role (``/api/v1/models``)."""

    model_config = ConfigDict(extra="forbid")

    role: str
    model: str
    vision: bool
    available: bool
    detail: str | None = None


class ModelsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    provider: str
    roles: list[RoleInfo]
