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


#: Maximum figures attached to one vision call (VRAM + prompt-focus bound).
#: Explicit multi-figure questions (compare Figure 1 and Figure 2) may use up
#: to this many; ordinary single-figure questions attach exactly one.
MAX_VISION_IMAGES = 2

#: Maximum same-paper text blocks attached as context (caption-adjacent first).
MAX_VISION_TEXT_BLOCKS = 2


def _infer_paper_hint(query: str, evidence: tuple[EvidenceItem, ...]) -> str | None:
    """Paper id hint from explicit arXiv ids in the query (never guessed)."""
    from app.evidence.retrieval_client import infer_paper_ids  # noqa: WPS433

    candidates = list(infer_paper_ids(query))
    if candidates:
        return candidates[0]
    return None


def _figure_references_in_query(query: str) -> list[str]:
    """Explicit Figure N mentions in the query (canonical form)."""
    import re as _re

    refs: list[str] = []
    for m in _re.finditer(r"\b(?:Figure|Fig\.?)\s*([0-9][0-9A-Za-z\-]*)", query or "", _re.IGNORECASE):
        canonical = f"Figure {m.group(1)}"
        if canonical not in refs:
            refs.append(canonical)
    return refs


def _figure_reference_matches_item(reference: str, item: EvidenceItem) -> bool:
    """Whether an explicit query reference (e.g. 'Figure 4') matches an item."""
    if not reference or item.reference is None:
        return False
    return item.reference.strip().lower() == reference.strip().lower()


def _score_text_for_figure(
    text: EvidenceItem, figure: EvidenceItem, query: str
) -> tuple[int, str]:
    """Relevance score for a text block given a target figure (higher first).

    Prefers: same paper > mentions the figure reference/caption words >
    mentions generic figure words > query word overlap. Deterministic
    (no model, no randomness). Returns ``(score, evidence_id)`` for stable
    tie-breaking.
    """
    import re as _re

    score = 0
    if text.paper_id == figure.paper_id:
        score += 10
    haystack = f"{text.content} {text.caption or ''} {text.section or ''}".lower()
    ref = (figure.reference or "").lower()
    if ref and ref in haystack:
        score += 5
    caption_words = {w for w in _re.findall(r"[a-z0-9]+", (figure.caption or "").lower()) if len(w) > 3}
    if caption_words and any(w in haystack for w in caption_words):
        score += 3
    if _re.search(r"\b(?:figure|fig\.?|diagram|chart)\b", haystack):
        score += 1
    query_words = {w for w in _re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 3}
    if query_words and any(w in haystack for w in query_words):
        score += 1
    return score, text.evidence_id


def select_vision_context(
    evidence: tuple[EvidenceItem, ...],
    query: str,
    *,
    max_images: int = MAX_VISION_IMAGES,
    max_texts: int = MAX_VISION_TEXT_BLOCKS,
) -> tuple[list[EvidenceItem], list[EvidenceItem]]:
    """Compact, deterministic vision context (Phase 9Q).

    Returns ``(figures, texts)`` where ``figures`` are figure items with
    image bytes first (target paper preferred, original order otherwise) and
    ``texts`` are the most relevant same-paper text blocks. Tables and
    other-paper figures are excluded from the *vision call only* — the full
    bundle still reaches text/table agents and the judge. Contradictory
    evidence is never filtered by stance, only by relevance role.

    When the query explicitly names a figure (e.g. "Figure 4"), that
    reference is the primary rank key — before paper hint and original order.
    """
    figures = [item for item in evidence if item.type == "figure"]
    with_bytes = [f for f in figures if f.image is not None and (f.image.b64 or f.image.path)]
    paper_hint = _infer_paper_hint(query, evidence)
    wanted_refs = _figure_references_in_query(query)

    def figure_key(item: EvidenceItem) -> tuple[int, int, int]:
        ref_match = 0 if any(_figure_reference_matches_item(r, item) for r in wanted_refs) else 1
        same_paper = 0 if (paper_hint is not None and item.paper_id == paper_hint) else 1
        order = figures.index(item)
        return (ref_match, same_paper, order)

    # Target figures first: same-paper-with-bytes, then any with-bytes, then
    # caption-only same-paper figures (context, never visual subjects).
    ordered = sorted(with_bytes, key=figure_key)
    # Same-paper-with-bytes first; remaining with-bytes figures fill the
    # bounded budget in original order (explicit multi-figure questions).
    # Caption-only figures are context, never visual subjects: include one
    # same-paper caption-only figure only when no second with-bytes figure
    # exists to fill the budget.
    if len(ordered) < max_images and paper_hint is not None:
        caption_only = [
            f for f in figures
            if f not in ordered and f.paper_id == paper_hint
            and (f.image is None or (not f.image.b64 and not f.image.path))
        ]
        ordered = ordered + caption_only[: max(0, max_images - len(ordered))]
    selected_figures = ordered[:max_images]

    anchor = selected_figures[0] if selected_figures else None
    texts = [item for item in evidence if item.type == "text"]
    if anchor is not None:
        scored = sorted(
            ((_score_text_for_figure(t, anchor, query), t) for t in texts),
            key=lambda pair: (-pair[0][0], pair[0][1]),
        )
        # Keep only same-paper texts unless none exist at all.
        same_paper = [t for _, t in scored if t.paper_id == anchor.paper_id]
        pool = same_paper if same_paper else [t for _, t in scored]
        selected_texts = pool[:max_texts]
    else:
        selected_texts = []
    return selected_figures, selected_texts


def _evidence_contexts_for_vision(
    evidence: tuple[EvidenceItem, ...],
    settings: Settings,
    max_chars: int,
    *,
    query: str = "",
) -> tuple[list[EvidenceContext], list[ImagePayload], dict[str, str]]:
    """Build Zone C blocks and provider ``images`` for selected figures.

    Compact selection (Phase 9Q): target figure(s) with bytes first, then
    same-paper text context. ``degraded`` maps ``evidence_id -> reason`` for
    missing/skipped images so the caller can emit the correct ``partial``
    status.
    """
    selected_figures, selected_texts = select_vision_context(evidence, query)
    # Fall back to all figures only when selection is empty but figures exist
    # (e.g. caption-only bundle → honest ``no_evidence`` via degraded map).
    if not selected_figures:
        selected_figures = _figure_items(evidence)
    blocks: list[EvidenceContext] = []
    images: list[ImagePayload] = []
    degraded: dict[str, str] = {}

    for item in selected_figures:
        blocks.append(EvidenceContext.from_item(item, max_chars))
        figure_images, _, reason = _resolve_and_encode_for_figure(item, settings)
        if figure_images:
            images.extend(figure_images)
        elif reason:
            degraded[item.evidence_id] = reason

    for item in selected_texts:
        blocks.append(EvidenceContext.from_item(item, max_chars))

    return blocks, images, degraded


def _validated_findings(
    raw_findings: list[dict[str, Any]],
    known_ids: set[str],
    *,
    usable_figure_ids: set[str] | None = None,
) -> tuple[list[Claim], list[str]]:
    kept: list[Claim] = []
    dropped: list[str] = []
    usable = usable_figure_ids if usable_figure_ids is not None else set(known_ids)
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
        # Phase 9P: a figure_observation must cite at least one figure with
        # usable image bytes — never text-only evidence. Text-only citations
        # stay ungrounded visual claims and are dropped here, not verified.
        if candidate.kind == "figure_observation":
            if not any(eid in usable for eid in candidate.evidence_ids):
                dropped.append(
                    f"claim[{candidate.claim_id}] figure_observation cites no usable figure image"
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

        blocks, images, degraded = _evidence_contexts_for_vision(
            evidence, resolved_settings, max_chars_per_item, query=ctx.query
        )
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
            # Raw ChatRequest usage bypasses the shared ``complete_json``
            # repair path; offer one malformed-JSON repair retry here. Any
            # other provider failure degrades rather than raising.
            if isinstance(exc, ValueError):
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

        # Phase 9P: usable-figure gating — figure_observation claims must cite
        # at least one figure whose bytes were actually attached to this call
        # (tracked via the degraded map: figures WITHOUT an entry produced
        # payloads). Text-only citations can never ground a visual claim.
        degraded_ids = set(degraded)
        # Only figures represented in this compact call are eligible.  A
        # previously broad set here allowed the model to cite an unselected
        # same-paper figure whose bytes were never attached.
        selected_ids = {block.evidence_id for block in blocks}
        usable_figure_ids = {
            item.evidence_id
            for item in evidence
            if item.type == "figure"
            and item.evidence_id in selected_ids
            and item.evidence_id in known_ids
            and item.evidence_id not in degraded_ids
        }
        # A call with zero attached images has no usable figures at all.
        if not images:
            usable_figure_ids = set()
        kept, drop_reasons = _validated_findings(
            raw_findings, known_ids, usable_figure_ids=usable_figure_ids
        )
        # Phase 9Q+: one controlled retry on valid-but-empty findings. The 3B
        # VLM intermittently abstains on multi-block prompts even when the
        # same image verifies via a minimal prompt. Retry once with the
        # single target figure + caption only (no surrounding text), same
        # validated image bytes. Never bypasses validation/gating.
        if not kept and images and not degraded:
            retry_kept, retry_dropped = await self._retry_minimal(
                ctx=ctx,
                evidence=evidence,
                blocks=blocks,
                images=images,
                known_ids=known_ids,
                usable_figure_ids=usable_figure_ids,
                system=system,
                vision_timeout_s=vision_timeout_s,
                started=started,
            )
            if retry_kept:
                kept = retry_kept
                drop_reasons = drop_reasons + retry_dropped
                logger.info(
                    "vision_agent_retry_succeeded",
                    component="agents",
                    kept=len(kept),
                )
            elif retry_dropped:
                drop_reasons = drop_reasons + retry_dropped
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

    async def _retry_minimal(
        self,
        *,
        ctx: AgentContext,
        evidence: tuple[EvidenceItem, ...],
        blocks: list[EvidenceContext],
        images: list[ImagePayload],
        known_ids: set[str],
        usable_figure_ids: set[str],
        system: str,
        vision_timeout_s: float,
        started: float,
    ) -> tuple[list[Claim], list[str]]:
        """One minimal retry: target figure block only, same validated image."""
        from app.prompts.assembly import render_evidence_block

        target_eid: str | None = None
        minimal_user = ""
        for block in blocks:
            if block.evidence_id in usable_figure_ids:
                target_eid = block.evidence_id
                minimal_user = (
                    f"--- USER QUESTION ---\n{ctx.query}\n--- END USER QUESTION ---\n\n"
                    + render_evidence_block(block)
                )
                break
        if target_eid is None:
            return [], ["retry skipped: no usable figure"]
        # Only the target figure's image was attached to the retry call
        # (images[:1]), so only claims citing the target figure can be
        # image-verified by it. Never let a retry on figure A accept a claim
        # about figure B whose bytes were not supplied to this call.
        retry_usable = {target_eid}
        try:
            response = await self._provider.chat(
                ChatRequest(
                    model=ctx.model,
                    messages=[
                        ChatMessage(role="system", content=system),
                        ChatMessage(role="user", content=minimal_user, images=images[:1]),
                    ],
                    temperature=ctx.temperature,
                    max_tokens=ctx.max_tokens,
                    timeout_s=vision_timeout_s,
                    response_format="json",
                    metadata={"request_id": ctx.request_id},
                )
            )
            import json as _json

            payload = _json.loads(response.text)
        except Exception as exc:  # noqa: BLE001
            return [], [f"retry failed: {type(exc).__name__}"]
        raw = payload.get("findings") if isinstance(payload, dict) else None
        if not isinstance(raw, list):
            return [], ["retry payload.findings is not a list"]
        return _validated_findings(raw, known_ids, usable_figure_ids=retry_usable)

    async def run(self, ctx: AgentContext) -> AgentRun:
        _, run = await self.run_for_evidence(ctx, ctx.evidence)
        return run
