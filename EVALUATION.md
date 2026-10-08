# EVALUATION — ResearchLens Reasoning Module (Person 3)

| Field | Value |
|---|---|
| Status | Draft v0.1 — protocol definition; **no results exist yet** |
| Rule | **Never invent results.** Every number in the final paper must come from a run directory under `evaluation/results/` with its config, model versions and seed. |

---

## 1. Research question & hypotheses

> **RQ:** Does multi-LLM collaborative reasoning and verification improve the accuracy and
> factual grounding of multimodal RAG for scientific paper question answering?

| ID | Hypothesis | Tested by |
|---|---|---|
| H1 | Multimodal evidence (tables+figures as first-class) improves answer correctness over text-only RAG | A vs B |
| H2 | Specialized multi-LLM agents improve correctness over a single LLM on multimodal evidence | B vs C |
| H3 | Adding a judge/verifier reduces hallucination and citation errors (possibly at small cost to coverage) | C vs D |
| H4 | Each modality agent contributes: removing table/vision agent degrades its modality's accuracy | ablation |
| H5 | Judge adds measurable value beyond its latency cost | ablation (judge off) |
| H6 | Gains hold per question category (table, figure, cross-modal, multi-paper) | slice analysis |

Secondary engineering RQs: latency cost per stage; agent agreement vs accuracy; when does
degradation (fallback) trigger and does it correlate with error?

## 2. Experimental systems

| System | Evidence | Reasoning | Judge |
|---|---|---|---|
| **A — Baseline** | text-only retrieval (flat chunks) | single LLM, single prompt | ✗ |
| **B** | multimodal (text+table+figure) | single LLM, single prompt | ✗ |
| **C** | multimodal | multi-LLM specialized agents (text/table/vision) + generator | ✗ |
| **D (ours)** | multimodal | multi-LLM agents + generator | ✓ deterministic + LLM judge |

Implementation: the *same* codebase runs all four, switched by `evaluation/configs/system_{A,B,C,D}.yaml`
(`evidence_mode: text_only`, `agents: [generic]` vs `[text, table, vision]`, `judge: off/on`).
This controls for prompt/model differences — only the architecture varies.

**Controls:** identical retrieval results across systems for a given question (freeze the
evidence bundle per question — `evidence_frozen=True`), identical model where the system
permits (same text model for A–D), temperature 0 / fixed seed, single hardware profile.

## 3. Ablations

| Ablation | Removed | Expectation to test |
|---|---|---|
| AB-T | Text Agent | drop on text/definition/causal questions |
| AB-Tab | Table Agent | drop on numeric/table questions (largest for Table-slice) |
| AB-V | Vision Agent | drop on figure/trend questions |
| AB-J | Judge | hallucination ↑, citation errors ↑, latency ↓ |
| AB-O | Multi-LLM orchestration (all agents → one generic LLM) | ≡ system B (sanity check: reproduces B within noise) |

Each ablation runs the same frozen evidence and question set as system D.

## 4. Datasets

| Dataset | Use | Type | Notes |
|---|---|---|---|
| **SPIQA** (primary) | main benchmark | scientific papers, image/table question answering | verify license/terms before download; document version + hash |
| QASper | scientific QA with evidence annotations | text + table/figure annotations | evidence-level scoring is valuable |
| SciCap / SciERC-style | caption/agreement auxiliary sanity | scientific captions | optional |
| ChartQA / DocVQA (subset) | component sanity for figure/table agents | charts/documents | not scientific papers; used only to unit-test modality reasoning |
| **ResearchLens-XM** (ours) | controlled cross-modal set | hand-built from 8–12 open-license papers | see §5 |

Rules: only datasets whose licenses permit research use; store `datasets/manifest.json`
(name, version, source URL, license, SHA-256, download date); never commit raw corpus files.

## 5. ResearchLens-XM (controlled cross-modal set)

~80–120 questions over 8–12 papers (arXiv open license), balanced:

| Category | ID | Count (target) |
|---|---|---|
| text | `text` | 15 |
| table | `table` | 15 |
| figure | `figure` | 15 |
| text+table | `text_table` | 15 |
| text+figure | `text_figure` | 10 |
| table+figure | `table_figure` | 10 |
| multi-paper | `multi_paper` | 10 |

Each item: `question_id, question, category, paper_ids, gold_answer (short), gold_evidence_ids,
acceptable_alternatives[], answer_type (span|numeric|list|free), difficulty`.
Gold evidence IDs are the backbone of grounding metrics; a question without gold evidence
can still be scored for correctness but not for grounding recall.
Labeling protocol: two people annotate ≥30% overlap; disagreements adjudicated; report agreement (κ).

## 6. Metrics

### 6.1 Answer correctness
- **Primary:** LLM-as-judge with a fixed rubric + fixed judge model, scoring
  `correct / partially_correct / incorrect` per question → normalized score (1 / 0.5 / 0).
  Judge sees gold answer + model answer, *not* which system produced it (blinded, randomized order).
- **Secondary:** exact/normalized match for `span` and `numeric` questions; set-F1 for `list`.
- **Calibration:** human spot-check of ≥50 (answer, verdict) pairs; report judge–human agreement.
  If agreement < target, revise rubric before reporting H1–H3.

### 6.2 Evidence grounding
- **Evidence Recall** = |cited evidence ∩ gold evidence| / |gold evidence|
- **Evidence Precision** = |cited evidence ∩ gold evidence| / |cited evidence|
- **Grounded Claim Ratio** = claims with verdict `SUPPORTED` / all claims in answer
- Reported per modality slice (text/table/figure).

### 6.3 Citation correctness
- **Citation Validity** = citations referencing an ID actually supplied ÷ all citations (expect 100% by construction — regression test, not a research metric).
- **Citation Support** = citations where the linked evidence actually supports the attached sentence ÷ all citations (judge/human verified).
- **Citation Hallucination Rate** = reference strings in the answer text that appear nowhere in the evidence bundle ÷ all reference strings. Target: 0.

### 6.4 Hallucination
- **Unsupported Claim Rate (UCR)** = claims with verdict ∈ {UNSUPPORTED, CONTRADICTED} ÷ all claims emitted by agents (measures the pipeline before filtering).
- **Answer Hallucination Rate (AHR)** = unsupported statements in the *final answer* ÷ statements (measures what users see; D should be ≈0 by construction — verify empirically).
- **Numeric Hallucination** = numeric values in the answer not present in any cited evidence, and not derivable by documented arithmetic from `table_data`. Separate metric for table vs figure questions.

### 6.5 Verification (judge) quality
Treat the judge as a classifier evaluated against human labels on a stratified subset (≥100 claims):
precision/recall/F1 per verdict class, confusion matrix. Especially:
- false `UNSUPPORTED` (judge too strict → coverage loss)
- false `SUPPORTED` (judge too lenient → hallucination slips through)

### 6.6 Latency & cost
- Per-stage p50/p95 (`analyze`, `agents`, `verify`, `generate`, `total`), per system.
- Token usage per request (prompt/completion) as cost proxy.
- Judge overhead = latency(D) − latency(C); report alongside AHR reduction (H5).

### 6.7 Agent agreement
- Pairwise agreement between agents on overlapping claims (table vs text on the same numbers).
- Cohen's κ across agents where verdicts are comparable.
- **Disagreement → error rate:** does disagreement predict an incorrect answer? (justifies the judge)

### 6.8 Degradation
- % requests with non-empty `metadata.degraded`; breakdown by cause (timeout, provider error, no evidence).

## 7. Protocol

1. Freeze: dataset hash, evidence bundles (per question), configs, prompt versions, model tags.
2. Run each system with `seed` recorded; 1 run for deterministic decoding; 3 runs with temp>0 only if exploring stability (report mean±std).
3. Write `evaluation/results/<run_id>/` containing: `config.yaml` (resolved settings), `models.json`,
   `prompts.json` (versions+hashes), `predictions.jsonl`, `metrics.json`, `logs/`, `git_sha`.
4. Statistics: paired bootstrap 95% CI over questions for score differences; report effect size and
   *n*; significance at α=0.05 with correction when comparing ≥3 systems; no claims from point estimates alone.
5. Slice everything by category (§5), paper, and question difficulty.
6. Report failures qualitatively: 5–10 representative error cases per system (misread table,
   invented figure number, cross-paper merge, unsupported causal claim).

**Reporting rule:** tables in the paper must be reproducible by
`python -m evaluation.runners.run_benchmark --config evaluation/configs/<system>.yaml --results <run_id>`.

## 8. Result layout (empty until Phase 5)

```
evaluation/results/
└── <run_id>/            # run_id = <system>_<dataset>_<YYYYMMDD>_<seed>
    ├── config.yaml  models.json  prompts.json
    ├── predictions.jsonl  metrics.json  latency.json
    └── README.md         # one paragraph: what was run, on what hardware, any caveats
```

`evaluation/results/**` is git-ignored except `results/.gitkeep` and small aggregated
`metrics_summary.csv` files used by the paper.

## 9. Acceptance criteria for the evaluation phase

- [ ] All four systems run from one command each, on frozen evidence.
- [ ] All metrics in §6 computed automatically into `metrics.json`.
- [ ] Human-label subset exists with reported judge agreement.
- [ ] Ablations AB-T/AB-Tab/AB-V/AB-J/AB-O produce comparable outputs.
- [ ] Latency p50/p95 recorded per system per stage.
- [ ] Manifest + licenses recorded for every dataset.
- [ ] No number appears in the paper that lacks a corresponding `results/<run_id>/`.
