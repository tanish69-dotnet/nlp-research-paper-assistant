"""``GET /api/v1/health`` (API_SPEC §3.1).

Distinguishes *application* health from *model* availability: the service stays
``ok`` when Ollama is down. Shallow checks perform no network I/O; ``deep=true``
pings providers and degrades the status when none is reachable.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import get_registry, get_request_id, get_settings
from app.config import Settings
from app.models.routing import ModelRegistry
from app.schemas.health import HealthResponse, HealthStatus, ProviderHealth

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health",
    description=(
        "Liveness plus light configuration checks. `?deep=true` additionally "
        "pings the configured model provider (slower; used by container "
        "health checks). Model unavailability degrades status — it does not "
        "take the service down."
    ),
)
async def health(
    request: Request,
    deep: bool = Query(
        default=False,
        description="Ping model providers (network I/O) before responding.",
    ),
    settings: Settings = Depends(get_settings),
    registry: ModelRegistry = Depends(get_registry),
) -> HealthResponse:
    checks = {
        "evidence_root": "ok" if settings.evidence_root_path.exists() else "missing",
        "prompts": "ok" if settings.prompts_path.exists() else "missing",
    }

    providers: list[ProviderHealth]
    if deep:
        providers = [await registry.provider_health()]
    else:
        providers = [
            ProviderHealth(
                name=registry.provider.name,
                reachable=None,
                models=None,
                detail="not checked (use ?deep=true)",
            )
        ]

    status: HealthStatus = "ok"
    if checks["prompts"] != "ok":
        status = "degraded"
    if deep and providers and all(p.reachable is False for p in providers):
        status = "degraded"

    uptime = max(0.0, time.time() - request.app.state.started_at)
    return HealthResponse(
        status=status,
        version=settings.app_version,
        request_id=get_request_id(request),
        providers=providers,
        checks=checks,
        uptime_s=round(uptime, 3),
    )
