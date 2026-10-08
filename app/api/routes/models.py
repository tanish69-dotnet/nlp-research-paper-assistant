"""``GET /api/v1/models`` (API_SPEC §3.2).

Exposes role → model mapping and availability. Never exposes provider keys and
never crashes when the provider is unreachable — availability simply reports
``available: false`` with a reason.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_registry, get_request_id
from app.models.routing import ModelRegistry
from app.schemas.health import ModelsResponse

router = APIRouter(tags=["models"])


@router.get(
    "/models",
    response_model=ModelsResponse,
    summary="Configured models per role",
    description=(
        "Maps each logical role (analyzer, text/table/vision reasoner, judge, "
        "generator) to its configured model and reports whether that model is "
        "reachable/installed. Safe to call with no model server running."
    ),
)
async def models(
    request: Request,
    registry: ModelRegistry = Depends(get_registry),
) -> ModelsResponse:
    return ModelsResponse(
        request_id=get_request_id(request),
        provider=registry.provider.name,
        roles=await registry.roles(),
    )
