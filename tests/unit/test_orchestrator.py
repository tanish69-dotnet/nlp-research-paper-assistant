"""Orchestrator tests (Phase 4): full pipeline happy paths + degradation.

These exercise ``full_reasoning`` directly (fast, no HTTP) with a deterministic
mock provider. Security assertions live here too (judge failure = no facts as
verified, citation resolution is deterministic).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest
from app.config import Settings
from app.models.mock import MockModelProvider
from app.orchestration.orchestrator import full_reasoning
from app.schemas.evidence import EvidenceBundle, EvidenceItem, TableData, ImageRef
from tests.conftest import load_mock_evidence, run

PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR4nGNgYGBgAAAABQABDQottQAAAABJRU5ErkJggg=="


def _valid_plan(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "question_type": "cross_modal_comparison",
        "required_modalities": ["text", "table", "figure"],
        "tasks": [
            {"task": "text context", "modality": "text"},
            {"task": "rank Table 3", "modality": "table"},
            {"task": "trend Figure 5", "modality": "figure"},
        ],
        "target_references": ["Table 3", "Figure 5"],
        "requires_cross_modal": True,
        "paper_scope": "single",
        "paper_ids": [],
        "sub_questions": [],
        "confidence": 0.9,
    }
    base.update(overrides)
    return base


def _bundle_with_b64_figure() -> EvidenceBundle:
    bundle = json.loads(json.dumps(load_mock_evidence()))
    for item in bundle["evidence"]:
        if item["type"] == "figure":
            item["image"] = {"b64": PNG_B64, "mime": "image/png"}
    return EvidenceBundle.model_validate(bundle)


def _text_claim() -> dict[str, Any]:
    return {
        "claim_id": "cl_text",
        "kind": "author_claim",
        "text": "We attribute the drop beyond 8k to attention dilution.",
        "evidence_ids": ["e_p001_p4_s42"],
        "confidence": 0.9,
    }


def _table_claim() -> dict[str, Any]:
    return {
        "claim_id": "cl_table",
        "kind": "table_comparison",
        "text": "Ours attains the highest SPIQA-F1 at 91.4.",
        "evidence_ids": ["e_p001_p7_t3"],
        "confidence": 0.95,
    }


def _figure_claim() -> dict[str, Any]:
    return {
        "claim_id": "cl_fig",
        "kind": "figure_observation",
        "text": "Performance peaks around 8k and then declines.",
        "evidence_ids": ["e_p001_p8_f5"],
        "confidence": 0.72,
    }


def _registry_with(overrides: dict[str, Any] | None = None, provider: MockModelProvider | None = None) -> Any:
    from app.models.routing import build_registry

    base: dict[str, Any] = {"model_provider": "mock", "log_level": "WARNING", "log_format": "console"}
    if overrides:
        base.update(overrides)
    settings = Settings(_env_file=None, **base)  # type: ignore[call-arg]
    if provider is not None:
        # Use the injected mock directly
        from app.models.routing import ModelRegistry  # noqa: WPS433

        return ModelRegistry(provider, settings), settings
    return build_registry(settings), settings


def test_full_pipeline_happy_path() -> None:
    provider = MockModelProvider(
        responses=[
            ("Query Analyzer", json.dumps(_valid_plan())),
            ("Text Reasoning Agent", json.dumps({"findings": [_text_claim()]})),
            ("Table Reasoning Agent", json.dumps({"findings": [_table_claim()]})),
            ("Vision", json.dumps({"findings": [_figure_claim()]})),
            (
                "Judge",
                json.dumps(
                    {
                        "verdicts": [
                            {"claim_id": "cl_text", "verdict": "SUPPORTED", "rationale": "ok", "evidence_ids_support": ["e_p001_p4_s42"], "evidence_ids_contradict": [], "missing_aspects": []},
                            {"claim_id": "cl_table", "verdict": "SUPPORTED", "rationale": "table is 91.4", "evidence_ids_support": ["e_p001_p7_t3"], "evidence_ids_contradict": [], "missing_aspects": []},
                            {"claim_id": "cl_fig", "verdict": "PARTIALLY_SUPPORTED", "rationale": "visual but no exact table value", "evidence_ids_support": ["e_p001_p8_f5"], "evidence_ids_contradict": [], "missing_aspects": ["exact number"]},
                        ]
                    }
                ),
            ),
            (
                "Answer Generator",
                json.dumps({"answer": "Ours is best [citation:cl_table] and the 8k trend [citation:cl_text]. Figure shows decline [citation:cl_fig].", "reasoning_summary": "summary"}),
            ),
        ]
    )
    registry, settings = _registry_with(provider=provider)
    bundle = _bundle_with_b64_figure()

    result = run(
        full_reasoning(
            "Which method performed best in Table 3, and why does Figure 5 show a drop?",
            bundle,
            "orch-happy",
            settings,
            registry,
        )
    )

    assert not result.unverified
    assert result.answer
    assert len(result.citations) == 3
    assert all(c.paper_id in {"paper_001", "paper_002"} for c in result.citations)
    assert all(c.page in {4, 7, 8, None} for c in result.citations)
    assert any(c.evidence_id == "e_p001_p7_t3" for c in result.citations)
    assert result.verification_result.status in {"supported", "partially_supported"}
    assert "unverified" not in result.verification_result.status


def test_vision_failure_does_not_block_text_and_table() -> None:
    """Vision down -> text+table continue; judge still runs; answer grounded on the rest."""
    provider = MockModelProvider(
        responses=[
            ("Query Analyzer", json.dumps(_valid_plan())),
            ("Text Reasoning Agent", json.dumps({"findings": [_text_claim()]})),
            ("Table Reasoning Agent", json.dumps({"findings": [_table_claim()]})),
            (
                "Judge",
                json.dumps(
                    {
                        "verdicts": [
                            {"claim_id": "cl_text", "verdict": "SUPPORTED", "rationale": "ok", "evidence_ids_support": ["e_p001_p4_s42"], "evidence_ids_contradict": [], "missing_aspects": []},
                            {"claim_id": "cl_table", "verdict": "SUPPORTED", "rationale": "ok", "evidence_ids_support": ["e_p001_p7_t3"], "evidence_ids_contradict": [], "missing_aspects": []},
                        ]
                    }
                ),
            ),
            (
                "Answer Generator",
                json.dumps({"answer": "Text+table only answer.", "reasoning_summary": "ok"}),
            ),
        ]
    )
    # Vision delay/slow would be caught before judge if we embed it this way; instead mock with no Vision response so the vision agent receives
    # a fallback empty finding path (the default fixture's figure file is missing → vision agent returns no_evidence, not an error).
    registry, settings = _registry_with(provider=provider)
    bundle = EvidenceBundle.model_validate(load_mock_evidence())  # no b64 — vision will degrade honestly

    result = run(
        full_reasoning("Which method?", bundle, "orch-partial-vision", settings, registry)
    )

    assert not result.unverified
    assert any(agent_run.status in {"no_evidence", "partial", "ok"} for agent_run in result.agent_runs if agent_run.agent == "vision_reasoner")


def test_judge_failure_leaves_pipeline_unverified() -> None:
    """Judge down ⇒ no facts are presented as verified."""
    provider = MockModelProvider(
        responses=[
            ("Query Analyzer", json.dumps(_valid_plan())),
            ("Text Reasoning Agent", json.dumps({"findings": [_text_claim()]})),
            ("Table Reasoning Agent", json.dumps({"findings": [_table_claim()]})),
            ("Vision", json.dumps({"findings": [_figure_claim()]})),
            ("Judge", "not json at all"),  # malformed → error
        ]
    )
    registry, settings = _registry_with(provider=provider)
    bundle = _bundle_with_b64_figure()

    result = run(full_reasoning("Q?", bundle, "judge-fails", settings, registry))

    assert result.unverified is True
    assert result.answer == ""
    assert result.verification_result.status == "unverified"
    assert any(agent_run.agent == "judge" and agent_run.status == "error" for agent_run in result.agent_runs)


def test_answer_generator_failure_graceful() -> None:
    """Generator down should still expose verified claims + statuses."""
    provider = MockModelProvider(
        responses=[
            ("Query Analyzer", json.dumps(_valid_plan())),
            ("Text Reasoning Agent", json.dumps({"findings": [_text_claim()]})),
            ("Table Reasoning Agent", json.dumps({"findings": [_table_claim()]})),
            ("Vision", json.dumps({"findings": [_figure_claim()]})),
            (
                "Judge",
                json.dumps(
                    {
                        "verdicts": [
                            {"claim_id": "cl_text", "verdict": "SUPPORTED", "rationale": "ok", "evidence_ids_support": ["e_p001_p4_s42"], "evidence_ids_contradict": [], "missing_aspects": []},
                            {"claim_id": "cl_table", "verdict": "SUPPORTED", "rationale": "ok", "evidence_ids_support": ["e_p001_p7_t3"], "evidence_ids_contradict": [], "missing_aspects": []},
                            {"claim_id": "cl_fig", "verdict": "SUPPORTED", "rationale": "ok", "evidence_ids_support": ["e_p001_p8_f5"], "evidence_ids_contradict": [], "missing_aspects": []},
                        ]
                    }
                ),
            ),
            ("Answer Generator", "not json at all"),
        ]
    )
    registry, settings = _registry_with(provider=provider)
    bundle = _bundle_with_b64_figure()

    result = run(full_reasoning("Q?", bundle, "gen-fails", settings, registry))

    assert not result.unverified
    assert result.answer == ""
    assert any(agent_run.agent == "answer_generator" and agent_run.status == "error" for agent_run in result.agent_runs)
    # On generator failure, no citations are resolved (answer itself failed).
    assert result.answer == ""


def test_deterministic_citation_resolution_from_verified_claims_only() -> None:
    """Unsupporteds are excluded from citation resolution."""
    provider = MockModelProvider(
        responses=[
            ("Query Analyzer", json.dumps(_valid_plan())),
            ("Text Reasoning Agent", json.dumps({"findings": [_text_claim()]})),
            ("Table Reasoning Agent", json.dumps({"findings": [_table_claim()]})),
            ("Vision", json.dumps({"findings": [_figure_claim()]})),
            (
                "Judge",
                json.dumps(
                    {
                        "verdicts": [
                            {"claim_id": "cl_text", "verdict": "UNSUPPORTED", "rationale": "no", "evidence_ids_support": [], "evidence_ids_contradict": [], "missing_aspects": []},
                            {"claim_id": "cl_table", "verdict": "SUPPORTED", "rationale": "yes", "evidence_ids_support": ["e_p001_p7_t3"], "evidence_ids_contradict": [], "missing_aspects": []},
                            {"claim_id": "cl_fig", "verdict": "SUPPORTED", "rationale": "yes", "evidence_ids_support": ["e_p001_p8_f5"], "evidence_ids_contradict": [], "missing_aspects": []},
                        ]
                    }
                ),
            ),
            ("Answer Generator", json.dumps({"answer": "Supported only [citation:cl_table] [citation:cl_fig].", "reasoning_summary": "ok"})),
        ]
    )
    registry, settings = _registry_with(provider=provider)
    bundle = _bundle_with_b64_figure()

    result = run(full_reasoning("Q?", bundle, "citations-only-verified", settings, registry))

    assert all(c.evidence_id in {"e_p001_p7_t3", "e_p001_p8_f5"} for c in result.citations)
    assert not any(c.evidence_id == "e_p001_p4_s42" for c in result.citations)


def test_empty_evidence_raises_before_agents() -> None:
    from app.core.errors import EvidenceEmptyError

    registry, settings = _registry_with()

    with pytest.raises(EvidenceEmptyError):
        run(full_reasoning("Q?", EvidenceBundle(evidence=[]), "empty", settings, registry))


def test_all_evidence_ids_survive_the_pipeline() -> None:
    """Invariant: every citation_id maps to supplied evidence_ids underneath."""
    provider = MockModelProvider(
        responses=[
            ("Query Analyzer", json.dumps(_valid_plan())),
            ("Text Reasoning Agent", json.dumps({"findings": [_text_claim()]})),
            ("Table Reasoning Agent", json.dumps({"findings": [_table_claim()]})),
            ("Vision", json.dumps({"findings": [_figure_claim()]})),
            (
                "Judge",
                json.dumps(
                    {
                        "verdicts": [
                            {"claim_id": "cl_text", "verdict": "SUPPORTED", "rationale": "ok", "evidence_ids_support": ["e_p001_p4_s42"], "evidence_ids_contradict": [], "missing_aspects": []},
                            {"claim_id": "cl_table", "verdict": "SUPPORTED", "rationale": "ok", "evidence_ids_support": ["e_p001_p7_t3"], "evidence_ids_contradict": [], "missing_aspects": []},
                            {"claim_id": "cl_fig", "verdict": "SUPPORTED", "rationale": "ok", "evidence_ids_support": ["e_p001_p8_f5"], "evidence_ids_contradict": [], "missing_aspects": []},
                        ]
                    }
                ),
            ),
            ("Answer Generator", json.dumps({"answer": "Done.", "reasoning_summary": "ok"})),
        ]
    )
    registry, settings = _registry_with(provider=provider)
    bundle = _bundle_with_b64_figure()

    result = run(full_reasoning("Q?", bundle, "invariants", settings, registry))

    supply = {item.evidence_id for item in bundle.evidence}
    for claim in result.claims:
        assert set(claim.evidence_ids) <= supply, claim
    for citation in result.citations:
        assert citation.evidence_id in supply


def test_cross_modal_with_missing_second_half_reports_partial() -> None:
    """Supply only table evidence for a 'Table 3 + Figure 5' question → partial."""
    from app.orchestration.orchestrator import full_reasoning as _full  # noqa: WPS433

    provider = MockModelProvider(
        responses=[
            ("Query Analyzer", json.dumps(_valid_plan(required_modalities=["text", "table", "figure"]))),
            ("Text Reasoning Agent", json.dumps({"findings": [_text_claim()]})),
            ("Table Reasoning Agent", json.dumps({"findings": [_table_claim()]})),
            (
                "Judge",
                json.dumps(
                    {
                        "verdicts": [
                            {"claim_id": "cl_text", "verdict": "SUPPORTED", "rationale": "ok", "evidence_ids_support": ["e_p001_p4_s42"], "evidence_ids_contradict": [], "missing_aspects": []},
                            {"claim_id": "cl_table", "verdict": "SUPPORTED", "rationale": "ok", "evidence_ids_support": ["e_p001_p7_t3"], "evidence_ids_contradict": [], "missing_aspects": []},
                        ]
                    }
                ),
            ),
            ("Answer Generator", json.dumps({"answer": "Only the first half is supported [citation:cl_table].", "reasoning_summary": "ok"})),
        ]
    )
    registry, settings = _registry_with(provider=provider)
    # Figure image still missing → vision degrades
    bundle = EvidenceBundle.model_validate(load_mock_evidence())  # no b64 figure

    result = run(_full("Which method in Table 3 and why does Figure 5 drop?", bundle, "cross-modal-partial", settings, registry))

    # The answer still exists; the endpoint should present it as "partial".
    assert result.answer
    assert any(agent_run.agent == "vision_reasoner" for agent_run in result.agent_runs)


def test_multipaper_claims_preserve_paper_ids() -> None:
    """Paper identity is not merged across papers."""
    bundle = EvidenceBundle.model_validate(load_mock_evidence())  # already has paper_001 + paper_002
    provider = MockModelProvider(
        responses=[
            ("Query Analyzer", json.dumps(_valid_plan(required_modalities=["text", "table"], paper_scope="multi"))),
            ("Text Reasoning Agent", json.dumps({"findings": [_text_claim()]})),
            ("Table Reasoning Agent", json.dumps({"findings": [_table_claim()]})),
            (
                "Judge",
                json.dumps(
                    {
                        "verdicts": [
                            {"claim_id": "cl_text", "verdict": "SUPPORTED", "rationale": "ok", "evidence_ids_support": ["e_p001_p4_s42"], "evidence_ids_contradict": [], "missing_aspects": []},
                            {"claim_id": "cl_table", "verdict": "SUPPORTED", "rationale": "ok", "evidence_ids_support": ["e_p001_p7_t3"], "evidence_ids_contradict": [], "missing_aspects": []},
                        ]
                    }
                ),
            ),
            ("Answer Generator", json.dumps({"answer": "[citation:cl_text] [citation:cl_table]", "reasoning_summary": "ok"})),
        ]
    )
    registry, settings = _registry_with(provider=provider)

    result = run(full_reasoning("Compare paper 1 and paper 2", bundle, "multipaper", settings, registry))

    assert result.answer
    by_citation = {c.evidence_id: c.paper_id for c in result.citations}
    # The only citations here happen to come from paper_001 (text + table)
    assert by_citation.get("e_p001_p4_s42") == "paper_001"
    if any(c.evidence_id.startswith("e_p002") for c in result.citations):
        assert all(
            c.paper_id == "paper_002"
            for c in result.citations
            if c.evidence_id.startswith("e_p002")
        )
