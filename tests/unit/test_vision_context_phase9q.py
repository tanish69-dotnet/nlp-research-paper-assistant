"""Phase 9Q — compact vision-context selection (deterministic, offline).

Covers: target-figure ordering, same-paper text preference, other-paper
exclusion, caption-only → no_evidence, empty findings → partial, malformed
output → error, contradictory evidence preserved for verification,
multi-figure bounded selection, text/table routing unchanged.
"""

from __future__ import annotations

import json

from app.agents.base import AgentContext
from app.agents.vision_agent import (
    MAX_VISION_IMAGES,
    MAX_VISION_TEXT_BLOCKS,
    VisionAgent,
    select_vision_context,
)
from app.models.mock import MockModelProvider
from app.schemas.evidence import EvidenceItem, ImageRef
from tests.conftest import run

PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR4nGNgYGBgAAAABQABDQottQAAAABJRU5ErkJggg=="


def _fig(eid: str, paper: str, *, image: bool = True, caption: str = "Figure 1: X") -> EvidenceItem:
    return EvidenceItem(
        evidence_id=eid,
        paper_id=paper,
        type="figure",
        content="",
        caption=caption,
        image=ImageRef(b64=PNG_B64) if image else None,
    )


def _text(eid: str, paper: str, content: str) -> EvidenceItem:
    return EvidenceItem(evidence_id=eid, paper_id=paper, type="text", content=content)


def _table(eid: str, paper: str) -> EvidenceItem:
    return EvidenceItem(evidence_id=eid, paper_id=paper, type="table", content="| A |")


# --- 1. target-figure ordering --------------------------------------------------


def test_target_figure_with_bytes_comes_first():
    other = _fig("paper_002:fig", "paper_002", image=True)
    target = _fig("1611.04684v1:elem_000", "1611.04684v1", image=True)
    evidence = (other, _text("t1", "paper_001", "x"), target)

    figures, _ = select_vision_context(evidence, "Look at Figure 1 of paper 1611.04684v1.")

    assert figures[0].evidence_id == "1611.04684v1:elem_000"


# --- 2. same-paper text preference ------------------------------------------------


def test_same_paper_text_preferred_over_other_paper():
    fig = _fig("1611.04684v1:elem_000", "1611.04684v1", image=True)
    same = _text("t_same", "1611.04684v1", "Figure 1 gives the architecture of our model.")
    other = _text("t_other", "paper_002", "Figure 1 gives the architecture of our model.")
    evidence = (other, fig, same)

    _, texts = select_vision_context(evidence, "Describe Figure 1 of 1611.04684v1.")

    assert texts and texts[0].evidence_id == "t_same"
    assert len(texts) <= MAX_VISION_TEXT_BLOCKS


def test_mention_overlap_preferred_within_same_paper():
    fig = _fig("p:fig", "p", image=True, caption="Figure 1: smoke diagram")
    generic = _text("t_gen", "p", "Some unrelated prose about training.")
    mention = _text("t_men", "p", "Figure 1 shows Box Alpha feeding Box Beta.")
    evidence = (fig, generic, mention)

    _, texts = select_vision_context(evidence, "Describe the diagram.")

    assert texts[0].evidence_id == "t_men"


# --- 3. other-paper figure exclusion -----------------------------------------------


def test_other_paper_figures_excluded_from_call_but_kept_in_bundle():
    target = _fig("1611.04684v1:elem_000", "1611.04684v1", image=True)
    other = _fig("paper_002:fig", "paper_002", image=True)
    evidence = (target, other, _text("t", "1611.04684v1", "ctx"))

    figures, _ = select_vision_context(evidence, "Figure 1 of 1611.04684v1?")

    # Target paper first; other-paper figures are not dropped from selection
    # entirely (bounded multi-figure budget) but never precede the target.
    assert figures[0].evidence_id == "1611.04684v1:elem_000"
    assert len(figures) <= 2
    # The full bundle is untouched — text/table agents and the judge still see it.
    assert len(evidence) == 3


# --- 4. caption-only → no_evidence ---------------------------------------------------


def test_caption_only_bundle_is_no_evidence():
    item = _fig("p:fig", "p", image=False)
    ctx = AgentContext(
        request_id="t", query="Describe Figure 1.", evidence=(item,),
        model="m", provider_name="mock",
    )

    claims, agent_run = run(VisionAgent(MockModelProvider()).run_for_evidence(ctx))

    assert claims == []
    assert agent_run.status == "no_evidence"


# --- 5. empty findings stay partial ----------------------------------------------------


def test_empty_findings_stay_partial():
    provider = MockModelProvider(responses=[("Vision", json.dumps({"findings": []}))])
    item = _fig("p:fig", "p", image=True)
    ctx = AgentContext(
        request_id="t", query="Describe Figure 1.", evidence=(item,),
        model="m", provider_name="mock",
    )

    claims, agent_run = run(VisionAgent(provider).run_for_evidence(ctx))

    assert claims == []
    assert agent_run.status == "partial"


# --- 6. malformed output stays error -----------------------------------------------------


def test_malformed_output_stays_error():
    provider = MockModelProvider(responses=[("Vision", "not json at all")])
    item = _fig("p:fig", "p", image=True)
    ctx = AgentContext(
        request_id="t", query="Describe Figure 1.", evidence=(item,),
        model="m", provider_name="mock",
    )

    claims, agent_run = run(VisionAgent(provider).run_for_evidence(ctx))

    assert claims == []
    assert agent_run.status == "error"
    assert agent_run.error is not None


# --- 7. contradictory evidence preserved for verification ------------------------------------


def test_contradictory_text_reaches_judge_bundle():
    """Selection never filters by stance: a contradicting text stays in context."""
    fig = _fig("p:fig", "p", image=True)
    supporting = _text("t_sup", "p", "Figure 1 shows Box Alpha feeding Box Beta.")
    contradicting = _text("t_con", "p", "Erratum: Figure 1 does not show any arrow.")
    evidence = (fig, supporting, contradicting)

    _, texts = select_vision_context(evidence, "Describe Figure 1.")

    # Both texts are same-paper; the top-2 keep both stances available.
    assert {t.evidence_id for t in texts} == {"t_sup", "t_con"}


# --- 8. multi-figure intent bounded ------------------------------------------------------------


def test_multi_figure_question_bounds_images():
    figs = tuple(_fig(f"p:fig{i}", "p", image=True) for i in range(5))
    evidence = figs + (_text("t", "p", "Compare Figure 1 and Figure 2."),)

    figures, _ = select_vision_context(
        evidence, "Compare Figure 1 and Figure 2 of paper p."
    )

    assert len(figures) <= MAX_VISION_IMAGES
    assert figures[0].evidence_id == "p:fig0"


def test_single_figure_question_attaches_one_image():
    figs = tuple(_fig(f"p:fig{i}", "p", image=True) for i in range(3))
    evidence = figs + (_text("t", "p", "Describe Figure 1."),)

    from app.agents.vision_agent import _evidence_contexts_for_vision
    from app.config import Settings

    settings = Settings(_env_file=None)
    blocks, images, _ = _evidence_contexts_for_vision(
        (figs[0],) + (_text("t", "p", "ctx"),), settings, 3000, query="Describe Figure 1."
    )

    assert len(images) == 1


# --- 9. text/table routing unchanged ---------------------------------------------------------------


def test_text_table_items_never_become_vision_subjects():
    fig = _fig("p:fig", "p", image=True)
    table = _table("p:tbl", "p")
    text = _text("p:txt", "p", "Figure 1 context.")
    evidence = (table, text, fig)

    figures, texts = select_vision_context(evidence, "Describe Figure 1.")

    assert all(f.type == "figure" for f in figures)
    assert all(t.type == "text" for t in texts)
    assert table.evidence_id not in {f.evidence_id for f in figures}
