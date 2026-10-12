"""Phase 9M/9P — one bounded figure-scoped retrieval retry.

When the question targets a figure — explicitly (``Figure N``) or
semantically (diagram/chart/architecture/...) — and names a paper (explicit
``paper_ids`` or an inferred arXiv id), but the first retrieval returned no
*usable* figure evidence for that paper, retry once with a paper+figure
scoped query that preserves the original question verbatim. The retry
replaces the bundle only when it returns evidence belonging to the intended
paper; otherwise the original bundle (and its honest degradation) stands.

``usable`` means: at least one figure item for the intended paper that
carries image bytes (``image.b64``) or an ``image.path``. Caption-only
figure records never count as usable — they must not become visual
observations.
"""

from __future__ import annotations

import re

from app.evidence.adapter import (
    adapt_retrieval_record,
    adapt_retrieval_response,
)
from app.evidence.retrieval_client import (
    RetrievalProvider,
    RetrievalRequest,
    infer_paper_ids,
)
from app.schemas.evidence import EvidenceBundle

_FIGURE_REF_RE = re.compile(r"\b(?:Figure|Fig\.?)\s*([0-9][0-9A-Za-z\-]*)", re.IGNORECASE)

#: Semantic figure-intent words. A question carrying one of these *and* an
#: identifiable paper is treated as figure-seeking even without an explicit
#: ``Figure N`` token (Phase 9P). Generic wording without a paper never fires.
_FIGURE_INTENT_RE = re.compile(
    r"\b(?:figure|diagram|chart|architecture|plot|image|curve|trend|visuali[sz]ation)\b",
    re.IGNORECASE,
)


def figure_references_in_query(query: str) -> list[str]:
    """Explicit ``Figure N`` mentions in the question (``['Figure 1']``)."""
    found: list[str] = []
    for match in _FIGURE_REF_RE.finditer(query or ""):
        canonical = f"Figure {match.group(1)}"
        if canonical not in found:
            found.append(canonical)
    return found


def has_figure_intent(query: str) -> bool:
    """Semantic figure intent (diagram/chart/architecture/...) without a number."""
    return bool(_FIGURE_INTENT_RE.search(query or ""))


def _has_usable_figure(bundle: EvidenceBundle, paper_id: str | None = None) -> bool:
    for item in bundle.evidence:
        if item.type != "figure":
            continue
        if paper_id is not None and item.paper_id != paper_id:
            continue
        image = item.image
        if image is None:
            continue
        if image.b64:
            return True
        if image.path:
            return True
    return False


def _scoped_query(query: str, paper_id: str, refs: list[str]) -> str:
    """Scoped retry preserving the question's own intent (Phase 9P).

    Retries the *original question verbatim* (which the ranker already
    handles) scoped to the paper via ``paper_ids`` — the paper id is NOT
    prepended to the text because the dense ranker scores pure-text queries
    better without an id prefix (measured: id-prefixed retry returns zero
    same-paper hits, verbatim retry returns elem_000 at rank 3). Explicit
    figure references are kept as-is when the user gave them; no
    architecture-specific terms are ever injected.
    """
    return query.strip()


async def maybe_scoped_figure_retry(
    provider: RetrievalProvider,
    query: str,
    bundle: EvidenceBundle,
    *,
    top_k: int,
    timeout_s: float,
    paper_ids: tuple[str, ...] | None = None,
) -> EvidenceBundle:
    """Apply the single bounded retry described in the module docstring."""
    refs = figure_references_in_query(query)
    candidates = list(paper_ids or ()) or list(infer_paper_ids(query))
    if not candidates:
        return bundle
    # Semantic figure intent (diagram/chart/...) counts alongside an explicit
    # ``Figure N`` — but only when a paper is identifiable. Generic wording
    # without a paper never retries (fail-closed).
    if not refs and not has_figure_intent(query):
        return bundle
    paper_id = candidates[0]
    if _has_usable_figure(bundle, paper_id):
        return bundle

    retry_query = _scoped_query(query, paper_id, refs)
    try:
        response = await provider.retrieve(
            RetrievalRequest(
                query=retry_query,
                top_k=top_k,
                timeout_s=timeout_s,
                paper_ids=(paper_id,),
            )
        )
    except Exception:
        return bundle

    retry_bundle = response.bundle
    if retry_bundle is None or not retry_bundle.evidence:
        return bundle
    # The retry must belong to the intended paper; mixed-paper retries are
    # discarded to preserve provenance.
    if not any(item.paper_id == paper_id for item in retry_bundle.evidence):
        return bundle
    if not _has_usable_figure(retry_bundle, paper_id):
        return bundle
    return retry_bundle
