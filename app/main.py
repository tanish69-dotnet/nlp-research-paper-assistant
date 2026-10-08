"""FastAPI application factory.

Contains wiring only — no business logic (ARCHITECTURE §3.1):

    create_app()  ->  logging + settings + registry + middleware + routes
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import structlog
from fastapi import FastAPI

from app.api.errors import install_exception_handlers
from app.api.middleware import BodySizeLimitMiddleware, RequestContextMiddleware
from app.api.routes import analyze, health, models
from app.config import Settings
from app.models.routing import build_registry
from app.observability.logging import setup_logging

logger = structlog.get_logger(__name__)

API_PREFIX = "/api/v1"

_DESCRIPTION = """
ResearchLens reasoning service (Person 3).

Multi-LLM, multimodal, evidence-verified question answering over scientific
papers. Phase 1 exposes health/capability endpoints; reasoning endpoints
(`/reason`, `/analyze`) arrive in later phases per DEVELOPMENT_PLAN.md.

Evidence is untrusted document content and is never interpreted as
instructions (SECURITY.md).
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the ASGI application.

    Provider construction is side-effect free (no sockets), so the app starts
    cleanly with Ollama stopped — availability shows up in `/health` and
    `/models` instead.
    """
    settings = settings or Settings()
    setup_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "service_starting",
            component="app",
            provider=settings.model_provider,
            env=settings.reasoning_env,
            version=settings.app_version,
        )
        yield
        await app.state.registry.aclose()
        logger.info("service_stopped", component="app")

    app = FastAPI(
        title="ResearchLens Reasoning Service",
        version=settings.app_version,
        description=_DESCRIPTION,
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    app.state.settings = settings
    app.state.registry = build_registry(settings)
    app.state.started_at = time.time()

    # Order: CORS (outermost of the three) -> request context -> body limit.
    if settings.cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        if "*" in settings.cors_origins and settings.reasoning_env == "prod":
            logger.warning(
                "permissive_cors_in_prod",
                component="app",
                detail="CORS_ORIGINS contains '*' in a prod environment",
            )
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
        )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(RequestContextMiddleware)

    install_exception_handlers(app)
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(models.router, prefix=API_PREFIX)
    app.include_router(analyze.router, prefix=API_PREFIX)
    return app


#: Uvicorn entry point: ``uvicorn app.main:app``.
app = create_app()
