"""Evidence contracts — the Person 2 → Person 3 boundary (API_SPEC §4).

This is the most important contract in the module: evidence metadata is
authoritative, ``evidence_id`` is the citation anchor, and ``paper_id``
preserves paper identity end to end (never merged across papers).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import EvidenceType

#: ``evidence_id`` is also used as an in-prompt delimiter (SECURITY.md §2),
#: so the charset is deliberately conservative.
EVIDENCE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_:.\-]{0,127}$"


class PaperRef(BaseModel):
    """Identity/metadata for one paper. Never merged across papers."""

    model_config = ConfigDict(extra="forbid")

    paper_id: str = Field(min_length=1)
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    num_pages: int | None = None


class TableData(BaseModel):
    """Structured table so numeric reasoning can be deterministic (no LLM guesswork)."""

    model_config = ConfigDict(extra="forbid")

    headers: list[str]
    rows: list[list[str | None]]
    caption: str | None = None
    cell_locators: dict[str, str] = Field(default_factory=dict)  # "r0|c1" -> locator


class ImageRef(BaseModel):
    """Image reference. Exactly one transport: filesystem path *or* base64.

    ``path`` is always relative to ``EVIDENCE_ROOT`` and is confined to it at
    validation time (SECURITY.md §4) — absolute paths and traversal are
    rejected by :func:`app.evidence.validation.resolve_image_path`.
    """

    model_config = ConfigDict(extra="forbid")

    path: str | None = None
    b64: str | None = None
    mime: str | None = None
    sha256: str | None = None

    @model_validator(mode="after")
    def _exactly_one_transport(self) -> "ImageRef":
        if (self.path is None) == (self.b64 is None):
            raise ValueError("image must set exactly one of 'path' or 'b64'")
        return self


class EvidenceItem(BaseModel):
    """One atomic piece of evidence (text span, table, figure, equation, metadata)."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(pattern=EVIDENCE_ID_PATTERN)
    paper_id: str = Field(min_length=1)
    type: EvidenceType
    content: str = ""
    caption: str | None = None
    reference: str | None = None  # human label: "Table 3", "Figure 5", "Section 4.2"
    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    table_data: TableData | None = None
    image: ImageRef | None = None
    char_span: tuple[int, int] | None = None
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    truncated: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("char_span")
    @classmethod
    def _span_sane(cls, value: tuple[int, int] | None) -> tuple[int, int] | None:
        if value is None:
            return None
        start, end = value
        if start < 0 or end < start:
            raise ValueError("char_span must satisfy 0 <= start <= end")
        return value

    @property
    def text_length(self) -> int:
        """Size of the text payload used for budget checks."""
        return len(self.content) + len(self.caption or "")


class RetrievalMeta(BaseModel):
    """Pass-through provenance so evaluation can separate retrieval vs reasoning errors."""

    model_config = ConfigDict(extra="forbid")

    query: str | None = None
    retriever: str | None = None
    top_k: int | None = Field(default=None, ge=1)
    retrieved_at: datetime | None = None
    run_id: str | None = None


class EvidenceBundle(BaseModel):
    """Person 2 → Person 3 boundary object (API_SPEC §4)."""

    model_config = ConfigDict(extra="forbid")

    query: str | None = None
    papers: list[PaperRef] = Field(default_factory=list)
    evidence: list[EvidenceItem]
    retrieval: RetrievalMeta | None = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ids_unique(self) -> "EvidenceBundle":
        ids = [item.evidence_id for item in self.evidence]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"duplicate evidence_id values: {dupes}")
        paper_ids = [paper.paper_id for paper in self.papers]
        if len(paper_ids) != len(set(paper_ids)):
            raise ValueError("duplicate paper_id values in papers")
        return self
