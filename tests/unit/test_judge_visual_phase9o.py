"""Phase 9O — visual-evidence verification regression suite.

Deterministic Box Alpha → Box Beta fixture plus the seven required cases:
supported visual claim, unsupported visual claim, missing figure bytes,
wrong-paper evidence, unknown evidence IDs, contradictory visual evidence,
invalid image payload, malformed judge output, and legacy text/table paths.
All offline via MockModelProvider (mocked); live matrix runs separately.
"""

from __future__ import annotations

import base64
import io
import json

import pytest

from app.agents.base import AgentContext
from app.agents.judge_answer import JudgeAgent
from app.models.mock import MockModelProvider
from app.prompts.assembly import EvidenceContext
from app.schemas.claims import Claim
from app.schemas.evidence import EvidenceBundle, EvidenceItem, ImageRef
from tests.conftest import run

PNG_1X1 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR4nGNgYGBgAAAABQABDQottQAAAABJRU5ErkJggg=="
)


def _figure_bundle(*, with_bytes: bool = True, paper_id: str = "live_9n_001") -> EvidenceBundle:
    image = ImageRef(b64=PNG_1X1) if with_bytes else None
    return EvidenceBundle(
        evidence=[
            EvidenceItem(
                evidence_id="live_9n_001:fig_p1_02",
                paper_id=paper_id,
                type="figure",
                content="",
                caption="Figure 1: Smoke diagram with two labeled boxes.",
                reference="Figure 1",
                page=None,
                image=image,
            ),
            EvidenceItem(
                evidence_id="live_9n_001:txt_p1_01",
                paper_id=paper_id,
                type="text",
                content="Figure 1 shows Box Alpha feeding Box Beta via a labeled arrow.",
            ),
        ]
    )


def _box_claim(**overrides) -> Claim:
    payload = {
        "claim_id": "cl1",
        "agent": "vision_reasoner",
        "kind": "figure_observation",
        "text": "Box Alpha feeds Box Beta via a labeled arrow.",
        "evidence_ids": ["live_9n_001:fig_p1_02"],
        "confidence": 0.9,
    }
    payload.update(overrides)
    return Claim(**payload)  # type: ignore[arg-type]


def _ctx(bundle: EvidenceBundle) -> AgentContext:
    return AgentContext(
        request_id="t",
        query="Describe Figure 1.",
        evidence=tuple(bundle.evidence),
        model="m",
        provider_name="mock",
    )


def _supported_judge_payload() -> str:
    return json.dumps(
        {
            "verdicts": [
                {
                    "claim_id": "cl1",
                    "verdict": "SUPPORTED",
                    "rationale": "image shows the arrow",
                    "evidence_ids_support": ["live_9n_001:fig_p1_02"],
                }
            ]
        }
    )


class _VisionEchoProvider(MockModelProvider):
    """Records whether the judge call carried image payloads."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saw_images: list[int] = []

    async def chat(self, request):  # type: ignore[override]
        self.saw_images.append(sum(len(m.images) for m in request.messages))
        return await super().chat(request)


# --- 1. supported visual claim ------------------------------------------------


def test_supported_box_alpha_claim_with_image_bytes() -> None:
    provider = _VisionEchoProvider(responses=[("Judge", _supported_judge_payload())])
    bundle = _figure_bundle(with_bytes=True)

    verdicts, agent_run = run(
        JudgeAgent(provider).judge(
            [_box_claim()], bundle, _ctx(bundle),
            vision_model="qwen2.5vl:3b", vision_provider=provider,
        )
    )

    assert agent_run.status == "ok"
    assert verdicts[0].verdict == "SUPPORTED"
    assert any(count > 0 for count in provider.saw_images), "vision judge must receive image bytes"


def test_evidence_block_marks_image_presence_not_bytes() -> None:
    bundle = _figure_bundle(with_bytes=True)
    block = EvidenceContext.from_item(bundle.evidence[0], 3000)

    assert block.image_status == "image: present (base64)"
    from app.prompts.assembly import render_evidence_block

    rendered = render_evidence_block(block)
    assert "image: present (base64)" in rendered
    assert PNG_1X1 not in rendered


def test_caption_only_block_marks_absence() -> None:
    bundle = _figure_bundle(with_bytes=False)
    block = EvidenceContext.from_item(bundle.evidence[0], 3000)

    assert block.image_status == "image: absent — caption only"


# --- 2. unsupported visual claim ----------------------------------------------


def test_unsupported_visual_claim_stays_unsupported() -> None:
    provider = MockModelProvider(
        responses=[
            (
                "Judge",
                json.dumps(
                    {
                        "verdicts": [
                            {
                                "claim_id": "cl1",
                                "verdict": "UNSUPPORTED",
                                "rationale": "image shows two boxes but no arrow labels",
                                "evidence_ids_support": [],
                            }
                        ]
                    }
                ),
            )
        ]
    )
    bundle = _figure_bundle(with_bytes=True)

    verdicts, agent_run = run(
        JudgeAgent(provider).judge(
            [_box_claim()], bundle, _ctx(bundle),
            vision_model="qwen2.5vl:3b", vision_provider=provider,
        )
    )

    assert agent_run.status == "ok"
    assert verdicts[0].verdict == "UNSUPPORTED"


# --- 3. caption-only record cannot support a visual observation ---------------


def test_caption_only_figure_goes_to_text_judge_without_images() -> None:
    provider = _VisionEchoProvider(responses=[("Judge", _supported_judge_payload())])
    bundle = _figure_bundle(with_bytes=False)

    verdicts, agent_run = run(
        JudgeAgent(provider).judge(
            [_box_claim()], bundle, _ctx(bundle),
            vision_model="qwen2.5vl:3b", vision_provider=provider,
        )
    )

    # No image bytes anywhere in the bundle: the vision path must not fire.
    assert all(count == 0 for count in provider.saw_images)
    assert agent_run.status == "ok"


# --- 4. wrong-paper evidence ----------------------------------------------------


def test_wrong_paper_evidence_is_unsupported() -> None:
    bundle = _figure_bundle(with_bytes=True, paper_id="paper_002")
    claim = _box_claim(evidence_ids=["live_9n_001:fig_p1_02"])
    provider = MockModelProvider(
        responses=[
            (
                "Judge",
                json.dumps(
                    {
                        "verdicts": [
                            {
                                "claim_id": "cl1",
                                "verdict": "UNSUPPORTED",
                                "rationale": "cited id belongs to another paper",
                                "evidence_ids_support": [],
                            }
                        ]
                    }
                ),
            )
        ]
    )

    verdicts, agent_run = run(
        JudgeAgent(provider).judge(
            [claim], bundle, _ctx(bundle),
            vision_model="qwen2.5vl:3b", vision_provider=provider,
        )
    )

    assert verdicts[0].verdict == "UNSUPPORTED"


# --- 5. unknown evidence IDs -----------------------------------------------------


def test_unknown_evidence_id_fails_closed() -> None:
    bundle = _figure_bundle(with_bytes=True)
    claim = _box_claim(evidence_ids=["e_ghost"])
    provider = MockModelProvider()

    verdicts, agent_run = run(
        JudgeAgent(provider).judge(
            [claim], bundle, _ctx(bundle),
            vision_model="qwen2.5vl:3b", vision_provider=provider,
        )
    )

    assert agent_run.status == "ok"
    assert verdicts[0].verdict == "UNSUPPORTED"
    assert verdicts[0].verifier == "deterministic"


# --- 6. contradictory visual evidence --------------------------------------------


def test_contradictory_visual_claim_is_contradicted() -> None:
    bundle = _figure_bundle(with_bytes=True)
    claim = _box_claim(text="Box Beta feeds Box Alpha (reversed).")
    provider = MockModelProvider(
        responses=[
            (
                "Judge",
                json.dumps(
                    {
                        "verdicts": [
                            {
                                "claim_id": "cl1",
                                "verdict": "CONTRADICTED",
                                "rationale": "arrow points Alpha to Beta",
                                "evidence_ids_support": [],
                                "evidence_ids_contradict": ["live_9n_001:fig_p1_02"],
                            }
                        ]
                    }
                ),
            )
        ]
    )

    verdicts, agent_run = run(
        JudgeAgent(provider).judge(
            [claim], bundle, _ctx(bundle),
            vision_model="qwen2.5vl:3b", vision_provider=provider,
        )
    )

    assert verdicts[0].verdict == "CONTRADICTED"
    assert verdicts[0].evidence_ids_contradict == ["live_9n_001:fig_p1_02"]


# --- 7. invalid image payload degrades, text judge decides -------------------------


def test_invalid_image_payload_falls_back_to_text_judge() -> None:
    from app.schemas.evidence import ImageRef as _ImageRef

    bundle = EvidenceBundle(
        evidence=[
            EvidenceItem(
                evidence_id="live_9n_001:fig_p1_02",
                paper_id="live_9n_001",
                type="figure",
                content="",
                caption="Figure 1",
                image=_ImageRef(b64="!!!not-valid-base64!!!"),
            )
        ]
    )
    provider = _VisionEchoProvider(responses=[("Judge", _supported_judge_payload())])

    verdicts, agent_run = run(
        JudgeAgent(provider).judge(
            [_box_claim()], bundle, _ctx(bundle),
            vision_model="qwen2.5vl:3b", vision_provider=provider,
        )
    )

    assert all(count == 0 for count in provider.saw_images)
    assert agent_run.status == "ok"


# --- 8. malformed judge output ------------------------------------------------------


def test_malformed_vision_judge_output_fails_closed() -> None:
    provider = MockModelProvider(responses=[("Judge", "not json at all")])
    bundle = _figure_bundle(with_bytes=True)

    verdicts, agent_run = run(
        JudgeAgent(provider).judge(
            [_box_claim()], bundle, _ctx(bundle),
            vision_model="qwen2.5vl:3b", vision_provider=provider,
        )
    )

    assert verdicts == []
    assert agent_run.status == "error"


# --- 9. legacy text/table paths unchanged ----------------------------------------------


def test_text_claim_never_takes_vision_path() -> None:
    provider = _VisionEchoProvider(
        responses=[
            (
                "Judge",
                json.dumps(
                    {
                        "verdicts": [
                            {
                                "claim_id": "clt",
                                "verdict": "SUPPORTED",
                                "evidence_ids_support": ["live_9n_001:txt_p1_01"],
                            }
                        ]
                    }
                ),
            )
        ]
    )
    bundle = _figure_bundle(with_bytes=True)
    claim = Claim(
        claim_id="clt",
        agent="text_reasoner",
        kind="author_claim",  # type: ignore[arg-type]
        text="Figure 1 shows Box Alpha feeding Box Beta.",
        evidence_ids=["live_9n_001:txt_p1_01"],
        confidence=0.9,
    )

    verdicts, agent_run = run(
        JudgeAgent(provider).judge(
            [claim], bundle, _ctx(bundle),
            vision_model="qwen2.5vl:3b", vision_provider=provider,
        )
    )

    assert all(count == 0 for count in provider.saw_images)
    assert verdicts[0].verdict == "SUPPORTED"
