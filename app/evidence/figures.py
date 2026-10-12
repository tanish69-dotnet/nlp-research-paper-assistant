"""Phase 9M — one bounded figure-scoped retrieval retry.

When the question explicitly targets a figure (``Figure N``) and names a
paper, but the first retrieval returned no *usable* figure evidence for that
paper, retry once with a paper+figure scoped query. The retry replaces the
bundle only when it returns evidence belonging to the intended paper;
otherwise the original bundle (and its honest degradation) stands.

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


def figure_references_in_query(query: str) -> list[str]:
    """Explicit ``Figure N`` mentions in the question (``['Figure 1']``)."""
    found: list[str] = []
    for match in _FIGURE_REF_RE.finditer(query or ""):
        canonical = f"Figure {match.group(1)}"
        if canonical not in found:
            found.append(canonical)
    return found


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
    ref_part = " ".join(refs) if refs else "Figure"
    return f"{ref_part} {paper_id} architecture diagram components data flow"


async def maybe_scoped_figure_retry(
    provider: RetrievalProvider,
    query: str,
    bundle: EvidenceBundle,
    *,
    top_k: int,
    timeout_s: float,
) -> EvidenceBundle:
    """Apply the single bounded retry described in the module docstring."""
    refs = figure_references_in_query(query)
    if not refs:
        return bundle
    paper_ids = infer_paper_ids(query)
    if not paper_ids:
        return bundle
    paper_id = paper_ids[0]
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
