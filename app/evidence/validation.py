"""Evidence validation — schema-level safety and budget rules (SECURITY.md §4).

This layer runs before any model call. It enforces:

- size budgets (item count, per-item and total characters),
- image path confinement to ``EVIDENCE_ROOT`` (no traversal, no absolute paths),
- presence of evidence (``EVIDENCE_EMPTY``).

Structural rules (id charset, uniqueness, char_span sanity) live on the schemas
themselves so they fail at parse time.
"""

from __future__ import annotations

from pathlib import Path, PureWindowsPath

from app.config import Settings
from app.core.errors import (
    EvidenceEmptyError,
    EvidenceInvalidError,
    ImagePathForbiddenError,
    PayloadTooLargeError,
)
from app.schemas.evidence import EvidenceBundle, EvidenceItem


def validate_evidence_size(bundle: EvidenceBundle, settings: Settings) -> None:
    """Enforce configured evidence budgets (raises ``PayloadTooLargeError``).

    Note: the per-item cap is applied to the *retrieved* text so a single
    hostile or bloated chunk cannot blow up a prompt (SECURITY.md §4).
    """
    if not bundle.evidence:
        raise EvidenceEmptyError("evidence list is empty; nothing to reason over")

    if len(bundle.evidence) > settings.max_evidence_items:
        raise PayloadTooLargeError(
            f"evidence has {len(bundle.evidence)} items; "
            f"max_evidence_items={settings.max_evidence_items}"
        )

    total = 0
    for item in bundle.evidence:
        length = item.text_length
        if length > settings.max_evidence_item_chars:
            raise PayloadTooLargeError(
                f"evidence item '{item.evidence_id}' has {length} chars; "
                f"max_evidence_item_chars={settings.max_evidence_item_chars}"
            )
        total += length

    if total > settings.max_evidence_chars:
        raise PayloadTooLargeError(
            f"evidence totals {total} chars; max_evidence_chars={settings.max_evidence_chars}"
        )


def resolve_image_path(raw_path: str, settings: Settings) -> Path:
    """Confine an evidence image path to ``EVIDENCE_ROOT``.

    Rejects: empty paths, absolute paths (POSIX/Windows/UNC), and any path
    whose *resolved* location escapes the evidence root — including ``..``
    traversal and symlink escapes (SECURITY.md §4).
    """
    if not raw_path or not raw_path.strip():
        raise ImagePathForbiddenError("image path is empty")

    path = raw_path.strip().replace("\\", "/")

    # Absolute / drive / UNC forms are refused before any filesystem access.
    if path.startswith("/") or path.startswith("//"):
        raise ImagePathForbiddenError(f"absolute image path forbidden: {raw_path}")
    pure = PureWindowsPath(path)
    if pure.is_absolute() or pure.drive or pure.root:
        raise ImagePathForbiddenError(f"absolute image path forbidden: {raw_path}")

    root = settings.evidence_root_path
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root):
        raise ImagePathForbiddenError(
            f"image path escapes EVIDENCE_ROOT: {raw_path}"
        )
    return candidate


def validate_evidence_images(bundle: EvidenceBundle, settings: Settings) -> dict[str, Path]:
    """Return ``evidence_id -> resolved absolute path`` for path-based images.

    Existence is *not* checked here: image files may be produced later by the
    ingestion pipeline, and the vision agent reports ``no_evidence`` when a
    file is absent (ARCHITECTURE §4.4). Only path safety is a Phase 1 concern.
    """
    resolved: dict[str, Path] = {}
    for item in bundle.evidence:
        image = item.image
        if image is None or image.path is None:
            continue
        resolved[item.evidence_id] = resolve_image_path(image.path, settings)
    return resolved


def validate_evidence(bundle: EvidenceBundle, settings: Settings) -> None:
    """Full Phase 1 evidence gate: budget + path safety.

    Raises :class:`ReasoningError` subclasses that map to stable API error
    codes (API_SPEC §6).
    """
    validate_evidence_size(bundle, settings)
    validate_evidence_images(bundle, settings)


def referenced_evidence_ids(items: list[EvidenceItem]) -> list[str]:
    """Stable, de-duplicated evidence ids preserving input order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item.evidence_id not in seen:
            seen.add(item.evidence_id)
            ordered.append(item.evidence_id)
    return ordered
