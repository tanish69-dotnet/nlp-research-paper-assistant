"""Reasoning request/response contract tests (API_SPEC §3.4, §5, §6)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.claims import Claim
from app.schemas.errors import ErrorCode, ProblemDetail
from app.schemas.evidence import EvidenceBundle
from app.schemas.query import QueryPlan
from app.schemas.reasoning import ReasoningRequest, ReasoningResponse
from app.schemas.verification import VerificationResult
from tests.conftest import load_mock_evidence


def _request_payload() -> dict:
    return {
        "query": "Which method performed best in Table 3?",
        "evidence": load_mock_evidence(),
        "options": {"include_agent_outputs": True},
    }


def test_reasoning_request_round_trip() -> None:
    request = ReasoningRequest.model_validate(_request_payload())

    assert request.query.startswith("Which method")
    assert isinstance(request.evidence, EvidenceBundle)
    assert request.options.confidence_threshold == 0.5

    again = ReasoningRequest.model_validate(request.model_dump(mode="json"))
    assert again.model_dump(mode="json") == request.model_dump(mode="json")


def test_reasoning_request_requires_query() -> None:
    payload = _request_payload()
    payload["query"] = ""

    with pytest.raises(ValidationError):
        ReasoningRequest.model_validate(payload)


def test_reasoning_request_rejects_unknown_fields() -> None:
    payload = _request_payload()
    payload["unexpected"] = True

    with pytest.raises(ValidationError):
        ReasoningRequest.model_validate(payload)


def test_options_reject_unknown_fields() -> None:
    payload = _request_payload()
    payload["options"]["not_a_real_option"] = 1

    with pytest.raises(ValidationError):
        ReasoningRequest.model_validate(payload)


def test_empty_evidence_is_accepted_by_schema() -> None:
    """The route (Phase 4) must be able to return 400 EVIDENCE_EMPTY."""
    payload = _request_payload()
    payload["evidence"]["evidence"] = []

    request = ReasoningRequest.model_validate(payload)
    assert request.evidence.evidence == []


def test_minimal_reasoning_response_is_valid() -> None:
    response = ReasoningResponse(
        request_id="abc123",
        status="ok",
        verification=VerificationResult(status="unverified"),
    )

    assert response.confidence == 0.0
    assert response.citations == []
    assert response.metadata.pipeline_version == "0.1.0"


def test_reasoning_response_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ReasoningResponse(
            request_id="abc",
            status="ok",
            verification=VerificationResult(status="unverified"),
            hallucination_score=0.1,  # not part of the contract
        )


def test_claim_with_verification_round_trip() -> None:
    claim = Claim(
        claim_id="cl1",
        agent="table_reasoner",
        kind="table_comparison",
        text="Ours attains the highest F1",
        evidence_ids=["e_p001_p7_t3"],
        confidence=0.9,
        verification={
            "claim_id": "cl1",
            "verdict": "SUPPORTED",
            "verifier": "deterministic+judge",
            "rationale": "Row 'Ours' F1=91.4 is the column maximum.",
        },
    )

    assert claim.verification is not None
    assert claim.verification.verdict == "SUPPORTED"
    dumped = claim.model_dump(mode="json")
    assert Claim.model_validate(dumped).model_dump(mode="json") == dumped


def test_claim_confidence_out_of_range_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Claim(
            claim_id="cl1",
            agent="text_reasoner",
            kind="author_claim",
            text="x",
            confidence=1.7,
        )


def test_query_plan_requires_valid_question_type() -> None:
    plan = QueryPlan(question_type="cross_modal_comparison", confidence=0.9)

    assert plan.paper_scope == "any"
    with pytest.raises(ValidationError):
        QueryPlan(question_type="not_a_type", confidence=0.5)


def test_problem_detail_shape() -> None:
    problem = ProblemDetail.build(
        code=ErrorCode.EVIDENCE_EMPTY,
        status=400,
        detail="evidence list is empty",
        request_id="req-1",
    )

    assert problem.type.endswith("EVIDENCE_EMPTY")
    assert problem.code is ErrorCode.EVIDENCE_EMPTY
    assert problem.retryable is False
    assert set(problem.model_dump()) == {
        "type",
        "title",
        "status",
        "detail",
        "code",
        "request_id",
        "retryable",
    }


def test_problem_detail_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ProblemDetail(
            type="t",
            title="T",
            status=500,
            detail="d",
            code=ErrorCode.INTERNAL_ERROR,
            request_id="r",
            stack="Traceback ...",  # never allowed in responses
        )
