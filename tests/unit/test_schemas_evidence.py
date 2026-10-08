"""Evidence contract tests (API_SPEC §4 — Person 2 boundary)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.evidence import EvidenceBundle, EvidenceItem, ImageRef
from tests.conftest import load_mock_evidence


def test_fixture_bundle_validates() -> None:
    bundle = EvidenceBundle.model_validate(load_mock_evidence())

    assert len(bundle.evidence) == 7
    assert {paper.paper_id for paper in bundle.papers} == {"paper_001", "paper_002"}
    assert len({item.evidence_id for item in bundle.evidence}) == 7
    assert bundle.retrieval is not None and bundle.retrieval.retriever


def test_fixture_covers_all_modalities() -> None:
    bundle = EvidenceBundle.model_validate(load_mock_evidence())
    types = {item.type for item in bundle.evidence}

    assert {"text", "table", "figure"} <= types


def test_missing_required_field_is_rejected() -> None:
    payload = load_mock_evidence()
    del payload["evidence"][0]["evidence_id"]

    with pytest.raises(ValidationError):
        EvidenceBundle.model_validate(payload)


def test_unknown_field_is_rejected() -> None:
    payload = load_mock_evidence()
    payload["evidence"][0]["surprise_field"] = "nope"

    with pytest.raises(ValidationError):
        EvidenceBundle.model_validate(payload)


def test_invalid_evidence_type_is_rejected() -> None:
    payload = load_mock_evidence()
    payload["evidence"][0]["type"] = "chart"

    with pytest.raises(ValidationError):
        EvidenceBundle.model_validate(payload)


def test_duplicate_evidence_id_is_rejected() -> None:
    payload = load_mock_evidence()
    payload["evidence"][1]["evidence_id"] = payload["evidence"][0]["evidence_id"]

    with pytest.raises(ValidationError, match="duplicate evidence_id"):
        EvidenceBundle.model_validate(payload)


def test_evidence_id_charset_is_enforced() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem(
            evidence_id="bad id with spaces!",
            paper_id="paper_001",
            type="text",
            content="hello",
        )


def test_reversed_char_span_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem(
            evidence_id="e_ok",
            paper_id="paper_001",
            type="text",
            content="hello",
            char_span=(10, 3),
        )


def test_image_requires_exactly_one_transport() -> None:
    with pytest.raises(ValidationError):
        ImageRef(path="a/b.png", b64="AAAA")  # both
    with pytest.raises(ValidationError):
        ImageRef()  # neither


def test_image_fixture_entries_use_relative_paths() -> None:
    bundle = EvidenceBundle.model_validate(load_mock_evidence())
    paths = [
        item.image.path
        for item in bundle.evidence
        if item.image is not None and item.image.path is not None
    ]

    assert paths
    assert all(not path.startswith(("/", "\\")) for path in paths)


def test_score_out_of_range_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem(
            evidence_id="e_ok",
            paper_id="paper_001",
            type="text",
            content="x",
            score=1.5,
        )


def test_paper_identity_is_preserved_per_item() -> None:
    bundle = EvidenceBundle.model_validate(load_mock_evidence())

    for item in bundle.evidence:
        assert item.paper_id in {"paper_001", "paper_002"}
    table_ids = {
        item.paper_id for item in bundle.evidence if item.type == "table"
    }
    assert table_ids == {"paper_001", "paper_002"}
