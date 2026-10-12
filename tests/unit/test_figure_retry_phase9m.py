"""Phase 9M — one bounded figure-scoped retrieval retry.

Covers: successful scoped retrieval replacing an imageless bundle, no retry
without an explicit Figure N mention, no retry without a paper id, retry
results for another paper discarded, caption-only retry results discarded,
transport failures keeping the original bundle.
"""

from __future__ import annotations

import pytest

from app.evidence.adapter import adapt_retrieval_record
from app.evidence.figures import figure_references_in_query, maybe_scoped_figure_retry
from app.evidence.retrieval_client import MockRetrievalProvider
from app.schemas.evidence import EvidenceBundle, EvidenceItem
from tests.conftest import run


def _figure_item(evidence_id: str, paper_id: str, *, with_image: bool) -> EvidenceItem:
    from app.schemas.evidence import ImageRef

    image = ImageRef(b64="iVBORw0KGgo=") if with_image else None
    return EvidenceItem(
        evidence_id=evidence_id,
        paper_id=paper_id,
        type="figure",
        content="",
        caption="Figure 1: Architecture",
        image=image,
    )


def _text_item(evidence_id: str, paper_id: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        paper_id=paper_id,
        type="text",
        content="Figure 1 gives the architecture of our model.",
    )


def test_reference_extraction():
    assert figure_references_in_query("Look at Figure 1 and describe it.") == ["Figure 1"]
    assert figure_references_in_query("See fig. 2 for details.") == ["Figure 2"]
    assert figure_references_in_query("What is overfitting?") == []


def test_successful_retry_replaces_imageless_bundle():
    bundle = EvidenceBundle(
        evidence=[_figure_item("1611.04684v1:elem_000", "1611.04684v1", with_image=False)]
    )
    provider = MockRetrievalProvider(
        responses=[
            (
                "Look at Figure 1 of paper 1611.04684v1",
                {
                    "evidence": [
                        {
                            "element_id": "elem_000",
                            "type": "figure",
                            "paper_id": "1611.04684v1",
                            "caption": "Figure 1: Architecture",
                            "image": {"b64": "iVBORw0KGgo="},
                        }
                    ]
                },
            )
        ]
    )

    out = run(
        maybe_scoped_figure_retry(
            provider,
            "Look at Figure 1 of paper 1611.04684v1 and describe it.",
            bundle,
            top_k=5,
            timeout_s=5.0,
        )
    )

    assert out is not bundle
    assert any(item.image is not None and item.image.b64 for item in out.evidence if item.type == "figure")


def test_no_retry_without_figure_mention():
    bundle = EvidenceBundle(evidence=[_text_item("e_t", "paper_001")])
    provider = MockRetrievalProvider()

    out = run(
        maybe_scoped_figure_retry(
            provider, "What is overfitting?", bundle, top_k=5, timeout_s=5.0
        )
    )

    assert out is bundle
    assert provider._call_count == 0


def test_no_retry_without_paper_id():
    bundle = EvidenceBundle(
        evidence=[_figure_item("paper_001:elem_000", "paper_001", with_image=False)]
    )
    provider = MockRetrievalProvider()

    out = run(
        maybe_scoped_figure_retry(
            provider, "Look at Figure 1 and describe it.", bundle, top_k=5, timeout_s=5.0
        )
    )

    assert out is bundle
    assert provider._call_count == 0


def test_retry_result_for_another_paper_is_discarded():
    bundle = EvidenceBundle(
        evidence=[_figure_item("paper_001:elem_000", "paper_001", with_image=False)]
    )
    from app.evidence.adapter import adapt_retrieval_response

    provider = MockRetrievalProvider(
        responses=[
            (
                "Figure 1",
                {
                    "evidence": [
                        {
                            "element_id": "elem_999",
                            "type": "figure",
                            "paper_id": "paper_002",
                            "caption": "Figure 1: Other",
                            "image": {"b64": "iVBORw0KGgo="},
                        }
                    ]
                },
            )
        ]
    )

    out = run(
        maybe_scoped_figure_retry(
            provider,
            "Look at Figure 1 of paper 1611.04684v1.",
            bundle,
            top_k=5,
            timeout_s=5.0,
        )
    )

    assert out is bundle


def test_caption_only_retry_result_is_discarded():
    bundle = EvidenceBundle(
        evidence=[_figure_item("paper_001:elem_000", "paper_001", with_image=False)]
    )
    provider = MockRetrievalProvider(
        responses=[
            (
                "Figure 1",
                {
                    "evidence": [
                        {
                            "element_id": "elem_000",
                            "type": "figure",
                            "paper_id": "paper_001",
                            "caption": "Figure 1: Architecture",
                        }
                    ]
                },
            )
        ]
    )

    out = run(
        maybe_scoped_figure_retry(
            provider,
            "Look at Figure 1 of paper 1611.04684v1.",
            bundle,
            top_k=5,
            timeout_s=5.0,
        )
    )

    assert out is bundle


def test_transport_failure_keeps_original_bundle():
    from app.core.errors import ModelUnavailableError

    bundle = EvidenceBundle(
        evidence=[_figure_item("paper_001:elem_000", "paper_001", with_image=False)]
    )

    class FailingProvider(MockRetrievalProvider):
        async def retrieve(self, request):  # type: ignore[override]
            raise ModelUnavailableError("down")

    out = run(
        maybe_scoped_figure_retry(
            FailingProvider(),
            "Look at Figure 1 of paper 1611.04684v1.",
            bundle,
            top_k=5,
            timeout_s=5.0,
        )
    )

    assert out is bundle


def test_no_retry_when_usable_figure_already_present():
    bundle = EvidenceBundle(
        evidence=[_figure_item("1611.04684v1:elem_000", "1611.04684v1", with_image=True)]
    )
    provider = MockRetrievalProvider()

    out = run(
        maybe_scoped_figure_retry(
            provider,
            "Look at Figure 1 of paper 1611.04684v1.",
            bundle,
            top_k=5,
            timeout_s=5.0,
        )
    )

    assert out is bundle
    assert provider._call_count == 0
