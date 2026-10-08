# DEVELOPMENT_PLAN — ResearchLens Reasoning Module (Person 3)

| Field | Value |
|---|---|
| Status | Draft v0.1 — Phase 0 (planning) awaiting review |
| Workflow | GSD/RALF-style iterative loop, small commits, evidence-based progress |
| Current phase | **Phase 0 — Planning & Design** (this document set) |

---

## 0. Working agreement

For every phase:

```
PLAN → IMPLEMENT → TEST → REVIEW → FIX → DOCUMENT → COMMIT → NEXT PHASE
```

Rules:
1. **Never claim something works without a test run.** Report test output, not intent.
2. **No placeholders labelled complete.** A stub must be marked `stub` in code and listed as deferred in the phase report.
3. **Commits are small and meaningful** (one phase may be several commits; one commit never spans unrelated phases).
4. **Docs update with code** — a phase is not done until its docs/ADR match reality.
5. Phase exits require the stated acceptance criteria; failure → FIX, not NEXT.
6. Any deviation from plan is recorded in the phase report (deviation log).

Definition of Done (any task): code + tests green locally + doc updated + no secrets/large binaries committed.

## Phase map

| Phase | Name | Outcome | Depends on |
|---|---|---|---|
| 0 | Planning & design | 6 reviewable docs + contracts + fixture | — |
| 1 | Foundation | project skeleton, config, schemas, provider abstraction, health/models, mock evidence | 0 |
| 2 | Analyze + Text agent | `/analyze` + text agent + unit tests | 1 |
| 3 | Table + Vision agents | modality agents with real model support | 2 |
| 4 | Judge + generator + orchestration | full `/reason` pipeline with citations | 3 |
| 5 | Integration + evaluation harness | Person 2 contract conformance, benchmark runner, metrics | 4 |
| 6 | Research experiments | systems A–D, ablations, analysis, paper numbers | 5 |
| 7 | Hardening | retries/timeouts/Docker/docs/observability polish | 4–6 |
| 8 | Future (backlog) | caching, queue, auth, HTTP retriever scale-out | 7 |

MVP = end of Phase 4. Research-grade = end of Phase 6.

---

## Phase 0 — Planning & Design (current)

**Deliverables**
- [x] Repository inspection (empty repo; only `.agent/`, `.kilo/`)
- [x] PRD.md, ARCHITECTURE.md, API_SPEC.md, EVALUATION.md, DEVELOPMENT_PLAN.md, SECURITY.md
- [x] Proposed directory structure
- [x] Evidence + output contracts defined (API_SPEC §4–5)
- [x] Agent boundaries, model abstraction, integration boundaries defined
- [x] Mock evidence fixture (`tests/fixtures/mock_evidence.json`)
- [x] Acceptance criteria, risks, dependencies, scope tiers (MVP / research / future)

**Acceptance for Phase 0 exit**
- [ ] Team review completed; contracts frozen or amended with changelog entries
- [ ] Person 2 acknowledges evidence contract; Person 4 acknowledges response contract
- [ ] Open questions in PRD §10 resolved (repo root, model availability, image transport)
- [ ] Decision recorded for evaluation dataset licenses (EVALUATION §4)

**Not in Phase 0:** any implementation code.

---

## Phase 1 — Foundation

**Scope**
1. `pyproject.toml` (deps: fastapi, uvicorn, pydantic, pydantic-settings, httpx, structlog, pytest, ruff, mypy; optional: ollama client), `.env.example`, `.gitignore`, README quickstart.
2. `app/config.py` — `Settings` with all keys from `.env.example`, env-validated, `Settings` test.
3. `app/schemas/*` — every contract from API_SPEC with round-trip tests.
4. `app/models/base.py` + `mock.py` (+ `ollama.py` skeleton with chat only) + `routing.py` role resolution.
5. `app/core/errors.py` (ProblemDetail + codes), `app/observability/logging.py` (JSON logs, request_id).
6. `app/main.py` + routes: `GET /health`, `GET /models`.
7. `app/evidence/validation.py` — bundle validation incl. `EVIDENCE_ROOT` path check.
8. Fixtures: `mock_evidence.json`, `mock_model_outputs/`.

**Tests:** schema round-trips; config parsing; path-traversal rejection; health/models with MockProvider; zero network/GPU required.

**Acceptance**
- [ ] `pytest` green on a clean clone with no Ollama running
- [ ] `GET /health` returns `ok` in mock mode; `GET /models` lists all roles
- [ ] Every schema in API_SPEC exists and validates the doc examples (docs ↔ code conformance test)
- [ ] `ruff` + `mypy` clean on `app/`
- [ ] Docs updated to reflect reality (or deviations recorded)

## Phase 2 — Query analysis + Text agent

**Scope:** prompt templates `v1/` for analyzer & text agent; `QueryAnalyzer`; `planner.py` (plan → tasks → evidence routing); `TextAgent`; `POST /analyze` (analyze-only path); text-only partial `/reason` (returns `verification.status="unverified"`).

**Tests:** analyzer returns valid `QueryPlan` for 10 fixture questions (types/modalities/refs asserted); ref binding finds `Table 3`/`Figure 5`; text agent emits claims only with valid evidence IDs; malformed JSON path triggers one repair then structured error; prompt loader versioning + checksum.

**Acceptance**
- [ ] `/analyze` returns a schema-valid plan for all fixture questions
- [ ] No claim may be created without a known `evidence_id` (unit-tested at claim construction)
- [ ] Analyzer failure → default plan + degraded flag (tested)

## Phase 3 — Table + Vision agents

**Scope:** `TableAgent` (deterministic pass over `table_data` → rankings/deltas; LLM pass for interpretation; `reading_mode`); `VisionAgent` (image via `ImageRef`, caption, context; qualitative precision rules); image loading with size/type limits; modality-aware prompts.

**Tests:** deterministic table ranking correctness (ground-truth table fixture); vision agent on missing image → `no_evidence`; numeric-claim guard (rejects unsupported precision, tested with crafted model outputs); oversized/corrupt image rejected; parallel fan-out smoke test (3 agents concurrently, mocked).

**Acceptance**
- [ ] Table rankings/deltas computed without LLM are exact for the fixture
- [ ] Vision claims carry `precision` and never contain exact numbers absent from fixtures (property-style test)
- [ ] One agent failure does not fail the request (tested)

## Phase 4 — Judge, generator, orchestration (MVP complete)

**Scope:** `verification/deterministic.py`; `judge_pipeline.py` + judge prompt; `AnswerGenerator`; `CitationResolver`; `orchestrator.py` with timeouts/retries/semaphores/degradation; `POST /reason` full pipeline; `RunRecord` in metadata; structured logging per request.

**Tests:** end-to-end `/reason` on fixture with `MockProvider` → verified claims + citations ⊆ evidence; injected unsupported claim gets `UNSUPPORTED` and is excluded from answer; judge timeout → `unverified` + degraded; citation resolution strips unknown IDs; deterministic checks catch cross-paper mixing; latency fields present.

**Acceptance (MVP)**
- [ ] `POST /reason` returns a grounded answer with correct citations on `mock_evidence.json`
- [ ] Unsupported claim in → excluded from answer + listed in verification (tested)
- [ ] Every response includes `request_id`, `timings`, `agent_status`
- [ ] Degraded paths tested for: analyzer, each agent, judge, empty evidence
- [ ] Integration test suite runs offline in < 60 s
- [ ] README quickstart works from a clean clone

## Phase 5 — Integration + evaluation harness

**Scope:** `HttpEvidenceProvider` (if Person 2 endpoint ready) + contract conformance test; `evaluation/runners/run_benchmark.py`; metrics module (correctness, grounding, citation, hallucination, latency); ResearchLens-XM dataset build; mock/dry-run mode; `POST /verify`; `POST /evaluate` (flagged).

**Tests:** conformance test against Person 2 payload sample; metrics unit tests with hand-computed expectations; runner writes complete `results/<run_id>/` (validated by test); dataset manifest hash check.

**Acceptance**
- [ ] One command produces `predictions.jsonl` + `metrics.json` for a dry-run system on 10 questions
- [ ] Metrics verified against hand-computed fixtures
- [ ] Person 2 contract verified against their real payload
- [ ] No dataset committed without manifest/license entry

## Phase 6 — Research experiments

**Scope:** system configs A–D; ablations AB-T/AB-Tab/AB-V/AB-J/AB-O; human label subset; judge calibration; statistical analysis scripts; results tables/figures generation; paper-ready `metrics_summary.csv`.

**Acceptance**
- [ ] All systems + ablations run reproducibly from configs
- [ ] Every reported metric has a `run_id` and `git_sha`
- [ ] Human agreement reported; judge precision/recall reported
- [ ] Failure case study section written from real logs
- [ ] **No result reported that was not produced by a saved run**

## Phase 7 — Hardening & operations

**Scope:** retry/backoff tuning; timeout budgets measured; Dockerfile + compose (app + optional ollama profile); health deep checks; request size limits; rate-limit middleware slot; API docs polish; CONTRIBUTING final; load smoke (50 concurrent requests, mock mode) + bottleneck notes.

**Acceptance:** container runs `pytest` then serves `/health`; documented known limits; concurrency smoke passes without event-loop blocking.

## Phase 8 — Backlog (explicitly deferred)

Redis response cache → job queue (202 + job_id) → GPU/remote provider → auth/API keys + per-user quotas → observability backend (OTel/Prometheus) → prompt/model registry with experiment tracking → research-library management & multi-paper map-reduce → horizontal scale-out.

---

## MVP scope (recap)

Local Ollama LLM+VLM · mock evidence · query analyzer · text/table/vision agents · judge · answer generator · citation preservation · `POST /reason` `/analyze` `/health` `/models` · tests green offline.

## Research-grade scope (recap)

Real RAG integration · SPIQA + controlled cross-modal set · systems A–D · multi-LLM comparison · judge evaluation · hallucination + citation metrics · ablation study · latency evaluation.

## Risks

| # | Risk | Impact | Likelihood | Mitigation | Trigger/when |
|---|---|---|---|---|---|
| R1 | Local model too weak for reliable JSON plans | high | med | schema validation + one repair + conservative fallback; measure in Phase 2 | Phase 2 acceptance |
| R2 | Ollama VRAM limits force small models → low quality | high | med | confirm available models early (PRD §10 Q1); allow text/vision model split; record model tags in every run | Phase 1 |
| R3 | Python 3.14 wheel incompatibility (pydantic-core, etc.) | med | low | verify install in Phase 1; fallback venv on 3.11/3.12 | Phase 1 |
| R4 | Person 2 contract drift / missing `evidence_id` & `table_data` | high | med | conformance test + documented fallback derivation + early contract review (Phase 0) | Phase 0/5 |
| R5 | Table extraction quality poor | high | med | dual-mode reading (structured + image); surface `reading_mode` to judge | Phase 3 |
| R6 | Vision model cannot read small figures | med | med | caption+context-first reasoning; qualitative-only claims; degrade to text | Phase 3 |
| R7 | Judge bias (LLM grading LLM) | med | med | deterministic layer + blinded human subset + agreement reporting | Phase 6 |
| R8 | Evaluation dataset license/availability issues | med | low | license check early; ResearchLens-XM as guaranteed fallback | Phase 5 |
| R9 | Latency exceeds interactive budget on laptop | med | med | parallel agents, token budgeting, stage timings, cached evidence | Phase 4/7 |
| R10 | Prompt injection from paper content | high | high | three-zone assembly + output discipline + tests (SECURITY.md) | Phases 2–4 |
| R11 | Scope creep (infra before value) | med | med | Phase 8 backlog discipline; architecture review each phase | continuous |
| R12 | Team integration stalls (P1/P2/P4) | med | med | embedded-evidence MVP mode (zero runtime dependency), versioned contracts | continuous |
| R13 | Git repository rooted at `C:\Users\Tanish` instead of `nlp\` | med | high | re-root repo to `nlp\` before first commit (see PRD §10 Q4) | before Phase 1 commit |

## Dependencies

**External (team):** Person 1 image/table extraction quality · Person 2 evidence payload (Phase 5) · Person 4 API consumption (Phase 4+) · shared paper set for ResearchLens-XM.

**Software:** Python 3.11+ (verify 3.14) · fastapi 0.135 / pydantic 2.13 / uvicorn / httpx / structlog / pytest (already installed) · Ollama + at least one text and one vision model (installed, server not running at inspection time) · optional later: ollama python client, Pillow, `datasets`, scipy (bootstrap CIs).

**Data:** SPIQA + secondary benchmarks (license check), open-license papers for the controlled set.

**Environment:** target laptop specs (RAM/VRAM) to be recorded in Phase 1 — drives model defaults and latency expectations.

## Phase report template (used at each phase exit)

```
Phase N — <name>
- Planned: ...
- Done: ... (with commit SHAs)
- Tests: <command> → <pass/fail counts>
- Deviations from plan: ...
- Deferrals: ...
- Risks updated: ...
- Next phase entry criteria met: yes/no
```
