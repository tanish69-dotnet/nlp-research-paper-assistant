"""Deterministic, conservative evidence checks before the LLM Judge.

- Claim evidence ids must be within the supplied bundle.
- Empty claims raise empty-claim handling.
- Numeric contradiction (authoritative cell vs claim text) when detectable.
"""

from __future__ import annotations

import re
from typing import Literal

from app.schemas.evidence import EvidenceBundle, TableData
from app.schemas.claims import Claim
from app.evidence.table_quality import (
    claim_requires_table_values,
    table_evidence_status,
    table_evidence_supports_claim,
    table_evidence_supports_values,
)

Verdict = Literal["SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONTRADICTED"]


def claim_has_unknown_evidence(claim: Claim, supply: set[str]) -> list[str]:
    return [eid for eid in claim.evidence_ids if eid not in supply]


_CANDIDATE_CELL_RE = re.compile(r"\b([0-9]+(?:\.[0-9]+)?)\b")
_METRIC_LABEL_RE = re.compile(r"\bR\s*\d+\s*@\s*\d+\b", re.IGNORECASE)
_PAPER_ID_RE = re.compile(r"\b\d{4}\.\d{4,5}(?:v\d+)?\b", re.IGNORECASE)


def _parse_numbers_from_claim(text: str) -> list[float]:
    out: list[float] = []
    scrubbed = _PAPER_ID_RE.sub("", _METRIC_LABEL_RE.sub("", text or ""))
    for match in _CANDIDATE_CELL_RE.finditer(scrubbed):
        # Metric labels such as R10@1 contain digits that are not table cell
        # values.  Likewise, Table 4 / Figure 5 are provenance references.
        prefix = scrubbed[max(0, match.start() - 12) : match.start()].lower()
        if match.start() > 0 and scrubbed[match.start() - 1] == "@":
            continue
        if re.search(r"(?:table|figure)\s*$", prefix):
            continue
        token = match.group(1)
        try:
            out.append(float(token))
        except ValueError:
            continue
    return out


def _table_cell_lookup(bundle: EvidenceBundle, evidence_id: str) -> TableData | None:
    for item in bundle.evidence:
        if item.evidence_id == evidence_id and item.table_data is not None:
            return item.table_data
    return None


def _cell_values_for_table(table: TableData) -> dict[float, str]:
    """Collectors of numeric cell values (precision 1e-6 tolerant) mapped by float value."""
    out: dict[float, str] = {}
    for row in table.rows:
        for cell in row:
            if cell is None:
                continue
            try:
                value = float(str(cell).strip().rstrip("%"))
            except ValueError:
                continue
            out[value] = str(cell)
    return out


def maybe_contradicted_by_table(
    claim: Claim,
    bundle: EvidenceBundle,
    *,
    epsilon: float = 1e-6,
) -> tuple[bool, str | None]:
    """Conservative numeric contradiction check for table-sourced claims.

    Returns ``(contradicted, detail)``. ``contradicted`` is True only when
    the claim states a precise number that conflicts with a numeric cell in the
    cited table evidence (authoritative Structured table_data, not prose).
    ``PARTIALLY_SUPPORTED`` etc remain the LLM Judge's job — this layer only
    says CONTRADICTED or UNSUPPORTED for deterministic invariants.
    """
    numbers = _parse_numbers_from_claim(claim.text)
    if not numbers:
        return False, None

    for eid in claim.evidence_ids:
        table = _table_cell_lookup(bundle, eid)
        if table is None:
            continue
        numeric_cells = _cell_values_for_table(table)
        # If the claim contains a number that equals (within epsilon) no cell
        # of the cited table, and the table has numeric cells, consider it
        # potentially contradicted when the claim is table-oriented.
        capable = any(idea in claim.kind for idea in ("table_", "observation")) or "table" in (claim.agent or "")
        # Broaden: also catch explicit "accuracy = 72%" style claims vs any table value
        for num in numbers:
            # If ANY candidate numeric value in the table matches (within epsilon)
            # we *do not* contradict.
            matches = any(abs(num - cell_val) <= epsilon for cell_val in numeric_cells)
            if not matches and numeric_cells:
                # Require at least one table type evidence; avoid false positive
                # on purely inferential text claims that mention a number.
                if any(item.type in {"table", "figure"} for item in bundle.evidence if item.evidence_id == eid):
                    return True, f"numeric value {num:g} in claim not present in table {eid}"
    return False, None


def validate_against_bundle(
    claim: Claim, bundle: EvidenceBundle
) -> tuple[Verdict | None, str | None]:
    """Deterministic gate. Returns a verdict (and detail) if one can be given without the LLM.

    - Empty claim text → UNSUPPORTED
    - Unknown evidence id → UNSUPPORTED (with missing aspect note)
    - Numeric contradiction → CONTRADICTED
    Otherwise → (None, None) meaning "let the LLM judge decide".
    """
    supply = {item.evidence_id for item in bundle.evidence}

    if not claim.text or not claim.text.strip():
        return "UNSUPPORTED", "claim text is empty"

    if not claim.evidence_ids:
        return "UNSUPPORTED", "claim has no evidence_ids"

    unknown = claim_has_unknown_evidence(claim, supply)
    if unknown:
        return "UNSUPPORTED", f"unknown evidence ids: {', '.join(unknown)}"

    # A citation to a table is not proof that the table contains the values
    # needed by a numerical/comparative claim.  This gate runs before the LLM
    # Judge so model confidence cannot promote caption-only evidence.
    if claim_requires_table_values(claim):
        for item in bundle.evidence:
            if item.evidence_id not in claim.evidence_ids or item.type != "table":
                continue
            if not table_evidence_supports_values(item):
                status = table_evidence_status(item)
                return (
                    "UNSUPPORTED",
                    f"table evidence {item.evidence_id} is {status}; "
                    "numerical/comparative claims require table values or explicit comparison evidence",
                )

    # Trusted structured table path: configured to be conservative (only a clear
    # numeric mismatch that spans authoritative cell evidence is a contradiction).
    contradicted, detail = maybe_contradicted_by_table(claim, bundle)
    if contradicted:
        return "CONTRADICTED", detail

    if claim_requires_table_values(claim):
        for item in bundle.evidence:
            if item.evidence_id in claim.evidence_ids and item.type == "table":
                if not table_evidence_supports_claim(item, claim):
                    return (
                        "UNSUPPORTED",
                        f"table evidence {item.evidence_id} has no row label or matching value for the comparative claim",
                    )

    return None, None
