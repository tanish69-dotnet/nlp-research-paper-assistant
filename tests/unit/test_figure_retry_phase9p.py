"""Phase 9P — widened figure retry: explicit refs + semantic intent + paper_ids.

Deterministic, offline (MockRetrievalProvider). Covers the eight required
cases without touching retrieval ranking or validation.
"""

from __future__ import annotations

from app.evidence.figures import has_figure_intent, maybe_scoped_figure_retry
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


def _text_item(evidence_id: str, paper_id: str, content: str = "Some prose.") -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        paper_id=paper_id,
        type="text",
        content=content,
    )


def _usable_figure_response() -> dict:
    return {
        "evidence": [
            {
                "element_id": "elem_000",
                "type": "figure",
                "paper_id": "1611.04684v1",
                "caption": "Figure 1: Architecture",
                "image": {"b64": "iVBORw0KGgo="},
            }
        ]
    }


# 1. Explicit Figure N + paper id ----------------------------------------------


def test_explicit_reference_with_paper_id_retries():
    bundle = EvidenceBundle(
        evidence=[_figure_item("1611.04684v1:elem_000", "1611.04684v1", with_image=False)]
    )
    provider = MockRetrievalProvider(
        responses=[("1611.04684v1", _usable_figure_response())]
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
    assert provider._call_count == 1


# 2. Semantic wording + explicit paper_ids -------------------------------------


def test_semantic_wording_with_explicit_paper_ids_retries():
    bundle = EvidenceBundle(
        evidence=[_figure_item("1611.04684v1:elem_000", "1611.04684v1", with_image=False)]
    )
    provider = MockRetrievalProvider(
        responses=[("architecture diagram", _usable_figure_response())]
    )

    out = run(
        maybe_scoped_figure_retry(
            provider,
            "Describe the architecture diagram and its data flow.",
            bundle,
            top_k=5,
            timeout_s=5.0,
            paper_ids=("1611.04684v1",),
        )
    )

    assert out is not bundle
    assert has_figure_intent("Describe the architecture diagram and its data flow.")


# 3. Semantic wording + inferable arXiv id --------------------------------------


def test_semantic_wording_with_inferable_arxiv_id_retries():
    bundle = EvidenceBundle(
        evidence=[_figure_item("1611.04684v1:elem_000", "1611.04684v1", with_image=False)]
    )
    provider = MockRetrievalProvider(
        responses=[("1611.04684v1", _usable_figure_response())]
    )

    out = run(
        maybe_scoped_figure_retry(
            provider,
            "Describe the architecture diagram of 1611.04684v1.",
            bundle,
            top_k=5,
            timeout_s=5.0,
        )
    )

    assert out is not bundle


# 4. Generic wording without a paper never retries -------------------------------


def test_generic_wording_without_paper_never_retries():
    bundle = EvidenceBundle(
        evidence=[_figure_item("1611.04684v1:elem_000", "1611.04684v1", with_image=False)]
    )
    provider = MockRetrievalProvider()

    out = run(
        maybe_scoped_figure_retry(
            provider, "Describe Figure 1.", bundle, top_k=5, timeout_s=5.0
        )
    )

    assert out is bundle
    assert provider._call_count == 0


# 5. Other-paper-only retry results are discarded ---------------------------------


def test_other_paper_retry_results_discarded():
    bundle = EvidenceBundle(
        evidence=[_figure_item("1611.04684v1:elem_000", "1611.04684v1", with_image=False)]
    )
    provider = MockRetrievalProvider(
        responses=[
            (
                "1611.04684v1",
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


# 6. Caption-only retry results are discarded --------------------------------------


def test_caption_only_retry_results_discarded():
    bundle = EvidenceBundle(
        evidence=[_figure_item("1611.04684v1:elem_000", "1611.04684v1", with_image=False)]
    )
    provider = MockRetrievalProvider(
        responses=[
            (
                "1611.04684v1",
                {
                    "evidence": [
                        {
                            "element_id": "elem_000",
                            "type": "figure",
                            "paper_id": "1611.04684v1",
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


# 7. Failed retry / missing bytes keeps the original bundle -------------------------


def test_failed_retry_keeps_original_bundle():
    from app.core.errors import ModelUnavailableError

    bundle = EvidenceBundle(
        evidence=[_figure_item("1611.04684v1:elem_000", "1611.04684v1", with_image=False)]
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


# 8. Text/table questions never retry -----------------------------------------------


def test_text_table_questions_never_retry():
    for query in [
        "What is overfitting?",
        "Which method performed best in Table 3?",
        "Compare the F1 scores across methods.",
    ]:
        bundle = EvidenceBundle(evidence=[_text_item("e_t", "paper_001")])
        provider = MockRetrievalProvider()

        out = run(
            maybe_scoped_figure_retry(
                provider, query, bundle, top_k=5, timeout_s=5.0,
                paper_ids=("1611.04684v1",),
            )
        )

        assert out is bundle
        assert provider._call_count == 0


def test_retry_query_preserves_intent_without_architecture_terms():
    """The scoped query keeps the user's wording; no injected architecture terms."""
    from app.evidence.figures import _scoped_query

    scoped = _scoped_query(
        "How does the performance curve evolve with context length?",
        "1611.04684v1",
        [],
    )

    assert "How does the performance curve evolve with context length?" in scoped
    # Paper scoping travels via paper_ids, not query text (measured: id
    # prefixes degrade dense ranking). No architecture terms injected.
    assert "architecture diagram components data flow" not in scoped
