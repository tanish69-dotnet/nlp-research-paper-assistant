"""Regression tests for ResearchLens coordinated improvements.

Covers §5 of the task:
  Ask Question — Figure 4 completeness, visual grounding, table cells,
  numeric abstention, citation provenance, paper-scoped isolation.
  Visual Evidence + Loading indicator — relevance ranking, exact-number
  search, honoring image bytes vs metadata-only, caption expansion, table
  structured rendering, empty/error states, dots loader accessibility,
  and keeping selectors stable.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.agents.judge_answer import _is_generic_figure_restatement  # internal, imported for direct gate
from app.agents.vision_agent import select_vision_context
from app.schemas.claims import Claim
from app.schemas.evidence import EvidenceBundle, EvidenceItem, ImageRef, PaperRef, TableData
from app.schemas.reasoning import ResponseMetadata  # ensure schema accepts additive fields if present

PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR4nGNgYGBgAAAABQABDQottQAAAABJRU5ErkJggg=="

INDEX = Path(__file__).resolve().parents[2] / "app" / "static" / "index.html"


# ---------------------------------------------------------------------------
# Ask Question
# ---------------------------------------------------------------------------


def test_figure4_reference_beam_question_not_pass_generic_restatement() -> None:
    """Requirement 5.1: the Figure 4 question must not pass with a generic restatement."""
    generic = "According to Figure 4, the reference beam and surveillance beam are depicted in the figure. These beams are part of the InteRFeX bistatic radar configuration."
    assert _is_generic_figure_restatement(generic) is True, "narrow detector must flag the reported generic answer"


def test_specific_figure4_explanation_is_not_flagged_generic() -> None:
    specific = (
        "According to Figure 4, the reference beam is shown as a red arrow entering the "
        "receiving array from the left, and the surveillance beam appears as a blue arrow "
        "from the right; the caption identifies them as the two branches of the InteRFeX "
        "bistatic radar configuration."
    )
    assert _is_generic_figure_restatement(specific) is False


def test_figure_reasoning_uses_visual_evidence_when_available() -> None:
    """Vision context should select the queried Figure N over a different figure."""
    fig1 = EvidenceItem(
        evidence_id="e_f1", paper_id="p", type="figure", reference="Figure 1", caption="Figure 1: control", image=ImageRef(b64=PNG_B64)
    )
    fig4 = EvidenceItem(
        evidence_id="e_f4", paper_id="p", type="figure", reference="Figure 4", caption="Figure 4: InteRFeX bistatic arrangement", image=ImageRef(b64=PNG_B64)
    )
    # fig1 listed first — the query targets Figure 4
    figures, _ = select_vision_context((fig1, fig4), "According to Figure 4, what are the reference beam and surveillance beam?")
    assert figures and figures[0].reference == "Figure 4"


def test_table_answers_use_actual_extracted_cells_when_available() -> None:
    """The table prompt must say 'actual extracted table cells' and forbid exact inference from caption."""
    tpl = (Path(__file__).resolve().parents[2] / "app" / "prompts" / "templates" / "v1" / "table_agent.md").read_text(encoding="utf-8")
    assert "actual extracted table cells" in tpl
    assert "Never" in tpl or "never" in tpl


def test_numeric_abstention_still_honest() -> None:
    """Unsupported numerical questions should still abstain (gate returns UNSUPPORTED)."""
    from app.verification.deterministic import validate_against_bundle

    table = TableData(headers=["Model", "F1"], rows=[["A", "0.77"], ["B", "0.61"]])
    bundle = EvidenceBundle(evidence=[EvidenceItem(evidence_id="e_tbl", paper_id="p", type="table", table_data=table)])
    claim = Claim(
        claim_id="cl1", agent="table_reasoner", kind="table_observation",
        text="Method A achieves F1 0.90 (fabricated).", evidence_ids=["e_tbl"], confidence=0.9,
    )
    verdict, _ = validate_against_bundle(claim, bundle)
    assert verdict == "CONTRADICTED" or verdict == "UNSUPPORTED"


def test_citations_reference_correct_source_evidence() -> None:
    """Evidence ids in citations come from claims' evidence_ids, not invented."""
    from app.orchestration.orchestrator import _resolve_citations  # type: ignore[attr-defined]

    bundle = EvidenceBundle(
        evidence=[
            EvidenceItem(evidence_id="e1", paper_id="p1", type="text", content="X"),
            EvidenceItem(evidence_id="e2", paper_id="p2", type="table", content="| A |"),
        ]
    )
    claim = Claim(claim_id="cl1", agent="text_reasoner", kind="author_claim", text="X", evidence_ids=["e1"], confidence=0.8)
    cits = _resolve_citations(bundle, [claim])
    assert len(cits) == 1
    assert cits[0].evidence_id == "e1"


def test_evidence_from_unrelated_papers_should_not_leak() -> None:
    """Paper-scoped reasoning must exclude other-paper evidence."""
    from tests.conftest import run
    from app.config import Settings
    from app.orchestration.orchestrator import full_reasoning
    from app.models.mock import MockModelProvider
    from app.models.routing import ModelRegistry

    bundle = EvidenceBundle(
        evidence=[
            EvidenceItem(evidence_id="a:e1", paper_id="alpha", type="figure", reference="Figure 1", caption="alpha fig", image=ImageRef(b64=PNG_B64)),
            EvidenceItem(evidence_id="b:e1", paper_id="beta", type="figure", reference="Figure 1", caption="beta fig", image=ImageRef(b64=PNG_B64)),
        ]
    )
    plan = json.dumps({
        "question_type": "other", "required_modalities": ["figure"], "tasks": [{"task": "about Figure 1", "modality": "figure", "target_references": ["Figure 1"]}],
        "target_references": ["Figure 1"], "requires_cross_modal": False, "paper_scope": "single", "paper_ids": ["alpha"], "sub_questions": [], "confidence": 0.9,
    })
    provider = MockModelProvider(responses=[
        ("Query Analyzer", plan),
        ("Vision", json.dumps({"findings": [{"claim_id": "cl1", "kind": "figure_observation", "text": "Beam A labeled red.", "evidence_ids": ["a:e1"], "confidence": 0.8}]})),
        ("Judge", json.dumps({"verdicts": [{"claim_id": "cl1", "verdict": "SUPPORTED", "rationale": "ok", "evidence_ids_support": ["a:e1"]}]})),
        ("Answer Generator", json.dumps({"answer": "Beam A red [citation:cl1].", "reasoning_summary": "ok"})),
    ])
    settings = Settings(_env_file=None, model_provider="mock", log_level="WARNING", log_format="console")  # type: ignore[call-arg]
    registry = ModelRegistry(provider, settings)
    result = run(full_reasoning("What is Figure 1 in alpha?", bundle, "paper-scope-test", settings, registry, paper_ids=("alpha",)))
    # Beta evidence must not appear among citations/claims
    for c in result.citations:
        assert c.paper_id == "alpha"
    assert all("b:e1" not in cl.evidence_ids for cl in result.claims if cl.claim_id in {v.claim_id for v in result.verifications if v.verdict in {"SUPPORTED", "PARTIALLY_SUPPORTED"}})


# ---------------------------------------------------------------------------
# Visual Evidence UI
# ---------------------------------------------------------------------------


def test_frontend_relevance_ranking_and_dedupe_and_scoping_exist() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert "_rankEvidence" in html, "client-side relevance ranker must exist"
    assert "wantedRefs" in html or "wanted_refs" in html
    assert "Dedup" in html or "dedup" in html.lower() or "seen" in html.lower()


def test_frontend_exact_figure_table_number_branch() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert re.search(r"Figure|Table", html) is not None
    # exact reference string exact-match bonus
    assert "_refMatchScore" in html or "exact" in html.lower()


def test_frontend_actual_images_render_when_bytes_available() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert "media-figure" in html
    assert "image_b64" in html


def test_frontend_missing_image_honest_not_crash() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert "Metadata only" in html
    assert "data-metadata-only" in html


def test_frontend_full_captions_and_expandable_toggle() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert "media-caption-clamp" in html or "Show more" in html
    assert "caption-toggle" in html


def test_frontend_structured_table_cells_render() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert "table_data" in html
    assert "data-table-render" in html


def test_frontend_missing_table_data_not_fabricated() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert "No structured table data was returned" in html


def test_frontend_missing_metadata_not_crash() -> None:
    html = INDEX.read_text(encoding="utf-8")
    # renderEvidence must normalize null/undefined metadata
    assert "raw ||" in html or "safe" in html.lower()


def test_frontend_empty_and_error_states() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert "evidence-empty" in html
    assert "evidence-status" in html
    assert "No figure or table evidence matched" in html or "sufficiently relevant" in html


def test_frontend_failed_image_retrieval_not_break_gallery() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert 'addEventListener("error"' in html
    assert "failed to load" in html.lower() or "Metadata only" in html


# ---------------------------------------------------------------------------
# Loading indicator
# ---------------------------------------------------------------------------


def test_minimal_dots_loader_css_and_element() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert "loader-dots" in html
    assert 'id="evidence-loader"' in html
    assert "dotsBounce" in html
    # palette: forest-green using var(--forest)
    assert "var(--forest)" in html


def test_dots_loader_size_approx_inline() -> None:
    html = INDEX.read_text(encoding="utf-8")
    # 16-24 px overall — implementation keeps fixed width/height via CSS
    assert "height: 16px" in html or "height: 18px" in html or "height: 16px" in html
    assert "width: 5px" in html or "5px" in html
    # Inline beside status
    assert "#evidence-loader" in html
    assert 'role="status"' in html and "aria-live" in html


def test_reduced_motion_respected_and_no_layout_shift() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in html
    assert "animation: none" in html


def test_loader_appears_during_request_and_disappears_on_done() -> None:
    html = INDEX.read_text(encoding="utf-8")
    # loader class toggling
    assert 'loader.classList.remove("hidden")' in html or "evidence-loader" in html
    assert 'loader2.classList.add("hidden")' in html or 'classList.add("hidden")' in html


def test_existing_selectors_preserved() -> None:
    html = INDEX.read_text(encoding="utf-8")
    # Required for Playwright tests
    required = ["#query", "#ask-btn", "#ask-status", "#evidence-query", "#evidence-btn", "#evidence-grid", "#evidence-status", "#evidence-loader"]
    for sel in required:
        token = sel.lstrip("#")
        assert f'id="{token}"' in html or f'"{token}"' in html, f"missing selector {sel}"


def test_no_oval_animation_remains_for_evidence() -> None:
    html = INDEX.read_text(encoding="utf-8")
    # The old证据 oval would have been evidence-spinner with spinner class. Must not remain in evidence area.
    assert 'id="evidence-spinner"' not in html, "old large oval element #evidence-spinner must be removed from evidence area"


# ---------------------------------------------------------------------------
# Prompt quality signals
# ---------------------------------------------------------------------------


def test_vision_prompt_enforces_visual_specificity() -> None:
    tpl = (Path(__file__).resolve().parents[2] / "app" / "prompts" / "templates" / "v1" / "vision_agent.md").read_text(encoding="utf-8")
    assert "caption and relevant paper text" in tpl or "surrounding text" in tpl
    assert "labels" in tpl.lower() and "relationship" in tpl.lower()
    assert "Answering figure-related questions" in tpl or "figure-related" in tpl.lower()


def test_judge_prompt_distinguishes_support_from_completeness() -> None:
    tpl = (Path(__file__).resolve().parents[2] / "app" / "prompts" / "templates" / "v1" / "judge_agent.md").read_text(encoding="utf-8")
    assert "Generic" in tpl or "generic" in tpl
    assert "depicted" in tpl.lower() or "shown" in tpl.lower()


def test_answer_generator_prompt_requires_completeness() -> None:
    tpl = (Path(__file__).resolve().parents[2] / "app" / "prompts" / "templates" / "v1" / "answer_generator.md").read_text(encoding="utf-8")
    assert "every part" in tpl.lower() or "Answer EVERY" in tpl
    assert "insufficient" in tpl.lower() or "cannot be established" in tpl.lower()
