"""Ensure figure and text judge groups retain both verdict sets."""

from __future__ import annotations

import json

from app.agents.base import AgentContext
from app.agents.judge_answer import JudgeAgent
from app.models.mock import MockModelProvider
from app.schemas.claims import Claim
from app.schemas.evidence import EvidenceBundle, EvidenceItem, ImageRef
from tests.conftest import run


PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR4nGNgYGBgAAAABQABDQottQAAAABJRU5ErkJggg=="


def test_mixed_figure_and_text_judge_verdicts_are_preserved():
    figure_id = "p:figure"
    text_id = "p:text"
    bundle = EvidenceBundle(
        evidence=[
            EvidenceItem(
                evidence_id=figure_id,
                paper_id="p",
                type="figure",
                caption="Figure 1: architecture",
                image=ImageRef(b64=PNG),
            ),
            EvidenceItem(evidence_id=text_id, paper_id="p", type="text", content="The method uses two stages."),
        ]
    )
    claims = [
        Claim(
            claim_id="figure_claim",
            agent="vision_reasoner",
            kind="figure_observation",
            text="The figure has two stages.",
            evidence_ids=[figure_id],
            confidence=0.8,
        ),
        Claim(
            claim_id="text_claim",
            agent="text_reasoner",
            kind="author_claim",
            text="The method uses two stages.",
            evidence_ids=[text_id],
            confidence=0.8,
        ),
    ]
    first = json.dumps(
        {
            "verdicts": [
                {
                    "claim_id": "figure_claim",
                    "verdict": "SUPPORTED",
                    "rationale": "visible",
                    "evidence_ids_support": [figure_id],
                }
            ]
        }
    )
    second = json.dumps(
        {
            "verdicts": [
                {
                    "claim_id": "text_claim",
                    "verdict": "SUPPORTED",
                    "rationale": "stated",
                    "evidence_ids_support": [text_id],
                }
            ]
        }
    )

    class SequencedProvider(MockModelProvider):
        async def chat(self, request):  # type: ignore[override]
            response = await super().chat(request)
            if self.call_count == 1:
                self._responses = [("Judge", second)]
            return response

    provider = SequencedProvider(responses=[("Judge", first)])
    ctx = AgentContext(
        request_id="mixed",
        query="Explain the figure and method.",
        evidence=tuple(bundle.evidence),
        model="judge",
        provider_name="mock",
    )

    verdicts, run_record = run(
        JudgeAgent(provider).judge(
            claims,
            bundle,
            ctx,
            vision_model="vision",
            vision_provider=provider,
        )
    )

    assert run_record.status == "ok"
    assert {verdict.claim_id for verdict in verdicts} == {"figure_claim", "text_claim"}
