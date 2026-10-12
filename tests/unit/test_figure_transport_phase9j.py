"""Phase 9J — figure b64 transport + path-confinement + null page (NLP side).

Proves: (1) real Figure 1 PNG bytes survive adapter → ImageRef{b64};
(2) b64 images validate inside EVIDENCE_ROOT without filesystem reads;
(3) path transport outside EVIDENCE_ROOT stays FORBIDDEN;
(4) page stays null (never invented); (5) caption ≠ image evidence.
"""

from __future__ import annotations

import base64
from pathlib import Path

from app.config import Settings
from app.core.errors import ImagePathForbiddenError
from app.evidence.adapter import adapt_retrieval_record
from app.evidence.images import decode_and_validate_b64
from app.evidence.validation import resolve_image_path, validate_evidence
from app.schemas.evidence import EvidenceBundle

P2_FIG = Path("multimodal_rag_retrieval_person2/data/source_artifacts/figures/1611.04684v1/arch.png")
EXPECTED_PNG_SHA = "654de8a7235e979d2f686c49ae83f5b56303b5f436aa142f7c41179789d67477"


def _settings() -> Settings:
    return Settings(_env_file=None)


def test_restored_png_bytes_survive_b64_transport():
    import hashlib

    raw = P2_FIG.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_PNG_SHA
    b64 = base64.b64encode(raw).decode("ascii")
    rec = {
        "element_id": "elem_000",
        "type": "figure",
        "paper_id": "1611.04684v1",
        "caption": "Architecture of KEHNN",
        "image": {"b64": b64, "mime": "image/png"},
        "page": None,
    }
    item = adapt_retrieval_record(rec, "1611.04684v1", 0)
    assert item.evidence_id == "1611.04684v1:elem_000"
    assert item.image is not None and item.image.b64 is not None
    assert item.page is None
    # b64 validates without any filesystem read
    data, mime = decode_and_validate_b64(item.image.b64, _settings())
    assert mime == "image/png" and len(data) == len(raw)


def test_p2_relative_path_is_confined_not_silently_allowed():
    # P2's repo-relative path must NOT resolve inside our EVIDENCE_ROOT.
    settings = _settings()
    bundle = EvidenceBundle(
        evidence=[
            adapt_retrieval_record(
                {
                    "element_id": "elem_000",
                    "type": "figure",
                    "paper_id": "1611.04684v1",
                    "caption": "Architecture of KEHNN",
                    "image_path": "data/source_artifacts/figures/1611.04684v1/arch.png",
                },
                "1611.04684v1",
                0,
            )
        ]
    )
    raised = False
    try:
        validate_evidence(bundle, settings)
    except ImagePathForbiddenError:
        raised = True
    # Either forbidden (file absent under ./evidence) or resolved harmlessly
    # inside EVIDENCE_ROOT — never outside it.
    if not raised:
        resolved = resolve_image_path(
            "data/source_artifacts/figures/1611.04684v1/arch.png", settings
        )
        assert str(resolved).startswith(str(settings.evidence_root_path))


def test_traversal_absolute_and_unc_still_rejected():
    settings = _settings()
    for hostile in ("../../etc/passwd", "C:\\Windows\\win.ini", "//server/share/x.png"):
        raised = False
        try:
            resolve_image_path(hostile, settings)
        except ImagePathForbiddenError:
            raised = True
        assert raised, hostile


def test_null_page_never_invented():
    rec = {
        "element_id": "elem_000",
        "type": "figure",
        "paper_id": "1611.04684v1",
        "caption": "Architecture of KEHNN",
    }
    item = adapt_retrieval_record(rec, "1611.04684v1", 0)
    assert item.page is None


def test_caption_is_not_image_evidence():
    rec = {
        "element_id": "elem_000",
        "type": "figure",
        "paper_id": "1611.04684v1",
        "caption": "Architecture of KEHNN",
    }
    item = adapt_retrieval_record(rec, "1611.04684v1", 0)
    assert item.image is None
    assert item.caption == "Architecture of KEHNN"


def test_p2_image_b64_alias_maps_to_imageref():
    """Phase 9N: P2 ``image_b64``/``image_mime`` keys map to ImageRef{b64}."""
    from app.evidence.adapter import adapt_retrieval_record
    from app.evidence.images import decode_and_validate_b64
    from app.config import Settings

    rec = {
        "element_id": "elem_000",
        "type": "figure",
        "paper_id": "1611.04684v1",
        "caption": "Figure 1: Architecture",
        "image_b64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR4nGNgYGBgAAAABQABDQottQAAAABJRU5ErkJggg==",
        "image_mime": "image/png",
        "page": None,
    }
    item = adapt_retrieval_record(rec, "1611.04684v1", 0)
    assert item.image is not None and item.image.b64 is not None
    assert item.page is None
    data, mime = decode_and_validate_b64(
        item.image.b64, Settings(_env_file=None)
    )
    assert mime == "image/png" and len(data) > 0


def test_p2_image_path_still_maps_when_no_b64():
    from app.evidence.adapter import adapt_retrieval_record

    rec = {
        "element_id": "elem_001",
        "type": "figure",
        "paper_id": "p",
        "caption": "Figure 1: X",
        "image_path": "paper_001/fig1.png",
    }
    item = adapt_retrieval_record(rec, "p", 0)
    assert item.image is not None and item.image.path == "paper_001/fig1.png"
