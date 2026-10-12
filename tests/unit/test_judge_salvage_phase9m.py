"""Phase 9M — Judge salvage parsing + fail-closed diagnostics.

Covers: minimal valid payloads (only claim_id/verdict/support), absent
optional lists defaulting to [], unknown ids still dropped, invalid verdict
strings still dropped, malformed field types still dropped, SUPPORTED with
empty support rejected, and all-dropped output failing closed with an error
run (not silent deterministic UNSUPPORTED).
"""

from __future__ import annotations

import json

from app.agents.base import AgentContext
from app.agents.judge_answer import JudgeAgent
from app.models.mock import MockModelProvider
from app.schemas.claims import Claim
from app.schemas.evidence import EvidenceBundle, EvidenceItem
from tests.conftest import run


def _claim(claim_id: str = "cl1") -> Claim:
    return Claim(
        claim_id=claim_id,
        agent="vision_reasoner",
        kind="figure_observation",  # type: ignore[arg-type]
        text="The figure shows the architecture of a model with multiple channels.",
        evidence_ids=["e_fig", "e_txt"],
        confidence=0.8,
    )


def _bundle() -> EvidenceBundle:
    return EvidenceBundle(
        evidence=[
            EvidenceItem(
                evidence_id="e_fig",
                paper_id="paper_001",
                type="figure",
                content="",
                caption="Figure 1: Architecture",
            ),
            EvidenceItem(
                evidence_id="e_txt",
                paper_id="paper_001",
                type="text",
                content="Figure 1 gives the architecture of our model.",
            ),
        ]
    )


def _ctx() -> AgentContext:
    bundle = _bundle()
    return AgentContext(
        request_id="t",
        query="Describe Figure 1.",
        evidence=tuple(bundle.evidence),
        model="m",
        provider_name="mock",
    )


def test_minimal_valid_payload_is_accepted() -> None:
    """Only claim_id + verdict + evidence_ids_support (optional lists absent)."""
    provider = MockModelProvider(
        responses=[
            (
                "Judge",
                json.dumps(
                    {
                        "verdicts": [
                            {
                                "claim_id": "cl1",
                                "verdict": "SUPPORTED",
                                "evidence_ids_support": ["e_fig"],
                            }
                        ]
                    }
                ),
            )
        ]
    )

    verdicts, agent_run = run(JudgeAgent(provider).judge([_claim()], _bundle(), _ctx()))

    assert agent_run.status == "ok"
    assert verdicts[0].verdict == "SUPPORTED"
    assert verdicts[0].evidence_ids_support == ["e_fig"]
    assert verdicts[0].evidence_ids_contradict == []
    assert verdicts[0].missing_aspects == []


def test_supported_with_empty_support_is_rejected_and_fails_closed() -> None:
    provider = MockModelProvider(
        responses=[
            (
                "Judge",
                json.dumps(
                    {
                        "verdicts": [
                            {
                                "claim_id": "cl1",
                                "verdict": "SUPPORTED",
                                "evidence_ids_support": [],
                            }
                        ]
                    }
                ),
            )
        ]
    )

    verdicts, agent_run = run(JudgeAgent(provider).judge([_claim()], _bundle(), _ctx()))

    # Fail-closed: judge run is error with a diagnostic; the only emitted
    # verdict is the deterministic UNSUPPORTED backfill (never a SUPPORTED).
    assert agent_run.status == "error"
    assert agent_run.error is not None
    assert "unusable" in agent_run.error.message
    assert all(v.verdict == "UNSUPPORTED" and v.verifier == "deterministic" for v in verdicts)


def test_unknown_evidence_id_still_dropped_and_fails_closed() -> None:
    provider = MockModelProvider(
        responses=[
            (
                "Judge",
                json.dumps(
                    {
                        "verdicts": [
                            {
                                "claim_id": "cl1",
                                "verdict": "SUPPORTED",
                                "evidence_ids_support": ["e_ghost"],
                            }
                        ]
                    }
                ),
            )
        ]
    )

    verdicts, agent_run = run(JudgeAgent(provider).judge([_claim()], _bundle(), _ctx()))

    assert agent_run.status == "error"
    assert agent_run.error is not None
    assert "unknown evidence ids" in agent_run.error.message
    assert verdicts == []


def test_invalid_verdict_string_still_dropped_and_fails_closed() -> None:
    provider = MockModelProvider(
        responses=[
            (
                "Judge",
                json.dumps(
                    {
                        "verdicts": [
                            {
                                "claim_id": "cl1",
                                "verdict": "MAYBE",
                                "evidence_ids_support": ["e_fig"],
                            }
                        ]
                    }
                ),
            )
        ]
    )

    verdicts, agent_run = run(JudgeAgent(provider).judge([_claim()], _bundle(), _ctx()))

    assert agent_run.status == "error"
    assert all(v.verdict == "UNSUPPORTED" and v.verifier == "deterministic" for v in verdicts)


def test_malformed_field_type_still_dropped() -> None:
    provider = MockModelProvider(
        responses=[
            (
                "Judge",
                json.dumps(
                    {
                        "verdicts": [
                            {
                                "claim_id": "cl1",
                                "verdict": "SUPPORTED",
                                "evidence_ids_support": "e_fig",
                            }
                        ]
                    }
                ),
            )
        ]
    )

    verdicts, agent_run = run(JudgeAgent(provider).judge([_claim()], _bundle(), _ctx()))

    # Phase 9N: required-field mistypes (support as string) still fail closed.
    # Optional-field mistypes are coerced (see the missing_aspects test below).
    assert agent_run.status == "error"
    assert all(v.verdict == "UNSUPPORTED" and v.verifier == "deterministic" for v in verdicts)


def test_mistyped_optional_lists_are_coerced_not_dropped() -> None:
    """missing_aspects as a string must not sink an otherwise valid verdict."""
    provider = MockModelProvider(
        responses=[
            (
                "Judge",
                json.dumps(
                    {
                        "verdicts": [
                            {
                                "claim_id": "cl1",
                                "verdict": "SUPPORTED",
                                "evidence_ids_support": ["e_fig"],
                                "missing_aspects": "none",
                            }
                        ]
                    }
                ),
            )
        ]
    )

    verdicts, agent_run = run(JudgeAgent(provider).judge([_claim()], _bundle(), _ctx()))

    assert agent_run.status == "ok"
    assert verdicts[0].verdict == "SUPPORTED"
    assert verdicts[0].missing_aspects == []


def test_live_shaped_minimal_supported_verdict_passes() -> None:
    """The exact minimal shape a small model emits for the Figure 1 claim."""
    provider = MockModelProvider(
        responses=[
            (
                "Judge",
                json.dumps(
                    {
                        "verdicts": [
                            {
                                "claim_id": "cl1",
                                "verdict": "SUPPORTED",
                                "rationale": "caption and mention match the architecture claim",
                                "evidence_ids_support": ["e_fig", "e_txt"],
                            }
                        ]
                    }
                ),
            )
        ]
    )

    verdicts, agent_run = run(JudgeAgent(provider).judge([_claim()], _bundle(), _ctx()))

    assert agent_run.status == "ok"
    assert verdicts[0].verdict == "SUPPORTED"
    assert set(verdicts[0].evidence_ids_support) == {"e_fig", "e_txt"}
