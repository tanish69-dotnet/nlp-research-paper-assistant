"""Judge context-window regression tests.

The live failure these cover::

    request (5027 tokens) exceeds the available context size (4096 tokens)

A figure question produced a vision claim and several text claims; the Judge
rendered the whole scoped bundle for both modality groups and Ollama rejected
the text request before generation.  These tests pin the behaviour that keeps
every Judge request inside the configured budget while preserving provenance
(evidence ids), claim text and the mixed text/vision grouping.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.agents.base import AgentContext
from app.agents.judge_answer import JudgeAgent
from app.core.tokens import estimate_messages_tokens
from app.models.mock import MockModelProvider
from app.schemas.claims import Claim
from app.schemas.evidence import EvidenceBundle, EvidenceItem, ImageRef, TableData
from tests.conftest import run

PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR4nGNgYGBgAAAABQAB"
    "DQottQAAAABJRU5ErkJggg=="
)

_CLAIM_PATTERN = re.compile(
    r"claim_id=(\S+) agent=\S+ kind=\S+ confidence=\d+\.\d+ evidence_ids=\['([^']+)'\]"
)


class RecordingProvider(MockModelProvider):
    """Mock provider that records the exact prompt of every call."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.prompts: list[str] = []
        self.image_counts: list[int] = []

    async def chat(self, request):  # type: ignore[override]
        self.prompts.append("\n".join(message.content for message in request.messages))
        self.image_counts.append(
            sum(len(message.images or []) for message in request.messages)
        )
        return await super().chat(request)

    @property
    def prompt_token_estimates(self) -> list[int]:
        return [estimate_messages_tokens([prompt]) for prompt in self.prompts]


class VerdictProvider(RecordingProvider):
    """Records prompts and answers with one SUPPORTED verdict per input claim."""

    def _build_text(self, request):  # type: ignore[override]
        prompt = self._prompt_text(request)
        if "Judge" in prompt:
            pairs = _CLAIM_PATTERN.findall(prompt)
            return json.dumps(
                {
                    "verdicts": [
                        {
                            "claim_id": claim_id,
                            "verdict": "SUPPORTED",
                            "rationale": "entailed by the supplied evidence",
                            "evidence_ids_support": [evidence_id],
                        }
                        for claim_id, evidence_id in pairs
                    ]
                }
            )
        return super()._build_text(request)


def _text_item(evidence_id: str, *, chars: int = 40_000) -> EvidenceItem:
    body = (
        "The InteRFeX array was deployed at the Nova Systems Space Precinct and the "
        "experiment reports the measured sensitivity for each of the eight channels. "
    )
    return EvidenceItem(
        evidence_id=evidence_id,
        paper_id="paper",
        type="text",
        content=(body * (chars // len(body) + 1))[:chars],
        reference="Section 3",
        page=2,
    )


def _figure_item(evidence_id: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        paper_id="paper",
        type="figure",
        content="",
        caption="Figure 1: shows the InteRFeX array as deployed at the Nova Systems Space Precinct, Peterborough, Australia.",
        reference="Figure 1",
        page=2,
        image=ImageRef(b64=PNG_B64),
    )


def _ctx(bundle: EvidenceBundle) -> AgentContext:
    return AgentContext(
        request_id="judge-budget",
        query="Explain Figure 1 and describe what it demonstrates. Cite the supporting evidence.",
        evidence=tuple(bundle.evidence),
        model="qwen2.5:1.5b",
        provider_name="mock",
    )


def _claim(claim_id: str, evidence_id: str, *, kind: str = "author_claim", agent: str = "text_reasoner") -> Claim:
    return Claim(
        claim_id=claim_id,
        agent=agent,
        kind=kind,  # type: ignore[arg-type]
        text="Figure 1 shows the InteRFeX array deployed at the Nova Systems Space Precinct in Peterborough, Australia.",
        evidence_ids=[evidence_id],
        confidence=0.8,
    )


def test_oversized_judge_prompt_is_shrunk_to_the_budget() -> None:
    """A 40k-char evidence item must not push the Judge past its budget."""

    bundle = EvidenceBundle(evidence=[_text_item("e_big")])
    provider = VerdictProvider()
    ctx = _ctx(bundle)

    verdicts, run_record = run(
        JudgeAgent(provider).judge(
            [_claim("cl1", "e_big")],
            bundle,
            ctx,
            max_chars_per_item=40_000,
            prompt_budget_tokens=1_250,
            min_chars_per_item=100,
            max_caption_chars=80,
        )
    )

    assert run_record.status == "ok"
    assert len(provider.prompts) == 1
    assert provider.prompt_token_estimates[0] <= 1_250
    # The excerpt shrank, but the evidence id and claim text survived intact.
    assert "e_big" in provider.prompts[0]
    assert "Nova Systems Space Precinct" in provider.prompts[0]
    assert verdicts[0].verdict == "SUPPORTED"
    assert verdicts[0].evidence_ids_support == ["e_big"]


def test_budget_is_enforced_for_every_call_when_claims_are_batched() -> None:
    """Too many claims for one request must be split, never truncated."""

    items = [_text_item(f"e{i}", chars=6_000) for i in range(6)]
    bundle = EvidenceBundle(evidence=items)
    provider = VerdictProvider()
    ctx = _ctx(bundle)
    claims = [_claim(f"cl{i}", f"e{i}") for i in range(6)]

    verdicts, run_record = run(
        JudgeAgent(provider).judge(
            claims,
            bundle,
            ctx,
            max_chars_per_item=3_000,
            prompt_budget_tokens=1_300,
            min_chars_per_item=200,
            max_caption_chars=80,
        )
    )

    assert run_record.status == "ok"
    assert len(provider.prompts) > 1  # split, not truncated
    assert all(tokens <= 1_300 for tokens in provider.prompt_token_estimates)
    assert {verdict.claim_id for verdict in verdicts} == {f"cl{i}" for i in range(6)}
    assert all(verdict.verdict == "SUPPORTED" for verdict in verdicts)
    # Every batch saw exactly the evidence its own claims cite.
    for prompt in provider.prompts:
        cited = set(re.findall(r"evidence_ids=\['([^']+)'\]", prompt))
        for evidence_id in cited:
            assert f"--- EVIDENCE {evidence_id} " in prompt


def test_each_modality_group_gets_its_own_budgeted_request() -> None:
    """Mixed figure/text claims keep both verdict sets and stay in budget."""

    bundle = EvidenceBundle(
        evidence=[_figure_item("e_fig"), _text_item("e_txt", chars=40_000)]
    )
    provider = VerdictProvider()
    ctx = _ctx(bundle)
    claims = [
        _claim("figure_claim", "e_fig", kind="figure_observation", agent="vision_reasoner"),
        _claim("text_claim", "e_txt"),
    ]

    verdicts, run_record = run(
        JudgeAgent(provider).judge(
            claims,
            bundle,
            ctx,
            vision_model="qwen2.5vl:3b",
            vision_provider=provider,
            max_chars_per_item=40_000,
            prompt_budget_tokens=1_400,
            vision_prompt_budget_tokens=1_300,
            min_chars_per_item=100,
            max_caption_chars=80,
        )
    )

    assert run_record.status == "ok"
    assert {verdict.claim_id for verdict in verdicts} == {"figure_claim", "text_claim"}
    assert len(provider.prompts) == 2
    # The figure request carries the image and only the figure evidence; the
    # text request carries neither.
    assert provider.image_counts[0] == 1
    assert "e_fig" in provider.prompts[0]
    assert "e_txt" not in provider.prompts[0]
    assert provider.image_counts[1] == 0
    assert "e_txt" in provider.prompts[1]
    assert "e_fig" not in provider.prompts[1]
    assert provider.prompt_token_estimates[1] <= 1_400
    assert provider.prompt_token_estimates[0] <= 1_300


def test_table_grounding_and_citation_ids_survive_budgeting() -> None:
    """Structured table evidence and its ids must be preserved, not dropped."""

    table = EvidenceItem(
        evidence_id="e_tab",
        paper_id="paper",
        type="table",
        content="| Model | R2@1 |\n|---|---:|\n| KEHNN | 0.786 |\n| LSTM | 0.725 |",
        table_data=TableData(
            headers=["Model", "R2@1"],
            rows=[["KEHNN", "0.786"], ["LSTM", "0.725"]],
            caption="Table 4: Evaluation results",
        ),
        caption="Table 4: Evaluation results",
        reference="Table 4",
        page=5,
    )
    bundle = EvidenceBundle(evidence=[table])
    provider = VerdictProvider()
    ctx = _ctx(bundle)
    claim = Claim(
        claim_id="cl_tab",
        agent="table_reasoner",
        kind="table_comparison",  # type: ignore[arg-type]
        text="KEHNN performs best with the highest R2@1 value of 0.786.",
        evidence_ids=["e_tab"],
        confidence=0.9,
    )

    verdicts, run_record = run(
        JudgeAgent(provider).judge(
            [claim],
            bundle,
            ctx,
            prompt_budget_tokens=1_500,
            min_chars_per_item=100,
        )
    )

    assert run_record.status == "ok"
    assert provider.prompt_token_estimates[0] <= 1_500
    assert "table_data:" in provider.prompts[0]
    assert "KEHNN | 0.786" in provider.prompts[0]
    assert "reference: Table 4" in provider.prompts[0]
    assert "page: 5" in provider.prompts[0]
    assert verdicts[0].evidence_ids_support == ["e_tab"]


def test_unsupported_verdict_is_preserved_through_budgeting() -> None:
    bundle = EvidenceBundle(evidence=[_text_item("e_txt", chars=20_000)])
    provider = RecordingProvider(
        responses=[
            (
                "Judge",
                json.dumps(
                    {
                        "verdicts": [
                            {
                                "claim_id": "cl1",
                                "verdict": "UNSUPPORTED",
                                "rationale": "the evidence is silent",
                                "evidence_ids_support": [],
                            }
                        ]
                    }
                ),
            )
        ]
    )
    ctx = _ctx(bundle)

    verdicts, run_record = run(
        JudgeAgent(provider).judge(
            [_claim("cl1", "e_txt")],
            bundle,
            ctx,
            max_chars_per_item=20_000,
            prompt_budget_tokens=1_250,
            min_chars_per_item=100,
        )
    )

    assert run_record.status == "ok"
    assert verdicts[0].verdict == "UNSUPPORTED"


def test_malformed_model_output_still_fails_gracefully() -> None:
    bundle = EvidenceBundle(evidence=[_text_item("e_txt", chars=8_000)])
    provider = RecordingProvider(responses=[("Judge", "this is not json")])
    ctx = _ctx(bundle)

    verdicts, run_record = run(
        JudgeAgent(provider).judge(
            [_claim("cl1", "e_txt")],
            bundle,
            ctx,
            max_chars_per_item=8_000,
            prompt_budget_tokens=1_250,
            min_chars_per_item=100,
        )
    )

    assert run_record.status == "error"
    assert verdicts == []
    assert run_record.error is not None
    assert len(provider.prompts) == 2  # original + JSON-repair retry, both well-formed


def test_provider_context_overflow_triggers_a_smaller_retry() -> None:
    """The provider outranks the estimator: an overflow is retried, not fatal."""

    bundle = EvidenceBundle(evidence=[_text_item("e_txt", chars=40_000)])
    ctx = _ctx(bundle)

    class OverflowOnceProvider(VerdictProvider):
        def __init__(self) -> None:
            super().__init__()
            self.failed = False

        async def chat(self, request):  # type: ignore[override]
            if not self.failed:
                self.failed = True
                self.prompts.append("\n".join(m.content for m in request.messages))
                raise RuntimeError(
                    "ollama returned HTTP 400: request (5027 tokens) exceeds the "
                    "available context size (4096 tokens)"
                )
            return await super().chat(request)

    provider = OverflowOnceProvider()

    verdicts, run_record = run(
        JudgeAgent(provider).judge(
            [_claim("cl1", "e_txt")],
            bundle,
            ctx,
            max_chars_per_item=40_000,
            prompt_budget_tokens=4_000,
            min_chars_per_item=100,
        )
    )

    assert run_record.status == "ok"
    assert len(provider.prompts) == 2
    assert provider.prompt_token_estimates[1] < provider.prompt_token_estimates[0]
    assert verdicts[0].verdict == "SUPPORTED"


def test_irreducible_single_claim_overflow_fails_closed_with_prompt_too_long() -> None:
    bundle = EvidenceBundle(evidence=[_text_item("e_txt", chars=40_000)])
    ctx = _ctx(bundle)
    # A budget smaller than the fixed template cannot be satisfied by shrinking
    # one claim's evidence; the judge must fail closed rather than send it.
    provider = VerdictProvider()

    verdicts, run_record = run(
        JudgeAgent(provider).judge(
            [_claim("cl1", "e_txt")],
            bundle,
            ctx,
            prompt_budget_tokens=256,
            min_chars_per_item=100,
        )
    )

    assert verdicts == []
    assert run_record.status == "error"
    assert provider.prompts == []  # nothing oversized was ever sent
