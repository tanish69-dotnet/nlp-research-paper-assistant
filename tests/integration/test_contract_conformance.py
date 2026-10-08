"""Person 2 smoke / conformance harness.

A valid Person 2 payload (``EvidenceBundle`` exactly as described in
``docs/integration_person2.md``) must survive:

  received → validated → normalized → consumed by the MVP pipeline

without any change to the reasoning code path. Invalid payloads must fail
safely.
"""

from __future__ import annotations

import pytest

from app.schemas.evidence import EvidenceBundle

# A realistic, supplier-assigned Person 2 payload: the fixture itself.
FIXTURE_PATH = "tests/fixtures/mock_evidence.json"


def test_person2_payload_is_valid_evidence_bundle() -> None:
    import json
    raw = json.loads(open(FIXTURE_PATH, encoding="utf-8").read())
    bundle = EvidenceBundle.model_validate(raw)

    assert len(bundle.evidence) >= 1
    assert all(item.evidence_id for item in bundle.evidence)
    assert all(item.paper_id for item in bundle.evidence)
    # Images, when present, are relative to EVIDENCE_ROOT
    for item in bundle.evidence:
        if item.image and item.image.path:
            assert not item.image.path.startswith("/") and not item.image.path.startswith("\\")
            assert ".." not in item.image.path


def test_person2_payload_passes_budget_and_path_validation(make_settings: object, monkeypatch: object) -> None:
    import json
    from app.evidence.validation import validate_evidence

    raw = json.loads(open(FIXTURE_PATH, encoding="utf-8").read())
    bundle = EvidenceBundle.model_validate(raw)
    settings = make_settings()  # type: ignore[operator]

    # Mock fixture has no real image files — validation only checks *paths*;
    # existence is handled later by the VisionAgent.
    validate_evidence(bundle, settings)


def test_invalid_person2_payload_fails_safely() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EvidenceBundle.model_validate({"evidence": [{"evidence_id": "x", "paper_id": "p", "type": "unknown"}]})


def test_supplier_image_path_traversal_rejected() -> None:
    from pydantic import ValidationError  # noqa: F401 - we check EvidenceBundle here

    # Image path confinement is enforced through the validation layer (case path:
    # validate_evidence → ImagePathForbiddenError).
    import json
    from app.evidence.validation import validate_evidence, ImagePathForbiddenError as PathError

    raw = json.loads(open(FIXTURE_PATH, encoding="utf-8").read())
    raw["evidence"][0]["image"] = {"path": "../../etc/passwd"}
    bundle = EvidenceBundle.model_validate(raw)
    settings_obj = __import__("app.config", fromlist=["Settings"]).Settings(_env_file=None)

    with pytest.raises(PathError):
        validate_evidence(bundle, settings_obj)


def test_evidence_ids_survive_normalization(
    make_settings: object,
) -> None:
    """The pipeline must not synthesize new ids — citations reflect the supplied set."""
    import json
    from tests.conftest import run

    raw = json.loads(open(FIXTURE_PATH, encoding="utf-8").read())
    raw = json.loads(json.dumps(raw))
    # Inject inline b64 for the fixture figure so vision has usable input
    b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR4nGNgYGBgAAAABQABDQottQAAAABJRU5ErkJggg=="
    for item in raw["evidence"]:
        if item.get("type") == "figure":
            item["image"] = {"b64": b64, "mime": "image/png"}

    bundle = EvidenceBundle.model_validate(raw)
    from fastapi.testclient import TestClient

    settings = make_settings()  # type: ignore[operator]
    from app.main import create_app

    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/reason",
            json={"query": "What is the paper about?", "evidence": bundle.model_dump(mode="json")},
        )

        body = response.json()

        known = {item.evidence_id for item in bundle.evidence}
        if body.get("status") == "error":
            pytest.skip("provider failure — smoke harness does not mock here; the assertion here is for determinism: no new ids even when the pipeline is degraded")
        # In the unverified path, citations are empty by construction.
        if body.get("verification", {}).get("status") == "unverified":
            assert body.get("citations") == []
        for claim in body.get("claims", []):
            assert set(claim.get("evidence_ids", [])) <= known, claim
        for citation in body.get("citations", []):
            assert citation.get("evidence_id") in known