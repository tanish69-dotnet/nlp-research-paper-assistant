"""Offline contract-conformance suite — Person 2 ``schema.md`` §2 → our EvidenceBundle.

Feeds the verbatim shapes Person 2's ``src/app.py::RetrieveResponse(evidence=[EvidenceItem{...}])``
emits (also the shapes in ``schema.md §2``) through ``adapt_retrieval_response`` and
asserts: stable namespaced IDs, modality mapping, caption→reference, provenance,
and that image traversals remain rejected.
"""

from __future__ import annotations

from app.evidence.adapter import adapt_retrieval_response
from app.schemas.evidence import EvidenceBundle


# The verbatim example from Person 2's ``schema.md §2`` (one ranked EvidenceItem)
_SCHEMA_MD_SECTION2_PAYLOAD = {
    "evidence": [
        {
            "rank": 1,
            "score": 0.884,
            "paper_id": "arxiv_2308.12345",
            "element_id": "elem_002",
            "type": "table",
            "page": 7,
            "section": "5. Evaluation",
            "content": "| Model | BLEU (EN-DE) | BLEU (EN-FR) |\n|---|---|---|\n| Transformer (base) | 27.3 | 38.1 |",
            "caption": "Table 1: Maximum BLEU scores on translation tasks.",
            "context": "As shown in Table 1, our base model beats previous ensemble models.",
            "image_path": None,
        }
    ]
}

# The Pydantic envelope Person 2's ``src/app.py::RetrieveResponse`` produces
# (rank/score explicitly set, score nullable, page optional, image_path nullable)
_SRC_APP_RETRIEVE_SHAPE = {
    "evidence": [
        {
            "rank": 2,
            "score": 0.71,
            "paper_id": "arxiv_2308.12345",
            "element_id": "elem_003",
            "type": "figure",
            "page": 3,
            "section": "3. Model Architecture",
            "content": "",
            "caption": "Figure 1: The Transformer model architecture.",
            "context": "Figure 1 illustrates the multi-head self-attention mechanisms.",
            "image_path": "data/extracted/arxiv_2308.12345/fig1.png",
        }
    ]
}


def test_schema_md_section2_maps_to_evidence_bundle():
    bundle = adapt_retrieval_response(_SCHEMA_MD_SECTION2_PAYLOAD, paper_id_fallback="retrieved")
    assert isinstance(bundle, EvidenceBundle)
    assert len(bundle.evidence) == 1
    item = bundle.evidence[0]
    assert item.paper_id == "arxiv_2308.12345"
    assert item.type == "table"
    assert item.page == 7
    assert item.section == "5. Evaluation"
    assert "BLEU" in item.content
    assert item.caption == "Table 1: Maximum BLEU scores on translation tasks."
    assert item.score == 0.884


def test_schema_md_ids_are_namespaced_with_paper_id():
    bundle = adapt_retrieval_response(_SCHEMA_MD_SECTION2_PAYLOAD)
    assert bundle.evidence[0].evidence_id == "arxiv_2308.12345:elem_002"


def test_multipaper_element_id_collision_is_avoided():
    payload = {
        "evidence": [
            {"element_id": "elem_002", "type": "table", "paper_id": "paper_A", "content": "t", "caption": "Table 1"},
            {"element_id": "elem_002", "type": "table", "paper_id": "paper_B", "content": "t", "caption": "Table 1"},
        ]
    }
    bundle = adapt_retrieval_response(payload)
    ids = [item.evidence_id for item in bundle.evidence]
    assert len(ids) == len(set(ids))
    assert ids[0].startswith("paper_A:")
    assert ids[1].startswith("paper_B:")


def test_app_envelope_preserves_caption_and_provenance():
    bundle = adapt_retrieval_response(_SRC_APP_RETRIEVE_SHAPE)
    item = bundle.evidence[0]
    assert item.caption == "Figure 1: The Transformer model architecture."
    assert item.paper_id == "arxiv_2308.12345"
    assert item.type == "figure"
    assert item.metadata["retrieval_rank"] == 0


def test_figure_context_captured_in_content():
    bundle = adapt_retrieval_response(_SRC_APP_RETRIEVE_SHAPE)
    item = bundle.evidence[0]
    assert "Figure 1 illustrates" in item.content or "Figure 1: The Transformer" in item.content


def test_reference_derived_from_caption():
    table_bundle = adapt_retrieval_response(_SCHEMA_MD_SECTION2_PAYLOAD)
    assert table_bundle.evidence[0].reference == "Table 1"

    figure_bundle = adapt_retrieval_response(_SRC_APP_RETRIEVE_SHAPE)
    assert figure_bundle.evidence[0].reference == "Figure 1"

    # Malformed / ambiguous captions — nothing invented
    bundle = adapt_retrieval_response({"evidence": [{"type": "table", "caption": "A difficult example from QA", "paper_id": "p", "content": "hi"}]})
    assert bundle.evidence[0].reference is None or "Table" not in (bundle.evidence[0].reference or "")


def test_image_path_preserved_and_confined_on_validation():
    figure_bundle = adapt_retrieval_response(_SRC_APP_RETRIEVE_SHAPE)
    # Figure holds the path at adapter level (confinement is validated later via validate_evidence)
    assert figure_bundle.evidence[0].image is not None
    assert figure_bundle.evidence[0].image.path == "data/extracted/arxiv_2308.12345/fig1.png"

    # Traversal inside image_path is preserved through the adapter and rejected at validation
    payload = {"evidence": [{"type": "figure", "paper_id": "p", "caption": "Figure 1: X", "image_path": "../../etc/passwd"}]}
    bundle = adapt_retrieval_response(payload)
    assert bundle.evidence[0].image is not None
    from app.config import Settings
    from app.evidence.validation import validate_evidence
    from app.core.errors import ImagePathForbiddenError

    raised = False
    try:
        validate_evidence(bundle, Settings(_env_file=None))
    except ImagePathForbiddenError:
        raised = True
    assert raised


def test_cross_ref_provenance_round_trips():
    payload = {
        "evidence": [
            {"element_id": "elem_001", "type": "text", "paper_id": "p", "content": "see Table 1"},
            {"element_id": "elem_002", "type": "table", "paper_id": "p", "content": "| T |", "caption": "Table 1", "expanded_via_cross_ref": True, "cross_ref_trigger": "1"},
        ]
    }
    bundle = adapt_retrieval_response(payload)
    expanded = [item for item in bundle.evidence if item.evidence_id.endswith(":elem_002") or item.metadata.get("expanded_via_cross_ref")]
    assert len(expanded) == 1
    assert expanded[0].metadata["expanded_via_cross_ref"] is True
    assert expanded[0].metadata["cross_ref_trigger"] == "1"
