"""Offline fixture dataset (7 categories — not a benchmark).

Built from ``tests/fixtures/mock_evidence.json`` so the fixture cases are
perfectly frozen evidence bundles the pipeline already consumes.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.schemas.evidence import EvidenceBundle
from evaluation.datasets.eval_case import EvalCase, EvalDataset, GoldAnswer


FIXTURE_PATH = Path(__file__).parent / ".." / ".." / "tests" / "fixtures" / "mock_evidence.json"
OUT_PATH = Path(__file__).parent / "fixture-mini.json"


def _bundle_for_ids(source: EvidenceBundle, keep: list[str]) -> EvidenceBundle:
    items = [item for item in source.evidence if item.evidence_id in keep]
    papers = [paper for paper in source.papers if paper.paper_id in {item.paper_id for item in items}]
    return EvidenceBundle(
        query=source.query,
        papers=papers,
        evidence=items,
        retrieval=source.retrieval,
        warnings=list(source.warnings),
    )


def build(out: Path = OUT_PATH, fixture_path: Path = FIXTURE_PATH) -> EvalDataset:
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    full = EvidenceBundle.model_validate(raw)

    # The fixture evidence ids:
    # e_p001_p1_abs   (Abstract text)
    # e_p001_p4_s42   (Section 4.2 Setup)
    # e_p001_p6_limit (Section 6 Limitations)
    # e_p001_p7_t3    (Table 3)
    # e_p001_p8_f5    (Figure 5)
    # e_p002_p5_t2    (Table 2 across papers)
    # e_p002_p9_concl (Conclusion multi-paper)

    by_id = {item.evidence_id: item for item in full.evidence}

    cases = [
        EvalCase(
            case_id="fixture_text",
            question="What is the evaluation split used?",
            category="text",
            evidence=_bundle_for_ids(full, ["e_p001_p4_s42", "e_p001_p1_abs"]),
            papers=["paper_001"],
            gold_answer=GoldAnswer(text="development split", alternatives=["dev split"]),
            gold_evidence_ids=["e_p001_p4_s42"],
            answer_type="free",
        ),
        EvalCase(
            case_id="fixture_table",
            question="Which method performed best in Table 3?",
            category="table",
            evidence=_bundle_for_ids(full, ["e_p001_p7_t3", "e_p001_p4_s42"]),
            papers=["paper_001"],
            gold_answer=GoldAnswer(text="Ours"),
            gold_evidence_ids=["e_p001_p7_t3"],
            answer_type="span",
        ),
        EvalCase(
            case_id="fixture_figure",
            question="Describe the trend in Figure 5.",
            category="figure",
            evidence=_bundle_for_ids(full, ["e_p001_p8_f5", "e_p001_p4_s42"]),
            papers=["paper_001"],
            gold_answer=GoldAnswer(text="peaks around 8k and then declines"),
            gold_evidence_ids=["e_p001_p8_f5"],
            answer_type="free",
        ),
        EvalCase(
            case_id="fixture_text_table",
            question="Compare Table 3 results with the setup description.",
            category="text_table",
            evidence=_bundle_for_ids(full, ["e_p001_p4_s42", "e_p001_p7_t3"]),
            papers=["paper_001"],
            gold_answer=GoldAnswer(text="Ours 91.4 vs Baseline-A 84.2 on the dev split"),
            gold_evidence_ids=["e_p001_p4_s42", "e_p001_p7_t3"],
            answer_type="free",
        ),
        EvalCase(
            case_id="fixture_text_figure",
            question="Does Figure 5 support the discussion in Section 4.2?",
            category="text_figure",
            evidence=_bundle_for_ids(full, ["e_p001_p4_s42", "e_p001_p8_f5"]),
            papers=["paper_001"],
            gold_answer=GoldAnswer(text="yes, it shows the diminishing return beyond 8k described in Section 4.2"),
            gold_evidence_ids=["e_p001_p4_s42", "e_p001_p8_f5"],
            answer_type="free",
        ),
        EvalCase(
            case_id="fixture_table_figure",
            question="Compare the Table 3 results with the Figure 5 trend.",
            category="table_figure",
            evidence=_bundle_for_ids(full, ["e_p001_p7_t3", "e_p001_p8_f5"]),
            papers=["paper_001"],
            gold_answer=GoldAnswer(text="Table 3: Ours highest at 91.4; Figure 5: F1 peaks around 8k"),
            gold_evidence_ids=["e_p001_p7_t3", "e_p001_p8_f5"],
            answer_type="free",
        ),
        EvalCase(
            case_id="fixture_multi_paper",
            question="Does DenseFusion outperform SparseCtx on the same metric?",
            category="multi_paper",
            evidence=_bundle_for_ids(full, ["e_p001_p7_t3", "e_p002_p5_t2", "e_p002_p9_concl"]),
            papers=["paper_001", "paper_002"],
            answer_type="free",
            gold_answer=GoldAnswer(text="no, SparseCtx is higher (90.6 vs 89.1) in the provided evidence"),
            gold_evidence_ids=["e_p002_p5_t2", "e_p002_p9_concl"],
        ),
    ]

    dataset = EvalDataset(
        name="fixture-mini",
        version="0.1.0",
        cases=cases,
        manifest={"source": "tests/fixtures/mock_evidence.json", "note": "test fixture only, not SPIQA nor ResearchLens-XM"},
    )
    return dataset


def main(out: Path = OUT_PATH, fixture_path: Path = FIXTURE_PATH) -> None:
    dataset = build(out=out, fixture_path=fixture_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dataset.model_dump_json(indent=2), encoding="utf-8")
    print(f"wrote {len(dataset.cases)} cases to {out}")


if __name__ == "__main__":
    main()
