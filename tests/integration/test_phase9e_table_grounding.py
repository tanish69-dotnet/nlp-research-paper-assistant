"""Phase 9E regression tests for complete versus caption-only table evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import Settings
from app.models.mock import MockModelProvider
from app.models.routing import ModelRegistry
from app.orchestration.orchestrator import full_reasoning
from app.schemas.evidence import EvidenceBundle
from tests.conftest import run


FIXTURE = Path(__file__).parents[1] / "fixtures" / "phase9e_table4_complete.json"
QUESTION = "According to Table 4 in paper 1611.04684v1, which model performs the best for response selection, and how can we tell?"


def _settings() -> Settings:
    return Settings(_env_file=None, model_provider="mock", log_level="WARNING", log_format="console")


def _registry(provider: MockModelProvider) -> tuple[ModelRegistry, Settings]:
    settings = _settings()
    return ModelRegistry(provider, settings), settings


def _plan() -> str:
    return json.dumps(
        {
            "question_type": "lookup",
            "required_modalities": ["table"],
            "tasks": [{"task": "rank Table 4", "modality": "table", "target_references": ["Table 4"]}],
            "target_references": ["Table 4"],
            "requires_cross_modal": False,
            "paper_scope": "single",
            "paper_ids": ["1611.04684v1"],
            "sub_questions": [],
            "confidence": 0.95,
        }
    )


def _complete_bundle() -> EvidenceBundle:
    return EvidenceBundle.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))


def _caption_only_bundle() -> EvidenceBundle:
    return EvidenceBundle.model_validate(
        {
            "query": QUESTION,
            "papers": [{"paper_id": "1611.04684v1"}],
            "evidence": [
                {
                    "evidence_id": "1611.04684v1:elem_004",
                    "paper_id": "1611.04684v1",
                    "type": "table",
                    "content": "Type: Table\nCaption: Table 4: Evaluation results on response selection\nContext:",
                    "caption": "Table 4: Evaluation results on response selection",
                    "reference": "Table 4",
                    "page": None,
                    "metadata": {"table_evidence_status": "caption_only"},
                }
            ],
        }
    )


def test_caption_only_phase9d_failure_returns_unverified_without_assertion() -> None:
    provider = MockModelProvider(responses=[("Query Analyzer", _plan())])
    registry, settings = _registry(provider)

    result = run(full_reasoning(QUESTION, _caption_only_bundle(), "phase9e-caption", settings, registry))

    assert result.answer == "The supplied evidence does not support a verified answer to this question."
    assert result.claims == []
    assert result.citations == []
    assert result.verification_result.status == "unverified"
    assert provider.call_count == 1  # analyzer only; table model was not called


def test_complete_table_fixture_answers_kehnn_and_resolves_table_citation() -> None:
    provider = MockModelProvider(
        responses=[
            ("Query Analyzer", _plan()),
            (
                "Table Reasoning Agent",
                json.dumps(
                    {
                        "findings": [
                            {
                                "claim_id": "cl_kehnn",
                                "kind": "table_comparison",
                                "text": "KEHNN performs best because it has the highest value in every supplied response-selection metric.",
                                "evidence_ids": ["1611.04684v1:elem_004"],
                                "confidence": 0.95,
                            }
                        ]
                    }
                ),
            ),
            (
                "Judge",
                json.dumps(
                    {
                        "verdicts": [
                            {
                                "claim_id": "cl_kehnn",
                                "verdict": "SUPPORTED",
                                "rationale": "KEHNN is highest across the supplied R2@1, R10@1, R10@2, and R10@5 rows.",
                                "evidence_ids_support": ["1611.04684v1:elem_004"],
                                "evidence_ids_contradict": [],
                                "missing_aspects": [],
                            }
                        ]
                    }
                ),
            ),
            ("Answer Generator", json.dumps({"answer": "KEHNN performs best.", "reasoning_summary": "grounded"})),
        ]
    )
    registry, settings = _registry(provider)

    result = run(full_reasoning(QUESTION, _complete_bundle(), "phase9e-complete", settings, registry))

    assert result.answer == "KEHNN performs best."
    assert result.verification_result.status == "supported"
    assert result.claims[0].verification is not None
    assert result.claims[0].verification.verdict == "SUPPORTED"
    assert result.citations[0].evidence_id == "1611.04684v1:elem_004"
    assert result.citations[0].reference == "Table 4"
    assert result.citations[0].page is None
