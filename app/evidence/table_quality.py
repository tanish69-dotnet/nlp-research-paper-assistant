"""Conservative table-evidence completeness checks.

The retrieval contract permits a table item with only a caption.  That is useful
for retrieval, but it is not enough to support a numerical or comparative table
claim.  These helpers keep that distinction explicit without attempting to
extract or invent table values.
"""

from __future__ import annotations

import re
from typing import Any

from app.schemas.evidence import EvidenceItem, TableData

TABLE_EVIDENCE_STATUS_KEY = "table_evidence_status"

STATUS_COMPLETE = "complete"
STATUS_EXPLICIT_TEXT = "explicit_text"
STATUS_CAPTION_ONLY = "caption_only"
STATUS_IMAGE_ONLY = "image_only"
STATUS_INCOMPLETE = "incomplete"

_KNOWN_STATUSES = {
    STATUS_COMPLETE,
    STATUS_EXPLICIT_TEXT,
    STATUS_CAPTION_ONLY,
    STATUS_IMAGE_ONLY,
    STATUS_INCOMPLETE,
}

_TABLE_WRAPPER_PREFIXES = (
    "paper:",
    "type:",
    "section:",
    "caption:",
    "context:",
    "mentions:",
)

_MARKDOWN_SEPARATOR = re.compile(r"^\s*\|?\s*[-:| ]+\s*\|?\s*$")
_COMPARATIVE_TERMS = re.compile(
    r"\b(?:best|better|highest|lowest|higher|lower|outperform(?:s|ed)?|"
    r"exceed(?:s|ed)?|ranking|ranked|top|accuracy|score|metric|performance)\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")
_METRIC_LABEL = re.compile(r"\bR\s*\d+\s*@\s*\d+\b", re.IGNORECASE)
_PAPER_ID = re.compile(r"\b\d{4}\.\d{4,5}(?:v\d+)?\b", re.IGNORECASE)
_DERIVED_VALUE = re.compile(
    r"\b(?:difference|delta|gap|change|increase|decrease|improvement|drop|margin)\b",
    re.IGNORECASE,
)


def _table_data_has_values(table_data: TableData | None) -> bool:
    """Return whether structured table data contains at least one value."""
    if table_data is None or not table_data.headers or not table_data.rows:
        return False
    return any(
        cell is not None and str(cell).strip()
        for row in table_data.rows
        for cell in row
    )


def _has_markdown_table(content: str) -> bool:
    """Recognize a header/separator/data Markdown table in content."""
    lines = [line.strip() for line in (content or "").splitlines() if line.strip()]
    pipe_lines = [line for line in lines if line.startswith("|") and line.endswith("|")]
    if len(pipe_lines) < 3:
        return False
    return any(_MARKDOWN_SEPARATOR.match(line) for line in pipe_lines[1:])


def _meaningful_content(content: str, caption: str | None) -> str:
    """Remove the standard visual preamble and repeated caption from content."""
    caption_text = (caption or "").strip()
    meaningful: list[str] = []
    for raw_line in (content or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        if lower.startswith(_TABLE_WRAPPER_PREFIXES):
            continue
        if caption_text and line == caption_text:
            continue
        meaningful.append(line)
    return "\n".join(meaningful).strip()


def classify_table_evidence(
    *,
    table_data: TableData | None,
    content: str,
    caption: str | None,
    image_present: bool,
    declared_status: Any = None,
) -> str:
    """Classify table evidence without treating captions as table values.

    A supplier declaration is preserved when it is one of our known statuses.
    Structured rows and Markdown rows are complete representations.  Other
    non-wrapper prose can be explicit comparison evidence, but a caption-only
    item is always incomplete for numerical table reasoning.
    """
    declared = str(declared_status or "").strip().lower()
    if declared in _KNOWN_STATUSES:
        return declared
    if declared in {"partial", "incomplete", "missing", "failed"}:
        return STATUS_INCOMPLETE
    if _table_data_has_values(table_data) or _has_markdown_table(content):
        return STATUS_COMPLETE

    meaningful = _meaningful_content(content, caption)
    if meaningful and (_NUMBER.search(meaningful) or _COMPARATIVE_TERMS.search(meaningful)):
        return STATUS_EXPLICIT_TEXT
    if image_present:
        return STATUS_IMAGE_ONLY
    if not meaningful:
        return STATUS_CAPTION_ONLY
    return STATUS_INCOMPLETE


def table_evidence_status(item: EvidenceItem) -> str:
    """Return the explicit or conservatively inferred status for one item."""
    declared = item.metadata.get(TABLE_EVIDENCE_STATUS_KEY)
    return classify_table_evidence(
        table_data=item.table_data,
        content=item.content,
        caption=item.caption,
        image_present=item.image is not None,
        declared_status=declared,
    )


def table_evidence_supports_values(item: EvidenceItem) -> bool:
    """Whether the item contains usable structured/text evidence for values."""
    return table_evidence_status(item) in {STATUS_COMPLETE, STATUS_EXPLICIT_TEXT}


def table_evidence_supports_claim(item: EvidenceItem, claim: Any) -> bool:
    """Require structured comparison claims to name a supplied table row.

    Prose explicitly stating a comparison is accepted as ``explicit_text``
    evidence. Structured table comparisons must mention a row label that
    actually exists in the cited table.
    """
    if not table_evidence_supports_values(item):
        return False
    if item.table_data is None:
        return True

    kind = str(getattr(claim, "kind", "") or "")
    if kind not in {"table_comparison", "comparison_row"}:
        return True
    text = str(getattr(claim, "text", "") or "").lower()
    labels = {
        str(row[0]).strip().lower()
        for row in item.table_data.rows
        if row and row[0] is not None and str(row[0]).strip()
    }
    if bool(labels) and any(label in text for label in labels if len(label) > 1):
        return True

    # Preserve the existing numeric-evidence path for claims that state a
    # concrete value but use a narrative label such as "we" instead of the
    # table's row label.  A value must actually occur in the cited table.
    claim_values: list[float] = []
    scrubbed = _PAPER_ID.sub("", _METRIC_LABEL.sub("", text or ""))
    for match in _NUMBER.finditer(scrubbed):
        prefix = scrubbed[max(0, match.start() - 12) : match.start()]
        if (match.start() > 0 and scrubbed[match.start() - 1] == "@") or re.search(
            r"(?:table|figure)\s*$", prefix, re.IGNORECASE
        ):
            continue
        claim_values.append(float(match.group(0)))
    table_values: set[float] = set()
    for row in item.table_data.rows:
        for cell in row:
            if cell is None:
                continue
            try:
                table_values.add(float(str(cell).strip().rstrip("%")))
            except ValueError:
                continue
    if bool(claim_values) and all(value in table_values for value in claim_values):
        return True

    # A requested difference is a derived value, not a cell that should be
    # present verbatim.  Accept only exact pairwise differences from supplied
    # numeric cells; the LLM still has to explain the result and the cited
    # table remains the source of both operands.
    if claim_values and _DERIVED_VALUE.search(text):
        values = sorted(table_values)
        derived = {
            round(abs(left - right), 6)
            for index, left in enumerate(values)
            for right in values[index + 1 :]
        }
        if all(round(value, 6) in derived for value in claim_values):
            return True
    return False


def claim_mentions_numeric_value(text: str) -> bool:
    """Detect a measurement number while ignoring references such as ``Table 4``."""
    for match in _NUMBER.finditer(text or ""):
        prefix = (text or "")[max(0, match.start() - 10) : match.start()].lower()
        if re.search(r"(?:table|figure)\s*$", prefix):
            continue
        return True
    return False


def claim_requires_table_values(claim: Any) -> bool:
    """Detect claims whose support requires table cells/comparison evidence."""
    text = str(getattr(claim, "text", "") or "")
    kind = str(getattr(claim, "kind", "") or "")
    agent = str(getattr(claim, "agent", "") or "")
    if kind == "table_comparison":
        return True
    if kind in {"table_observation", "table_interpretation", "comparison_row"}:
        return claim_mentions_numeric_value(text) or bool(_COMPARATIVE_TERMS.search(text))
    if agent == "table_reasoner":
        return claim_mentions_numeric_value(text) or bool(_COMPARATIVE_TERMS.search(text))
    return False
