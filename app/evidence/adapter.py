"""Adapter: Person 2 retrieval record → our EvidenceBundle.

Person 2 returns ranked ``EvidenceItem`` dicts with fields that may be named
slightly differently than ours (``section`` vs ``section_title``, ``caption``
vs ``table_caption``, ``image_path`` vs ``image.path``). This module maps
them without loosening our validation.
"""

from __future__ import annotations

import hashlib
import re
import warnings
from typing import Any

from app.schemas.common import EvidenceType
from app.schemas.evidence import EvidenceBundle, EvidenceItem, ImageRef, PaperRef, TableData
from app.evidence.table_quality import (
    TABLE_EVIDENCE_STATUS_KEY,
    classify_table_evidence,
)

ALLOWED_TYPES: set[str] = {"text", "table", "figure", "equation", "metadata"}


def _clean_reference(source: dict[str, Any]) -> str | None:
    for key in ("reference", "label", "figure_id", "table_id"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    # Derive a human-readable label from a caption that explicitly contains
    # "Table N" / "Figure N" — only when the pattern is strong (no ambiguity).
    # This is the correct source for table/figure ``reference`` (human label,
    # not ``element_id``); element_id remains the stable ``evidence_id``.
    caption = source.get("caption")
    if isinstance(caption, str) and caption.strip():
        match = re.search(r"\b(?:Table|Figure)\s*[0-9][0-9A-Za-z\-]*\b", caption, re.IGNORECASE)
        if match:
            return match.group(0)
    # element_id as a final fallback (stable, but not a human label)
    value = source.get("element_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _image(source: dict[str, Any]) -> ImageRef | None:
    # Person 2 uses ``image_path`` (a relative PNG). We already enforce
    # exact-one-transport in ``ImageRef``, so we must not supply both.
    raw = source.get("image_path") or source.get("image")
    if not raw:
        return None
    if isinstance(raw, dict):
        # Already shaped like {"path","b64","mime","sha256"} or contains
        # image_path subfield — take path/b64 if present.
        path = raw.get("path") or raw.get("image_path")
        b64 = raw.get("b64")
        if isinstance(b64, str) and b64.strip():
            return ImageRef(b64=b64.strip(), mime=raw.get("mime"), sha256=raw.get("sha256"))
        if isinstance(path, str) and path.strip():
            return ImageRef(path=path.strip(), mime=raw.get("mime"), sha256=raw.get("sha256"))
        return None
    if isinstance(raw, str) and raw.strip():
        # A local extracted path — trust only that it's a non-empty string
        # (confinement happens in validation, not here).
        return ImageRef(path=raw.strip())
    return None


def _evidence_type(source: dict[str, Any]) -> EvidenceType:
    value = str(source.get("type", "text")).strip().lower()
    if value in ALLOWED_TYPES:
        return value  # type: ignore[return-value]
    # Be lenient: capit. variations ("Table" -> "table")
    lower = value.lower()
    if lower in ALLOWED_TYPES:
        return lower  # type: ignore[return-value]
    return "text"  # type: ignore[return-value]


def _evidence_id(source: dict[str, Any], paper_id: str, rank: int) -> str:
    is_element_id = source.get("element_id") not in (None, "")
    is_evidence_id = source.get("evidence_id") not in (None, "")

    raw = source.get("evidence_id") or source.get("element_id") or source.get("id")
    if isinstance(raw, str) and raw.strip() and re.match(r"^[A-Za-z0-9][A-Za-z0-9_:.\-]{0,127}$", raw.strip()):
        value = raw.strip()
        # Genuine evidence_id (explicit evidence_id key) is kept verbatim.
        if is_evidence_id:
            return value
        # Bare element_id (e.g. "elem_002") would collide across papers — namespace with paper_id.
        # An element_id that already carries a namespace (contains ":") is left as-is.
        if is_element_id and ":" not in value:
            return f"{paper_id}:{value}"
        return value

    parent = source.get("evidence_id_parent") or source.get("paper_id_source")
    seed = "|".join(
        [
            str(paper_id or "unknown_paper"),
            str(source.get("page") or rank),
            str(_evidence_type(source)),
            str(source.get("reference") or source.get("section") or source.get("caption") or rank),
            str(rank),
        ]
    )
    derived = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"{paper_id or 'paper'}:derived:{derived}"


def _table_data(source: dict[str, Any]) -> TableData | None:
    raw = source.get("table_data")
    if not isinstance(raw, dict):
        return None
    try:
        return TableData.model_validate(raw)
    except Exception:
        return None


def _content(source: dict[str, Any]) -> str:
    for key in ("content", "text", "markdown", "html", "value", "chunk"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    # Tables may have empty ``content`` with table_data instead
    if source.get("table_data") or source.get("image_path"):
        return ""
    return ""


def _figure_content(source: dict[str, Any]) -> str:
    """Preserve both ``content`` and figure ``context`` (Person 2's mention).

    For type ``figure`` the upstream ``content`` is often ``""`` while
    ``context`` holds the only surrounding sentence (e.g. "Figure 1
    illustrates ..."). We keep both, never drop one.
    """
    content = _content(source)
    context = source.get("context")
    if not isinstance(context, str) or not context.strip():
        return content
    context = context.strip()
    if not content:
        return context
    if content.strip() == context:
        return content.strip()
    return f"{content.strip()}\n{context}"


def _section(source: dict[str, Any]) -> str | None:
    for key in ("section", "section_title", "heading", "chapter"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _caption(source: dict[str, Any]) -> str | None:
    for key in ("caption", "table_caption", "figure_caption", "title"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _paper_id_for(source: dict[str, Any], fallback: str) -> str:
    for key in ("paper_id", "paper", "source_paper", "document_id", "doc_id"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _score(source: dict[str, Any]) -> float | None:
    for key in ("score", "relevance", "rank_score", "similarity"):
        value = source.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                continue
    return None


def _char_span(source: dict[str, Any]) -> tuple[int, int] | None:
    raw = source.get("char_span") or source.get("span")
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        try:
            start, end = int(raw[0]), int(raw[1])
            if 0 <= start <= end:
                return (start, end)
        except (TypeError, ValueError):
            pass
    return None


def adapt_retrieval_record(source: dict[str, Any], paper_id_fallback: str, rank: int) -> EvidenceItem:
    """One record → one ``EvidenceItem``. Never fabricates page/reference/paper."""

    paper_id = _paper_id_for(source, paper_id_fallback)
    evidence_id = _evidence_id(source, paper_id, rank)

    raw_type = _evidence_type(source)
    raw_page = source.get("page")

    # Preserve whatever integer page the source had; don't invent one.
    try:
        page: int | None = int(raw_page) if raw_page is not None and str(raw_page).strip() else None
        if page is not None and page < 1:
            page = None
    except (TypeError, ValueError):
        page = None

    image = _image(source)
    content = _figure_content(source)
    table_data = _table_data(source)
    if raw_type != "figure" and image is not None:
        # A stray image_path on a "text" record is still meaningful — keep it.
        pass
    if raw_type == "text" and image is not None:
        # Keep it — the vision pipeline will choose by ``type`` anyway.
        pass

    metadata = {
        "retrieval_rank": rank,
        "expanded_via_cross_ref": bool(source.get("expanded_via_cross_ref", False)),
        **({"cross_ref_trigger": str(source["cross_ref_trigger"])} if source.get("cross_ref_trigger") not in (None, "") else {}),
        **{
            k: v
            for k, v in (source.get("metadata") or {}).items()
            if not k.startswith("__")
        },
    }
    if raw_type == "table":
        upstream_metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
        declared_status = (
            metadata.get(TABLE_EVIDENCE_STATUS_KEY)
            or source.get(TABLE_EVIDENCE_STATUS_KEY)
            or upstream_metadata.get("table_extraction")
        )
        metadata[TABLE_EVIDENCE_STATUS_KEY] = classify_table_evidence(
            table_data=table_data,
            content=content,
            caption=_caption(source),
            image_present=image is not None,
            declared_status=declared_status,
        )

    return EvidenceItem(
        evidence_id=evidence_id,
        paper_id=paper_id,
        type=raw_type,  # type: ignore[arg-type]
        content=content,
        caption=_caption(source),
        reference=_clean_reference(source),
        page=page,
        section=_section(source),
        table_data=table_data,
        image=image,
        char_span=_char_span(source),
        score=_score(source),
        truncated=bool(source.get("truncated", False)),
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Retrieval response extraction — Person 2 may wrap the list differently
# ---------------------------------------------------------------------------


def _extract_raw_evidence_items(payload: Any) -> list[dict[str, Any]]:
    """Try every envelope Person 2 is known to use.

    Expected: ``{"evidence": [ ... ]}`` (per the ingest/retrieve contract).
    Observed variations: ``{"results": [...]}``, ``{"hits": [...]}``,
    bare list ``[...]``.
    """

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("evidence", "results", "hits", "items", "data", "retrieved"):
        value = payload.get(key)
        if isinstance(value, list) and any(isinstance(item, dict) for item in value):
            return [item for item in value if isinstance(item, dict)]

    # Maybe the object already has evidence-like keys at the top level
    if "type" in payload or "evidence_id" in payload:
        return [payload]

    return []


def _extract_query_context(payload: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None, list[str]]:
    """Retrieve optional pass-through retrieval metadata from the envelope.

    Covers: ``query`` at top level, ``retrieval`` dict, top-level
    ``retriever/run_id/retrieved_at`` echoes.
    """

    query: str | None = payload.get("query")
    for container in (payload.get("retrieval"),):
        if isinstance(container, dict) and "query" in container and container["query"]:
            query = str(container["query"])

    retrieval: dict[str, Any] | None = None
    raw = payload.get("retrieval")
    if isinstance(raw, dict):
        retrieval = dict(raw)
    elif any(key in payload for key in ("retriever", "top_k", "run_id")):
        retrieval = {
            k: payload[k]
            for k in ("retriever", "top_k", "run_id", "retrieved_at", "topK", "query")
            if k in payload
        }

    papers: list[str] = []
    raw_papers = payload.get("papers")
    if isinstance(raw_papers, list):
        for entry in raw_papers:
            if isinstance(entry, dict) and entry.get("paper_id"):
                papers.append(str(entry["paper_id"]))
            elif isinstance(entry, str):
                papers.append(entry)

    return query, retrieval, papers


def adapt_retrieval_response(
    payload: Any,
    *,
    paper_id_fallback: str = "retrieved",
) -> EvidenceBundle:
    """``payload`` (any Person 2 envelope) → our ``EvidenceBundle``.

    The only strict requirement enforced here is that each item becomes an
    ``EvidenceItem`` that passes our existing Pydantic validation.
    """

    if payload is None:
        raise ValueError("empty retrieval response")

    # Root may be {"evidence": [...]} or a bare list
    raw_items = _extract_raw_evidence_items(payload)
    envelope: dict[str, Any] = payload if isinstance(payload, dict) else {}

    query, retrieval, paper_ids = _extract_query_context(envelope)

    # Paper registry: assemble from explicit papers + per-item paper ids.
    by_paper: dict[str, EvidenceBundle] = {}  # collected below
    # Placeholder: we don't yet know papers' titles/years — PaperRef with
    # only paper_id is valid per EvidenceBundle (API_SPEC §4.1).

    raw_papers = envelope.get("papers")
    paper_refs: list[dict[str, Any]] = []
    if isinstance(raw_papers, list):
        for entry in raw_papers:
            if isinstance(entry, dict) and entry.get("paper_id"):
                paper_refs.append({"paper_id": str(entry["paper_id"]), "title": entry.get("title")})
            elif isinstance(entry, str):
                paper_refs.append({"paper_id": entry})

    # Also add paper ids that appear inside items but not in the envelope
    for raw in raw_items:
        pid = (raw.get("paper_id") or raw.get("document_id") or paper_id_fallback)  # type: ignore[union-attr]
        if not any(p["paper_id"] == pid for p in paper_refs):
            paper_refs.append({"paper_id": str(pid)})

    items: list[EvidenceItem] = []
    for rank, raw in enumerate(raw_items):
        try:
            item = adapt_retrieval_record(raw, paper_id_fallback, rank)
        except Exception as exc:
            # Skip malformed single-item rather than dropping the whole
            # response (the in-iter validation error is logged by the
            # provider before asking).
            import warnings

            warnings.warn(f"skipping malformed retrieval item at rank {rank}: {exc}", stacklevel=2)
            continue
        items.append(item)

    return EvidenceBundle(
        papers=paper_refs,  # type: ignore[arg-type]
        evidence=items,
        query=query,
        retrieval=retrieval,  # type: ignore[arg-type]
        warnings=["adapted from Person 2 /retrieve"] if raw_items else [],
    )
