"""Evidence validation tests — path confinement and budgets (SECURITY.md §4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import (
    EvidenceEmptyError,
    ImagePathForbiddenError,
    PayloadTooLargeError,
)
from app.evidence.validation import (
    resolve_image_path,
    validate_evidence,
    validate_evidence_images,
    validate_evidence_size,
)
from app.schemas.evidence import EvidenceBundle, EvidenceItem, ImageRef
from tests.conftest import load_mock_evidence


def _item(evidence_id: str = "e_1", *, content: str = "hello", **overrides: object) -> EvidenceItem:
    payload = {
        "evidence_id": evidence_id,
        "paper_id": "paper_001",
        "type": "text",
        "content": content,
    }
    payload.update(overrides)  # type: ignore[arg-type]
    return EvidenceItem(**payload)  # type: ignore[arg-type]


def _bundle(*items: EvidenceItem) -> EvidenceBundle:
    return EvidenceBundle(evidence=list(items))


# --- budgets -----------------------------------------------------------------


def test_empty_evidence_is_rejected(make_settings: object) -> None:
    settings = make_settings()  # type: ignore[operator]

    with pytest.raises(EvidenceEmptyError):
        validate_evidence_size(_bundle(), settings)


def test_too_many_items_rejected(make_settings: object) -> None:
    settings = make_settings(max_evidence_items=3)  # type: ignore[operator]
    bundle = _bundle(*(_item(f"e_{i}") for i in range(5)))

    with pytest.raises(PayloadTooLargeError, match="max_evidence_items"):
        validate_evidence_size(bundle, settings)


def test_oversized_single_item_rejected(make_settings: object) -> None:
    settings = make_settings(max_evidence_item_chars=100)  # type: ignore[operator]
    bundle = _bundle(_item("e_big", content="x" * 200))

    with pytest.raises(PayloadTooLargeError, match="max_evidence_item_chars"):
        validate_evidence_size(bundle, settings)


def test_total_budget_rejected(make_settings: object) -> None:
    settings = make_settings(  # type: ignore[operator]
        max_evidence_items=100,
        max_evidence_item_chars=1_000,
        max_evidence_chars=2_000,
    )
    bundle = _bundle(*(_item(f"e_{i}", content="y" * 900) for i in range(5)))

    with pytest.raises(PayloadTooLargeError, match="max_evidence_chars"):
        validate_evidence_size(bundle, settings)


def test_within_budget_passes(make_settings: object) -> None:
    settings = make_settings()  # type: ignore[operator]

    validate_evidence_size(
        _bundle(_item("e_1"), _item("e_2", content="world")), settings
    )


def test_caption_counts_toward_item_budget(make_settings: object) -> None:
    settings = make_settings(max_evidence_item_chars=150)  # type: ignore[operator]
    bundle = _bundle(_item("e_1", content="x" * 30, caption="c" * 125))

    with pytest.raises(PayloadTooLargeError):
        validate_evidence_size(bundle, settings)


# --- image path confinement --------------------------------------------------


def test_relative_path_inside_root_is_accepted(
    make_settings: object, tmp_path: Path
) -> None:
    settings = make_settings(evidence_root=str(tmp_path))  # type: ignore[operator]

    resolved = resolve_image_path("paper_001/p7_table3.png", settings)

    assert resolved == (tmp_path / "paper_001" / "p7_table3.png").resolve()


@pytest.mark.parametrize(
    "hostile",
    [
        "../../etc/passwd",
        "..\\..\\windows\\system32\\config\\sam",
        "paper/../../outside.png",
        "/etc/passwd",
        "C:\\Windows\\win.ini",
        "D:/secret.png",
        "\\\\server\\share\\img.png",
        "",
        "   ",
    ],
)
def test_traversal_and_absolute_paths_are_forbidden(
    make_settings: object, tmp_path: Path, hostile: str
) -> None:
    settings = make_settings(evidence_root=str(tmp_path))  # type: ignore[operator]

    with pytest.raises(ImagePathForbiddenError):
        resolve_image_path(hostile, settings)


def test_traversal_hidden_in_deeply_nested_path(
    make_settings: object, tmp_path: Path
) -> None:
    """``a/b/../../../../x`` escapes even though it *starts* legitimately."""
    settings = make_settings(evidence_root=str(tmp_path))  # type: ignore[operator]

    with pytest.raises(ImagePathForbiddenError):
        resolve_image_path("a/b/../../../../outside.png", settings)


def test_validate_evidence_images_returns_resolved_paths(
    make_settings: object, tmp_path: Path
) -> None:
    settings = make_settings(evidence_root=str(tmp_path))  # type: ignore[operator]
    bundle = EvidenceBundle(
        evidence=[
            _item(
                "e_img",
                type="table",
                image=ImageRef(path="paper_001/p7.png"),
            ),
            _item("e_txt"),  # no image
            _item("e_b64", image=ImageRef(b64="QUJD")),  # base64 transport
        ]
    )

    resolved = validate_evidence_images(bundle, settings)

    assert set(resolved) == {"e_img"}
    assert resolved["e_img"].is_absolute()


def test_validate_evidence_rejects_hostile_image_path(
    make_settings: object, tmp_path: Path
) -> None:
    settings = make_settings(evidence_root=str(tmp_path))  # type: ignore[operator]
    bundle = _bundle(
        _item("e_img", type="figure", image=ImageRef(path="../../../evil.png"))
    )

    with pytest.raises(ImagePathForbiddenError):
        validate_evidence(bundle, settings)


def test_fixture_bundle_passes_full_validation(make_settings: object) -> None:
    settings = make_settings()  # type: ignore[operator]
    bundle = EvidenceBundle.model_validate(load_mock_evidence())

    validate_evidence(bundle, settings)  # must not raise
    assert len(bundle.evidence) == 7