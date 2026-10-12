"""Phase 9K Stage 2 — vision preprocessing + provider wiring.

Covers: longest-side downscale with aspect-ratio preservation, no-upscale
for small images, corrupt/oversize handling, vision payload omits ``options``
while text payload keeps them, missing-model degradation, caption-only
evidence never becoming a visual observation, unsupported visual claims
staying unsupported.
"""

from __future__ import annotations

import base64
import io

import pytest

from app.config import Settings
from app.core.errors import EvidenceInvalidError, PayloadTooLargeError
from app.evidence.images import (
    VISION_MAX_SIDE_PX,
    decode_validate_and_preprocess_b64,
    encode_file_for_vision,
    preprocess_for_vision,
)

PIL = pytest.importorskip("PIL.Image", reason="Pillow required for preprocessing tests")
from PIL import Image  # noqa: E402  # type: ignore[import-not-found]


def _settings(**overrides) -> Settings:
    base = {"_env_file": None}
    base.update(overrides)
    return Settings(**base)  # type: ignore[call-arg]


def _png_bytes(size: tuple[int, int], color: tuple[int, int, int] = (10, 20, 30)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# --- preprocessing ----------------------------------------------------------


def test_large_image_is_downscaled_preserving_aspect_ratio():
    data = _png_bytes((4617, 1674))
    out, mime, original, new_size = preprocess_for_vision(data, ".png")

    assert original == (4617, 1674)
    assert max(new_size) == VISION_MAX_SIDE_PX
    assert mime == "image/png"
    # Aspect ratio preserved within a pixel of rounding
    assert abs(new_size[0] / new_size[1] - 4617 / 1674) < 0.01
    with Image.open(io.BytesIO(out)) as im:
        assert im.size == new_size
        assert max(im.size) <= VISION_MAX_SIDE_PX


def test_small_image_is_not_upscaled():
    data = _png_bytes((400, 300))
    out, _, original, new_size = preprocess_for_vision(data, ".png")

    assert original == (400, 300)
    assert new_size == (400, 300)
    with Image.open(io.BytesIO(out)) as im:
        assert im.size == (400, 300)


def test_boundary_image_at_limit_passes_through():
    data = _png_bytes((VISION_MAX_SIDE_PX, 400))
    _, _, _, new_size = preprocess_for_vision(data, ".png")

    assert new_size == (VISION_MAX_SIDE_PX, 400)


def test_corrupt_bytes_raise_evidence_invalid():
    with pytest.raises(EvidenceInvalidError):
        preprocess_for_vision(b"this is not an image", ".png")


def test_oversized_bytes_raise_before_decoding():
    settings = _settings(max_image_bytes=1024)
    with pytest.raises(PayloadTooLargeError):
        from app.evidence.images import validate_image_bytes

        validate_image_bytes(b"\x00" * 2048, ".png", settings)


def test_b64_end_to_end_preprocess_roundtrip():
    data = _png_bytes((2000, 1000))
    settings = _settings()
    out_b64, mime, original, new_size = decode_validate_and_preprocess_b64(_b64(data), settings)

    assert mime == "image/png"
    assert original == (2000, 1000)
    assert max(new_size) == VISION_MAX_SIDE_PX
    decoded = base64.b64decode(out_b64)
    with Image.open(io.BytesIO(decoded)) as im:
        assert max(im.size) <= VISION_MAX_SIDE_PX


def test_invalid_b64_raises():
    with pytest.raises(EvidenceInvalidError):
        decode_validate_and_preprocess_b64("!!!not-base64!!!", _settings())


def test_encode_file_for_vision_reads_and_downscales(tmp_path):
    from pathlib import Path

    raw = _png_bytes((3136, 1000))
    path = Path(tmp_path) / "fig.png"
    path.write_bytes(raw)
    b64, mime, original, new_size = encode_file_for_vision(path, _settings())

    assert mime == "image/png"
    assert original == (3136, 1000)
    assert max(new_size) == VISION_MAX_SIDE_PX
    assert base64.b64decode(b64)


# --- provider wiring: options omitted for vision, kept for text --------------


def test_ollama_payload_omits_options_with_images_keeps_for_text():
    from app.models.base import ChatMessage, ChatRequest, ImagePayload
    from app.models.ollama import OllamaModelProvider

    vision_req = ChatRequest(
        model="qwen2.5vl:3b",
        messages=[
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="user", content="q", images=[ImagePayload(b64="QUJD")]),
        ],
        temperature=0.0,
        max_tokens=512,
        response_format="json",
    )
    vision_payload = OllamaModelProvider._payload(vision_req)
    assert vision_payload["messages"][1]["images"] == ["QUJD"]
    assert "options" not in vision_payload

    text_req = ChatRequest(
        model="qwen2.5:1.5b",
        messages=[ChatMessage(role="user", content="plain")],
        temperature=0.2,
        max_tokens=128,
    )
    text_payload = OllamaModelProvider._payload(text_req)
    assert text_payload["options"] == {"temperature": 0.2, "num_predict": 128}


# --- agent-level behavior -----------------------------------------------------


def test_processed_bytes_reach_provider_not_raw_source():
    """VisionAgent forwards the downscaled copy (proves actual bytes flow)."""
    import asyncio

    from app.agents.base import AgentContext
    from app.agents.vision_agent import VisionAgent
    from app.models.mock import MockModelProvider
    from app.schemas.evidence import EvidenceItem, ImageRef

    big = _png_bytes((3000, 1200))
    captured: dict = {}

    class CapturingProvider(MockModelProvider):
        async def chat(self, request):  # type: ignore[override]
            for message in request.messages:
                if message.images:
                    captured["b64"] = message.images[0].b64
            return await super().chat(request)

    provider = CapturingProvider(
        responses=[
            (
                "Vision",
                '{"findings": [{"claim_id": "cl1", "kind": "figure_observation", '
                '"text": "Seen.", "evidence_ids": ["e_fig"], "confidence": 0.7}]}',
            )
        ]
    )
    item = EvidenceItem(
        evidence_id="e_fig",
        paper_id="paper_001",
        type="figure",
        content="",
        caption="Figure 1: X",
        image=ImageRef(b64=_b64(big)),
    )
    ctx = AgentContext(
        request_id="t", query="Q", evidence=(item,), model="qwen2.5vl:3b", provider_name="mock"
    )
    claims, run = asyncio.run(VisionAgent(provider).run_for_evidence(ctx))

    assert claims and run.status in {"ok", "partial"}
    sent = base64.b64decode(captured["b64"])
    assert len(sent) < len(big), "downscaled copy must be smaller than the source"
    with Image.open(io.BytesIO(sent)) as im:
        assert max(im.size) <= VISION_MAX_SIDE_PX


def test_caption_only_evidence_is_no_evidence():
    import asyncio

    from app.agents.base import AgentContext
    from app.agents.vision_agent import VisionAgent
    from app.models.mock import MockModelProvider
    from app.schemas.evidence import EvidenceItem

    item = EvidenceItem(
        evidence_id="e_cap",
        paper_id="paper_001",
        type="figure",
        content="",
        caption="Figure 1: X",
    )
    ctx = AgentContext(
        request_id="t", query="Q", evidence=(item,), model="qwen2.5vl:3b", provider_name="mock"
    )
    claims, run = asyncio.run(
        VisionAgent(MockModelProvider()).run_for_evidence(ctx)
    )

    assert claims == []
    assert run.status == "no_evidence"


def test_missing_model_surfaces_as_error_not_crash():
    import asyncio
    import json

    from app.agents.base import AgentContext
    from app.agents.vision_agent import VisionAgent
    from app.models.mock import MockModelProvider
    from app.schemas.evidence import EvidenceItem, ImageRef

    small = _png_bytes((100, 100))
    item = EvidenceItem(
        evidence_id="e_fig",
        paper_id="paper_001",
        type="figure",
        content="",
        caption="Figure 1: X",
        image=ImageRef(b64=_b64(small)),
    )
    provider = MockModelProvider(
        fail_times=99,
        responses=[("Vision", json.dumps({"findings": []}))],
    )
    ctx = AgentContext(
        request_id="t", query="Q", evidence=(item,), model="qwen2.5vl:3b", provider_name="mock"
    )
    claims, run = asyncio.run(VisionAgent(provider).run_for_evidence(ctx))

    assert claims == []
    assert run.status == "error"
    assert run.error is not None


def test_unsupported_visual_claim_stays_unsupported():
    import asyncio
    import json

    from app.agents.base import AgentContext
    from app.agents.judge_answer import JudgeAgent
    from app.models.mock import MockModelProvider
    from app.schemas.claims import Claim
    from app.schemas.evidence import EvidenceBundle

    claim = Claim(
        claim_id="cl_v",
        agent="vision_reasoner",
        kind="figure_observation",  # type: ignore[arg-type]
        text="The value drops exactly from 83.17 to 61.24.",
        evidence_ids=["e_fig"],
        confidence=0.9,
    )
    bundle = EvidenceBundle(
        evidence=[
            {
                "evidence_id": "e_fig",
                "paper_id": "paper_001",
                "type": "figure",
                "content": "",
                "caption": "Figure 1: trend",
            }
        ]
    )
    provider = MockModelProvider(
        responses=[
            (
                "Judge",
                json.dumps(
                    {
                        "verdicts": [
                            {
                                "claim_id": "cl_v",
                                "verdict": "UNSUPPORTED",
                                "rationale": "no legible numbers",
                                "evidence_ids_support": [],
                                "evidence_ids_contradict": [],
                                "missing_aspects": ["exact values"],
                            }
                        ]
                    }
                ),
            )
        ]
    )
    ctx = AgentContext(
        request_id="t", query="Q", evidence=tuple(bundle.evidence), model="m", provider_name="mock"
    )
    verdicts, run = asyncio.run(JudgeAgent(provider).judge([claim], bundle, ctx))

    assert verdicts[0].verdict == "UNSUPPORTED"
    assert run.status == "ok"
