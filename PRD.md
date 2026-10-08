# PRD — ResearchLens Reasoning Module (Person 3)

| Field | Value |
|---|---|
| Module | `person3_reasoning` (reasoning service of ResearchLens) |
| Status | Draft v0.1 — Phase 0, pending team review |
| Owner | Person 3 (AI/NLP engineer) |
| Scope | Multi-LLM reasoning, multimodal reasoning, verification, citations, evaluation, reasoning API |
| Non-goals | PDF ingestion, primary RAG indexing/retrieval, frontend/UI |

---

## 1. Problem

Scientific papers are multimodal: paragraphs, equations, tables, charts, diagrams,
figures, captions, references, experimental results, appendices. Conventional RAG
flattens a paper into plain text, which destroys exactly the structure that hard
questions depend on.

Example question that fails under flat-text RAG:

> "Which method performed best in Table 3, and why does Figure 5 show a drop in performance?"

Answering it requires joint reasoning over a table, a figure, their captions,
surrounding prose, methodology — and possibly a second paper. Even when a capable LLM
is given the right evidence, it still:

- misreads table cells (wrong row/column alignment, wrong metric),
- invents numbers that cannot be read from a figure,
- emits plausible but non-existent citations,
- blends two papers into one claim,
- states a confident answer where the evidence is silent.

The module under this PRD exists to answer a **research question**, not merely to
wrap an LLM:

> **Does multi-LLM collaborative reasoning and verification improve the accuracy and
> factual grounding of multimodal RAG for scientific paper question answering?**

## 2. Users

| Persona | Need |
|---|---|
| Student / UG researcher | Fast, grounded answers on a small local library; trustworthy citations |
| Faculty / reviewer | Cross-paper comparison, contradiction detection, methodology differences |
| Research team (future) | Shared persistent library, reproducible experiments, scaling to 10k papers |
| Developer / teammate (Person 2, 4) | Stable contracts: evidence in, structured answer out |

## 3. Product goals

1. **Grounded answers.** Every claim in a final answer is traceable to evidence IDs supplied by the retrieval layer; citations are attached by the system, never invented by a model.
2. **Specialized multi-LLM reasoning.** Distinct agents for text, tables, figures, plus a judge and a generator — not the same prompt to N models.
3. **Verifiable.** Each atomic claim is classified `SUPPORTED / PARTIALLY_SUPPORTED / UNSUPPORTED / CONTRADICTED` against the supplied evidence.
4. **Model agnostic.** Swapping Ollama → vLLM → cloud API changes configuration only, never agent logic.
5. **Local first.** Runs on a laptop with no paid API; cloud is optional.
6. **Scalable by design.** Same contracts support 10 → 10,000+ papers and 1 → many users without rewrite.
7. **Honest.** No fabricated metrics, no placeholder components labelled "done", no invented citations or results.

## 4. Non-goals (this module)

- PDF parsing, OCR, layout analysis, chunking, embedding, vector store, retriever internals (Person 1/2).
- UI, chat UX, session management, frontend state (Person 4).
- Distributed infrastructure (K8s, queues, GPU cluster) — only *extension points* are in scope now.
- Mandatory paid/cloud APIs.
- Autonomous web browsing / online paper search (future platform feature, outside this module).

## 5. Functional requirements

### 5.1 Query analysis
- **FR-1** Classify the question: `definition | lookup | numeric_lookup | comparison | cross_modal_comparison | multi_paper_comparison | causal_explanation | trend_analysis | aggregation_list | ablation_analysis | other`.
- **FR-2** Determine required modalities: `text | table | figure | equation | metadata`.
- **FR-3** Detect explicit target references (`Table 3`, `Figure 5`, `Section 4.2`) and bind them to evidence IDs when present.
- **FR-4** Decompose multi-part questions into ordered sub-questions with their own modality needs.
- **FR-5** Detect single-paper vs multi-paper scope and report paper identity list.

### 5.2 Specialized reasoning agents
- **FR-6** *Text agent*: extract claims, explanations, limitations, experimental context; distinguish **author claim** from **model inference**; cite only supplied evidence.
- **FR-7** *Table agent*: operate on structured table data **and** table image + caption + surrounding context; support row/column/header/metric comparisons, best/worst, deltas, ablations, dataset×metric grids; never silently trust extracted table text.
- **FR-8** *Vision agent*: operate on figure image + caption + surrounding text; report trends, peaks, drops, axes/legend readings, qualitative comparisons as **observations**, never as precise numbers that cannot be reliably read; every observation carries evidence IDs.
- **FR-9** Agents emit **structured** findings (`Claim` objects), not free prose, and declare confidence.

### 5.3 Verification
- **FR-10** Judge classifies every claim: `SUPPORTED | PARTIALLY_SUPPORTED | UNSUPPORTED | CONTRADICTED`.
- **FR-11** Judge detects agent disagreement, table misreadings, vision hallucination, missing evidence, invalid citations.
- **FR-12** Deterministic (non-LLM) pre-checks run before the LLM judge: evidence-ID existence, reference/type consistency, paper-identity consistency, numeric-in-evidence membership.
- **FR-13** Judge can never introduce new evidence; it may only request more (`needs_more_evidence`).

### 5.4 Citations & grounding
- **FR-14** Citations are resolved server-side from `evidence_id`s carried by verified claims. Model output never contains citation objects that are trusted verbatim.
- **FR-15** Unknown/dangling evidence IDs are dropped and reported in `metadata.dropped_evidence_ids`.
- **FR-16** Paper identity is preserved end-to-end; evidence from two papers is never merged into one unlabelled claim.

### 5.5 Answer generation
- **FR-17** Produce a final answer in markdown from *verified claims only*, with system-attached citations.
- **FR-18** Report an overall verification status and a calibrated confidence; explicitly say when evidence is insufficient instead of guessing.
- **FR-19** Degrade gracefully: if an agent or judge fails, return a partial answer flagged in `metadata.degraded` rather than a 500.

### 5.6 Cross-paper reasoning
- **FR-20** Support N papers in one request; produce structured comparison rows
  (`paper_id, method, dataset, metric, result, limitation, evidence_id`).
- **FR-21** Never merge evidence across papers silently; per-paper sub-answers may be synthesized but citations must stay per paper.

### 5.7 Service
- **FR-22** FastAPI endpoints: `GET /health`, `GET /models`, `POST /analyze`, `POST /reason`, plus `POST /verify` (internal/ablation) and `POST /evaluate` (feature-flagged).
- **FR-23** Stateless: all state is in the request/response or external stores.
- **FR-24** Structured JSON logging with `request_id`, agent, model, latency, status, evidence IDs, error.
- **FR-25** Config-driven models (`ANALYZER_MODEL`, `TEXT_MODEL`, `TABLE_MODEL`, `VISION_MODEL`, `JUDGE_MODEL`, `GENERATOR_MODEL`), prompts stored as versioned files, not inline strings.
- **FR-26** Retries with backoff on transient provider errors; hard per-agent timeouts; failure isolation per agent.
- **FR-27** Health check reports provider reachability; `/models` reports configured roles, capabilities and availability.

## 6. Non-functional requirements

| ID | Requirement | Target (MVP) |
|---|---|---|
| NFR-1 | Latency | p50 < 15 s, p95 < 45 s for single-paper multimodal query on laptop CPU/7B-class models (measured, not assumed) |
| NFR-2 | Determinism | temperature 0 (or fixed seed) for analysis/judge; identical inputs → identical structured output modulo model nondeterminism flag |
| NFR-3 | Correctness of contracts | 100% of API request/response validated by Pydantic; no untyped dict boundaries |
| NFR-4 | Testability | agents runnable with a `MockProvider`; unit tests require no network and no GPU |
| NFR-5 | Isolation | one agent failure never fails the request; degraded results explicitly flagged |
| NFR-6 | Security | untrusted paper text cannot alter instructions; path/size limits enforced (see SECURITY.md) |
| NFR-7 | Portability | Windows + Linux; Python 3.11+ (verify 3.14 wheel support in Phase 1) |
| NFR-8 | Extensibility | new provider = one new class implementing `ModelProvider`; new agent = one class + one registration |
| NFR-9 | Reproducibility | every evaluation run writes config, model versions, prompt versions, dataset hash, seed |
| NFR-10 | Observability | every request yields a full `AgentRun` trace record |

## 7. Scope tiers

### 7.1 MVP (must work end-to-end, locally)
Local Ollama LLM + VLM · mock evidence fixture · query analyzer · text/table/vision agents · judge · answer generator · citation preservation · `POST /reason` + `POST /analyze` + `/health` + `/models` · unit + integration tests with `MockProvider`.

### 7.2 Research grade
Real RAG integration with Person 2's evidence service · SPIQA (+ secondary benchmarks, licensing permitting) · controlled cross-modal set · baseline A vs systems B/C/D · multi-LLM comparison · judge evaluation · hallucination + citation metrics · ablation study · latency profiling.

### 7.3 Future (extension points only, not built now)
Multiple providers & routing · GPU worker pools · async job queue · response cache · metrics/tracing backend · rate limiting · auth · multi-user libraries · experiment tracking · prompt/model registry UI · horizontal scaling.

## 8. Success criteria

**MVP:** all FR-1…FR-27 implemented or explicitly deferred; `pytest` green locally with no model required; `/reason` returns a verified answer with correct citations on the fixture.

**Research grade:** Systems A–D + ablations runnable from a single command; metrics written to `evaluation/results/`; every reported number reproducible from a saved run directory; no claim of improvement without statistical evidence.

**Quality bar:** correctness · reproducibility · modularity · testability · observability · model-agnostic design · evidence grounding · scalability · security — above framework count, microservices, speculative infrastructure.

## 9. Assumptions

- Person 2 exposes evidence either (a) inside the request payload, or (b) via a small HTTP endpoint. Contract in API_SPEC.md; both supported through `EvidenceProvider`.
- Person 4 consumes the HTTP API only (JSON), no direct module imports.
- Ollama is the default local provider; models are configurable and may be absent (mock mode must still work).
- Evaluation datasets are used only where licensing permits; dataset download is a separate, explicit step.
- Persona/institution data is out of scope for MVP.

## 10. Open questions (to resolve in review)

1. Which model sizes are actually available on the target laptop (VRAM/RAM)? Drives `TEXT_MODEL`/`VISION_MODEL` defaults.
2. Does Person 2 return images as filesystem paths or base64? Contract supports both; default path-based.
3. Is a conversation/multi-turn context needed in MVP? Proposed: **no**, single-turn with optional `history` field reserved.
4. Repo root: the enclosing Git repository currently sits at `C:\Users\Tanish`. The project repository should be rooted at `nlp\` — confirm before first commit.
