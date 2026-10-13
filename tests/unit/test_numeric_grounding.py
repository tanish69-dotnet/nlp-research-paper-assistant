"""Numeric-grounding regression tests (pixel-width failure + friends).

A number appearing *somewhere* in the evidence is not sufficient: the
specific quantity (value + unit/subject context) must be jointly present in
the cited evidence. Valid table scores keep working.
"""

from __future__ import annotations

from app.schemas.claims import Claim
from app.schemas.evidence import EvidenceBundle, EvidenceItem, TableData
from app.verification.deterministic import validate_against_bundle


def _claim(text: str, evidence_ids: list[str], **overrides) -> Claim:
    payload = {
        "claim_id": "cl1",
        "agent": "table_reasoner",
        "kind": "table_observation",
        "text": text,
        "evidence_ids": evidence_ids,
        "confidence": 0.9,
    }
    payload.update(overrides)
    return Claim(**payload)  # type: ignore[arg-type]


def _table_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        evidence=[
            EvidenceItem(
                evidence_id="e_tbl",
                paper_id="p",
                type="table",
                content="| Model | F1 |\n| A | 0.77 |\n| B | 0.61 |",
                caption="Table 1: scores.",
                table_data=TableData(
                    headers=["Model", "F1"],
                    rows=[["A", "0.77"], ["B", "0.61"]],
                    caption="Table 1: scores.",
                ),
            )
        ]
    )


def _figure_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        evidence=[
            EvidenceItem(
                evidence_id="e_fig",
                paper_id="p",
                type="figure",
                content="",
                caption="Figure 1: diagram.",
            )
        ]
    )


def test_pixel_width_with_unrelated_table_value_is_unsupported():
    """Original failure: pixel width must not inherit a table F1."""
    claim = _claim(
        "The exact pixel width of the Done box in Figure 1 is 0.77.",
        ["e_tbl"],
    )
    bundle = EvidenceBundle(
        evidence=_table_bundle().evidence + _figure_bundle().evidence
    )

    verdict, detail = validate_against_bundle(claim, bundle)

    assert verdict == "UNSUPPORTED"
    assert detail is not None


def test_unrelated_table_value_cannot_support_figure_measurement():
    # "peaks at 0.77" has no physical-property noun, so the gate defers to
    # the LLM judge (None) — but a *pixel* measurement on the same value
    # must fail. Both assertions pin the boundary precisely.
    claim = _claim("The curve peaks at 0.77 pixels.", ["e_tbl"])
    verdict, _ = validate_against_bundle(claim, _table_bundle())

    assert verdict == "UNSUPPORTED"


def test_bare_number_without_property_defers_to_judge():
    claim = _claim("The curve peaks at 0.77.", ["e_tbl"])
    verdict, _ = validate_against_bundle(claim, _table_bundle())

    assert verdict is None


def test_incorrect_unit_is_unsupported():
    claim = _claim("Method A reaches 0.77 pixels F1.", ["e_tbl"])
    verdict, _ = validate_against_bundle(claim, _table_bundle())

    assert verdict == "UNSUPPORTED"


def test_unsupported_conversion_is_unsupported():
    claim = _claim("Method A reaches 77 seconds.", ["e_tbl"])
    verdict, _ = validate_against_bundle(claim, _table_bundle())

    assert verdict == "UNSUPPORTED"


def test_correct_table_score_passes_gate():
    """Valid numeric answers must keep working (gate returns None → LLM)."""
    claim = _claim("Method A achieves an F1 score of 0.77.", ["e_tbl"])
    verdict, _ = validate_against_bundle(claim, _table_bundle())

    assert verdict is None


def test_valid_measurement_in_text_passes_gate():
    bundle = EvidenceBundle(
        evidence=[
            EvidenceItem(
                evidence_id="e_txt",
                paper_id="p",
                type="text",
                content="The Done box is 120 pixels wide in Figure 1.",
            )
        ]
    )
    claim = _claim(
        "The Done box is 120 pixels wide.", ["e_txt"],
        agent="vision_reasoner", kind="figure_observation",
    )
    verdict, _ = validate_against_bundle(claim, bundle)

    assert verdict is None


def test_claim_without_numbers_is_unaffected():
    claim = _claim("Box Alpha feeds Box Beta.", ["e_tbl"])
    verdict, _ = validate_against_bundle(claim, _table_bundle())

    assert verdict is None
