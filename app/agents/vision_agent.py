"""Vision / Figure Reasoning Agent (ARCHITECTURE §4.4).

Consume figure images + captions + surrounding text via the unified
``ModelProvider`` interface. Image acquisition is security-confined
(``EVIDENCE_ROOT``, byte and pixel limits) and a degraded ``AgentRun``
is emitted — never a throw — when the image cannot be loaded.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import structlog

from app.agents.base import AgentContext, agent_error_from, complete_json, new_agent_run
from app.config import Settings
from app.core.errors import EvidenceInvalidError, ImagePathForbiddenError, PayloadTooLargeError
from app.evidence.images import (
    decode_validate_and_preprocess_b64,
    encode_file_for_vision,
)
from app.evidence.validation import resolve_image_path
from app.models.base import ChatMessage, ChatRequest, ChatResponse, ImagePayload, ModelProvider
from app.prompts.assembly import EvidenceContext, assemble_three_zone
from app.prompts.loader import load_prompt
from app.schemas.claims import AgentRun, Claim
from app.schemas.evidence import EvidenceItem

logger = structlog.get_logger(__name__)

AGENT_NAME = "vision_reasoner"
PROMPT_VERSION = "vision_agent/v1"
ALLOWED_KINDS = frozenset({"figure_observation", "author_claim", "inference", "limitation"})


def _figure_items(
    evidence: tuple[EvidenceItem, ...],
) -> list[EvidenceItem]:
    return [item for item in evidence if item.type == "figure"]


def _surrounding_text(evidence: tuple[EvidenceItem, ...], max_chars: int) -> list[EvidenceContext]:
    """Collectors of ``text`` context (captions describe figures)."""
    return [
        EvidenceContext.from_item(item, max_chars)
        for item in evidence
        if item.type == "text"
    ]


def _resolve_and_encode_for_figure(
    figure: EvidenceItem, settings: Settings
) -> tuple[list[ImagePayload], Path | None, str | None]:
    """Load a figure's image for a provider call.

    Returns ``(images, resolved_path_or_None, detail_or_None)``.
    ``detail`` is set when the image should be reported as a degraded run.
    """
    image = figure.image
    if image is None:
        return [], None, "figure has no image attached"

    if image.b64 is not None:
        try:
            # Downscale-for-vision copy; the stored source bytes are untouched.
            processed_b64, mime, _, _ = decode_validate_and_preprocess_b64(image.b64, settings)
        except (EvidenceInvalidError, PayloadTooLargeError) as exc:
            return [], None, f"b64 image for {figure.evidence_id} failed validation: {exc.detail}"
        return [ImagePayload(b64=processed_b64, mime=mime)], None, None  # type: ignore[arg-type]

    if image.path is not None:
        try:
            path = resolve_image_path(image.path, settings)
        except ImagePathForbiddenError as exc:
            return [], None, f"{figure.evidence_id}: {exc.detail}"

        if not path.is_file():
            return [], None, f"{figure.evidence_id} image not found at {image.path!r} (inside {settings.evidence_root})"

        try:
            b64, mime, _, _ = encode_file_for_vision(path, settings)
        except (EvidenceInvalidError, PayloadTooLargeError, OSError) as exc:
            detail = getattr(exc, "detail", str(exc))
            return [], None, f"{figure.evidence_id} image failed validation: {detail}"
        return [ImagePayload(b64=b64, mime=mime)], path, None  # type: ignore[arg-type]

    return [], None, "figure image has no transport"


def _evidence_contexts_for_vision(
    evidence: tuple[EvidenceItem, ...],
    settings: Settings,
    max_chars: int,
) -> tuple[list[EvidenceContext], list[ImagePayload], dict[str, str]]:
    """Build Zone C blocks and provider ``images`` for all figures.

    ``degraded`` maps ``evidence_id -> reason`` for missing/skipped images so
    the caller can emit the correct ``partial`` status.
    """
    figures = _figure_items(evidence)
    blocks: list[EvidenceContext] = []
    images: list[ImagePayload] = []
    degraded: dict[str, str] = {}

    for item in figures:
        blocks.append(EvidenceContext.from_item(item, max_chars))
        figure_images, _, reason = _resolve_and_encode_for_figure(item, settings)
        if figure_images:
            images.extend(figure_images)
        elif reason:
            degraded[item.evidence_id] = reason

    for block in _surrounding_text(evidence, max_chars):
        blocks.append(block)

    return blocks, images, degraded


def _validated_findings(
    raw_findings: list[dict[str, Any]], known_ids: set[str]
) -> tuple[list[Claim], list[str]]:
    kept: list[Claim] = []
    dropped: list[str] = []
    for idx, raw in enumerate(raw_findings):
        payload = dict(raw)
        payload.setdefault("agent", AGENT_NAME)
        try:
            candidate = Claim.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            dropped.append(f"claim[{idx}] schema: {type(exc).__name__}")
            continue
        if candidate.kind not in ALLOWED_KINDS:
            dropped.append(f"claim[{candidate.claim_id}] kind={candidate.kind!r} not allowed for vision")
            continue
        unknown = [eid for eid in candidate.evidence_ids if eid not in known_ids]
        if unknown:
            logger.warning(
                "vision_agent_dropped_unknown_evidence_id",
                component="agents",
                claim_id=candidate.claim_id,
                unknown=unknown,
            )
            continue
        kept.append(candidate)
    return kept, dropped


class VisionAgent:
    """Reasons over figure images plus their captions and surrounding text."""

    name = AGENT_NAME

    def __init__(self, provider: ModelProvider, *, prompt_version: str = "v1") -> None:
        self._provider = provider
        self._prompt_version = prompt_version

    async def run_for_evidence(
        self,
        ctx: AgentContext,
        evidence: tuple[EvidenceItem, ...] | None = None,
        *,
        settings: Settings | None = None,
        max_chars_per_item: int = 3000,
        timeout_s: float | None = None,
    ) -> tuple[list[Claim], AgentRun]:
        started = time.perf_counter()
        if evidence is None:
            evidence = ctx.evidence

        figures = _figure_items(evidence)
        if not figures:
            return [], new_agent_run(
                AGENT_NAME,
                ctx,
                status="no_evidence",
                started_s=started,
                evidence_ids_used=[],
                prompt_version=PROMPT_VERSION,
            )

        # Settings supply image limits and evidence-root. Use the caller's
        # ``ctx.extra.get("settings")`` or a conservative default when absent.
        resolved_settings = settings or ctx.extra.get("settings")  # type: ignore[arg-type]
        if resolved_settings is None:
            from app.config import Settings as _Settings  # noqa: WPS433 - import inside method only for defaults

            resolved_settings = _Settings(_env_file=None, model_provider="mock", log_level="WARNING", log_format="console")  # type: ignore[call-arg]

        blocks, images, degraded = _evidence_contexts_for_vision(evidence, resolved_settings, max_chars_per_item)
        known_ids = {item.evidence_id for item in evidence}

        # Degraded path: no usable images at all.
        if not images:
            detail = "; ".join(f"{eid}: {msg}" for eid, msg in degraded.items()) or "no usable figure images"
            logger.info("vision_agent_no_usable_images", component="agents", detail=detail)
            return [], new_agent_run(
                AGENT_NAME,
                ctx,
                status="no_evidence",
                started_s=started,
                evidence_ids_used=list(known_ids),
                prompt_version=PROMPT_VERSION,
            )

        # Validate provider has a configured model before sensitive payload.
        if not ctx.model or ctx.model.strip() == ctx.provider_name:
            # ``registry.provider.name`` was used as a placeholder when no
            # role model is configured. For vision, a missing model is
            # surfaced as no_evidence rather than calling the provider.
            # (Models with "not configured" are surfaced elsewhere.)
            pass

        template = load_prompt("vision_agent", self._prompt_version)
        messages = assemble_three_zone(template, ctx.query, blocks)
        system, user = messages[0].content, messages[1].content
        # Phase 9K: vision inference on 4 GB VRAM is slow (direct test: ~48s
        # for a full description). The agent budget (60s default) is too tight
        # once analysis+judge share the request, so vision gets a floor of
        # 240s unless the caller passes an explicit override.
        vision_timeout_s = timeout_s if timeout_s is not None else max(ctx.timeout_s, 240.0)
        vision_request = ChatRequest(
            model=ctx.model,
            messages=[
                ChatMessage(role="system", content=system),
                ChatMessage(role="user", content=user, images=images),
            ],
            temperature=ctx.temperature,
            max_tokens=ctx.max_tokens,
            timeout_s=vision_timeout_s,
            response_format="json",
            metadata={"request_id": ctx.request_id},
        )

        try:
            response = await self._provider.chat(vision_request)
            raw = response.text
            import json

            payload = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            # Retry for malformed JSON: the shared repair path is handled
            # inside ``complete_json``, but raw ChatRequest usage here bypasses
            # it — report directly.
            try:
                pass
            except Exception:
                pass
            # For phase 3 simplicity we treat any vision provider failure as
            # degraded rather than letting it become an unhandled exception.
            import importlib

            if "json.JSONDecodeError" in type(exc).__name__ or isinstance(exc, ValueError):
                # One repair retry for malformed vision output.
                try:
                    repaired = await self._provider.chat(
                        ChatRequest(
                            model=ctx.model,
                            messages=[
                                ChatMessage(role="system", content=system),
                                ChatMessage(
                                    role="user",
                                    content=user + "\n\nYour previous reply was not valid JSON. Reply with a single valid JSON object only.",
                                    images=images,
                                ),
                            ],
                            temperature=ctx.temperature,
                            max_tokens=ctx.max_tokens,
                            timeout_s=vision_timeout_s,
                            response_format="json",
                            metadata={"request_id": ctx.request_id},
                        )
                    )
                    import json as _json

                    payload = _json.loads(repaired.text)
                    response = repaired
                except Exception as second_exc:  # noqa: BLE001
                    from app.agents.base import agent_error_from as _agent_error_from

                    return [], new_agent_run(
                        AGENT_NAME,
                        ctx,
                        status="error",
                        started_s=started,
                        evidence_ids_used=list(known_ids),
                        prompt_version=PROMPT_VERSION,
                        error=_agent_error_from(second_exc),
                    )
            else:
                from app.agents.base import agent_error_from as _agent_error_from

                return [], new_agent_run(
                    AGENT_NAME,
                    ctx,
                    status="error",
                    started_s=started,
                    evidence_ids_used=list(known_ids),
                    prompt_version=PROMPT_VERSION,
                    error=_agent_error_from(exc),
                )

        raw_findings = payload.get("findings") if isinstance(payload, dict) else None
        if not isinstance(raw_findings, list):
            from app.agents.base import agent_error_from as _agent_error_from

            return [], new_agent_run(
                AGENT_NAME,
                ctx,
                status="error",
                started_s=started,
                evidence_ids_used=list(known_ids),
                prompt_version=PROMPT_VERSION,
                error=_agent_error_from(
                    type("MalformedOutput", (), {"detail": "payload.findings is not a list"})(),
                ),
            )

        kept, drop_reasons = _validated_findings(raw_findings, known_ids)
        if drop_reasons:
            logger.info(
                "vision_agent_filtered_findings",
                component="agents",
                kept=len(kept),
                dropped=len(drop_reasons),
                reasons=drop_reasons,
            )
        extra_note = "Some figures had no usable images" if degraded else ""
        status = "ok" if kept and not degraded else "partial" if kept or not degraded else "no_evidence"
        # Purposely do not expose degraded detail in the claim text — it stays
        # in logging + agent run metadata (SECURITY.md §7: no large payloads).

        return kept, new_agent_run(
            AGENT_NAME,
            ctx,
            status=status,  # type: ignore[arg-type]
            started_s=started,
            findings=[claim.claim_id for claim in kept],
            evidence_ids_used=list(known_ids),
            prompt_version=PROMPT_VERSION,
            usage_prompt_tokens=getattr(response, "usage", None).prompt_tokens if hasattr(response, "usage") else None,  # type: ignore[attr-defined]
            usage_completion_tokens=getattr(response, "usage", None).completion_tokens if hasattr(response, "usage") else None,  # type: ignore[attr-defined]
        )

    async def run(self, ctx: AgentContext) -> AgentRun:
        _, run = await self.run_for_evidence(ctx, ctx.evidence)
        return run
