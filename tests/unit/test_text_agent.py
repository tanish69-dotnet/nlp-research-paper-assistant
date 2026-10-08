"""Text-agent tests (Phase 2).

The agent produces structured Claims over the textual evidence. Every claim
must be bound to the supplied evidence_id set and labelled correctly as
``author_claim`` vs ``inference``.
"""

from __future__ import annotations

import json

from app.agents.base import AgentContext
from app.agents.text_agent import TextAgent
from app.schemas.evidence import EvidenceItem
from app.models.mock import MockModelProvider
from tests.conftest import load_mock_evidence, run


def _text_evidence() -> tuple[EvidenceItem, ...]:
    """Text-only slice of the fixture (what TextAgent sees)."""
    bundle = load_mock_evidence()
    return tuple(
        EvidenceItem.model_validate(item)
        for item in bundle["evidence"]
        if item["type"] == "text"
    )


def _ctx(
    query: str = "test question",
    evidence: tuple[EvidenceItem, ...] | None = None,
) -> AgentContext:
    if evidence is None:
        evidence = _text_evidence()
    return AgentContext(
        request_id="test-1",
        query=query,
        evidence=evidence,
        model="mock-model",
        provider_name="mock",
    )


def _findings_json(*findings: dict) -> str:
    return json.dumps({"findings": list(findings)})


def test_produces_author_claim_and_inference_with_valid_evidence_ids() -> None:
    evidence = _text_evidence()
    id0 = evidence[0].evidence_id
    id1 = evidence[1].evidence_id

    provider = MockModelProvider(
        responses=[
            (
                "why does Figure 5",
                _findings_json(
                    {
                        "claim_id": "cl1",
                        "kind": "author_claim",
                        "text": "We attribute the drop to attention dilution.",
                        "evidence_ids": [id1],
                        "confidence": 0.95,
                    },
                    {
                        "claim_id": "cl2",
                        "kind": "inference",
                        "text": "The 16k context degrades F1 by adding irrelevant passages.",
                        "evidence_ids": [id0, id1],
                        "confidence": 0.6,
                    },
                ),
            )
        ]
    )

    claims, agent_run = run(TextAgent(provider).run_for_evidence(_ctx("why does Figure 5 drop?")))

    assert {claim.kind for claim in claims} == {"author_claim", "inference"}
    assert all(claim.evidence_ids for claim in claims)
    assert agent_run.status in {"ok", "partial"}
    assert set(agent_run.findings) == {claim.claim_id for claim in claims}


def test_drops_claims_referencing_unknown_evidence_ids() -> None:
    provider = MockModelProvider(
        responses=[
            (
                "dogs",
                _findings_json(
                    {
                        "claim_id": "bad",
                        "kind": "inference",
                        "text": "Fabricated claim with a made-up id.",
                        "evidence_ids": ["e_does_not_exist"],
                        "confidence": 0.9,
                    },
                    {
                        "claim_id": "good",
                        "kind": "author_claim",
                        "text": "Real claim about the paper.",
                        "evidence_ids": [_text_evidence()[0].evidence_id],
                        "confidence": 0.8,
                    },
                ),
            )
        ]
    )

    claims, agent_run = run(TextAgent(provider).run_for_evidence(_ctx("dogs")))

    assert [claim.claim_id for claim in claims] == ["good"]
    assert "good" in agent_run.findings
    assert "bad" not in agent_run.findings


def test_insufficient_evidence_returns_empty_findings() -> None:
    provider = MockModelProvider(
        responses=[("unrelated", _findings_json())]
    )

    claims, agent_run = run(TextAgent(provider).run_for_evidence(_ctx("unrelated question with no support")))

    assert claims == []
    assert agent_run.status == "partial"
    assert agent_run.findings == []


def test_no_text_evidence_returns_no_evidence_status() -> None:
    provider = MockModelProvider()

    claims, agent_run = run(
        TextAgent(provider).run_for_evidence(_ctx("x", evidence=()))
    )

    assert claims == []
    assert agent_run.status == "no_evidence"


def test_malformed_payload_with_no_findings_list_is_error() -> None:
    provider = MockModelProvider(
        responses=[("x", json.dumps({"unexpected": "shape"}))]
    )

    claims, agent_run = run(TextAgent(provider).run_for_evidence(_ctx("x")))

    assert claims == []
    assert agent_run.status == "error"
    assert agent_run.error is not None


def test_malformed_json_triggers_error_status() -> None:
    provider = MockModelProvider(responses=[("x", "not json at all")])

    claims, agent_run = run(TextAgent(provider).run_for_evidence(_ctx("x")))

    assert claims == []
    assert agent_run.status == "error"


def test_provider_timeout_at_the_text_agent_becomes_error_status() -> None:
    slow = MockModelProvider(delay_s=0.3)
    ctx = AgentContext(
        request_id="timeout-test",
        query="x",
        evidence=_text_evidence(),
        model="m",
        provider_name="mock",
        timeout_s=0.05,
    )

    claims, agent_run = run(TextAgent(slow).run_for_evidence(ctx))

    assert claims == []
    assert agent_run.status == "error"


def test_invalid_kind_is_dropped() -> None:
    provider = MockModelProvider(
        responses=[
            (
                "x",
                _findings_json(
                    {
                        "claim_id": "weird",
                        "kind": "figure_observation",  # not legal for text
                        "text": "A trend described as if it were a figure.",
                        "evidence_ids": [_text_evidence()[0].evidence_id],
                        "confidence": 0.7,
                    }
                ),
            )
        ]
    )

    claims, _ = run(TextAgent(provider).run_for_evidence(_ctx("x")))

    assert len(claims) == 0


def test_only_text_typed_evidence_is_used() -> None:
    """When the full bundle (text+table+figure) is passed, table/figure ids are ignored."""
    from tests.conftest import load_mock_evidence as raw

    full = tuple(EvidenceItem.model_validate(item) for item in raw()["evidence"])
    # mock returns a claim citing a table evidence_id — TextAgent must drop it
    table_id = [item.evidence_id for item in full if item.type == "table"][0]

    provider = MockModelProvider(
        responses=[
            ("x", _findings_json(
                {
                    "claim_id": "c_img",
                    "kind": "author_claim",
                    "text": "Table claims should not pass through the text agent.",
                    "evidence_ids": [table_id],
                    "confidence": 0.8,
                }
            ))
        ]
    )

    claims, _ = run(TextAgent(provider).run_for_evidence(_ctx("x", evidence=full)))

    assert len(claims) == 0
