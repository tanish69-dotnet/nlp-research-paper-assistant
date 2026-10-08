# ARCHITECTURE — ResearchLens Reasoning Module (Person 3)

| Field | Value |
|---|---|
| Status | Draft v0.1 — Phase 0, pending team review |
| Style | Modular monolith: one FastAPI process, strict internal boundaries |
| Rule | Simple local implementation, clean abstraction seams — no speculative infrastructure |

---

## 1. Design principles

1. **Modularity** — every subsystem communicates through Pydantic contracts, never ad-hoc strings.
2. **Model agnosticism** — no model name appears in agent logic; models are configuration.
3. **Provider abstraction** — all inference goes through one interface (`ModelProvider`).
4. **Parallel by default** — independent agents run concurrently; orchestration is explicit.
5. **Stateless service** — request carries inputs, response carries outputs; no server-side session state.
6. **Structured contracts** — validated schemas at every boundary; `dict`-passing is a defect.
7. **Observability** — every request produces a complete, queryable run record.
8. **Cache-ready** — expensive operations sit behind interfaces that can be cached later.
9. **Failure isolation** — a dead VLM degrades the answer, it does not kill the request.
10. **Versionability** — prompts, model configs, and eval configs are files with versions.

## 2. System context

```
                 ┌──────────────────────────────────────────────┐
                 │                 ResearchLens                │
                 │                                              │
 Person 1 ──────►│  ingestion (PDF → blocks, images, tables)    │
                 │                                              │
 Person 2 ──────►│  RAG: index, retrieve, rerank ──► Evidence   │
                 │                                  Bundle      │
                 │                                     │        │
 Person 4 ──────►│  UI ──HTTP──► ┌─────────────────────▼──────┐ │
                 │              │   REASONING SERVICE (P3)    │ │
                 └──────────────┴─────────────────────────────┘ │
                                        │
                                        ▼
                              LLM / VLM providers
                        (Ollama · vLLM · HF · cloud APIs)
```

This module owns **only** the box on the right. It consumes an abstract
`EvidenceBundle` and emits a `ReasoningResponse`. It never imports Person 1/2/4 code.

## 3. Component overview

```
POST /reason
    │
    ▼
┌───────────────────── ReasoningOrchestrator ─────────────────────┐
│                                                                  │
│  1. Validate + normalize evidence (EvidenceValidator)            │
│  2. QueryAnalyzer ──► QueryPlan (types, modalities, tasks, refs)  │
│  3. TaskPlanner    ──► list[AgentTask] routed by modality         │
│  4. Parallel agent fan-out (asyncio.gather + per-agent budget)    │
│        ├── TextAgent      ──► claims (text evidence)              │
│        ├── TableAgent     ──► claims (table evidence + image)     │
│        └── VisionAgent    ──► claims (figure evidence + image)    │
│  5. EvidenceVerifier                                                   │
│        ├── Deterministic checks (IDs, refs, paper identity, nums) │
│        └── JudgeAgent (LLM) ──► per-claim verdicts                │
│  6. AnswerGenerator (verified claims only) ──► answer + citations │
│  7. Assemble ReasoningResponse + RunRecord (observability)        │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
        │                                   │
        ▼                                   ▼
  ModelRegistry / ModelProvider      EvidenceProvider
  (role → model → provider)          (request-embedded | HTTP)
```

### 3.1 Module responsibilities

| Component | Responsibility | Explicitly NOT responsible for |
|---|---|---|
| `api/routes` | HTTP binding, request validation, status codes | business logic |
| `orchestration/orchestrator` | ordering, concurrency, timeouts, degradation | prompting, model calls |
| `orchestration/planner` | `QueryPlan` → concrete `AgentTask` list | executing tasks |
| `agents/query_analyzer` | classify, decompose, detect refs/modality | answering |
| `agents/text_agent` | text-only evidence → claims | reading images, tables |
| `agents/table_agent` | structured table + table image → claims | figures, prose QA |
| `agents/vision_agent` | figure image + caption → observations | numeric precision claims |
| `agents/judge_agent` | LLM claim verification | creating evidence |
| `agents/answer_generator` | verified claims → final answer | new facts, new citations |
| `verification/deterministic` | schema/ID/consistency checks without LLM | semantic support judgment |
| `verification/judge_pipeline` | deterministic checks then LLM judge | answering |
| `models/*` | provider implementations of one interface | prompt content |
| `prompts/*` | versioned prompt templates | logic |
| `schemas/*` | contracts (Pydantic) | behavior |
| `evidence/*` (in `app/`) | validation, selection, token budgeting, path safety | retrieval |
| `observability/*` | logging, run records, latency | storage backend (later) |

## 4. Agent responsibilities (detailed contracts)

All agents implement:

```python
class Agent(Protocol):
    name: str
    async def run(self, ctx: AgentContext) -> AgentRun: ...
```

`AgentContext` = {request_id, query, QueryPlan, assigned evidence slice, options, clock}.
`AgentRun` = {agent, model, prompt_version, status, latency_ms, findings: list[Claim], error?}.

Statuses: `ok | partial | no_evidence | timeout | error | skipped | degraded`.

### 4.1 Query Analyzer
- **In:** user query, optional paper list, evidence *summaries* (IDs/refs only, not full bodies — cheaper and injection-safer).
- **Out:** `QueryPlan` (question_type, required_modalities, tasks, target_references bound to evidence IDs, decomposition, paper_scope, confidence).
- **Failure:** falls back to a conservative default plan (`single_paper`, all modalities present in evidence) and marks `metadata.degraded += ["query_analyzer"]`.
- Runs **first and alone** (everything depends on it).

### 4.2 Text Agent
- **In:** text-type evidence only.
- **Out:** claims of kind `author_claim | inference | limitation | methodology | definition`.
- Must separate *what the paper says* (`author_claim`) from *what the model concludes* (`inference`).
- Forbidden: using world knowledge as evidence; any claim without ≥1 evidence ID.

### 4.3 Table Agent
- **In:** `type=table` evidence — prefers structured `table_data` (headers + rows), falls back to markdown/text rendering; always receives caption, section, surrounding context; receives `image_path` when present.
- **Out:** claims with kind `table_observation` (exact cell values), `table_comparison` (ranking/deltas), `table_interpretation`.
- Two-pass design (Phase 3): (a) deterministic pass computes rankings/deltas from `table_data` where available — no LLM; (b) LLM pass explains/answers. Deterministic numbers are authoritative; the LLM may not contradict them.
- Must declare `reading_mode: structured | ocr_text | image_vlm` so the judge knows the risk profile.

### 4.4 Vision / Figure Agent
- **In:** figure image + caption + surrounding text + question.
- **Out:** `figure_observation` claims (trend direction, relative comparison, legend/axis identity, qualitative peak/drop) with `precision: qualitative | approximate`.
- **Hard rule:** no exact numeric readings unless the number is legible and marked `precision: approximate` with `value_source: figure_reading`. Numeric claims preferentially sourced from tables/text in the same paper.
- Never fabricate series, categories, or axis labels; if the image is missing → status `no_evidence`.

### 4.5 Judge / Verifier
- **In:** original query, full evidence (or evidence referenced by claims + local context), all agent claims.
- **Out:** per-claim `ClaimVerification{verdict, rationale, evidence_ids_support, evidence_ids_contradict, missing_aspects}` + overall status + `needs_more_evidence`.
- Verdicts: `SUPPORTED | PARTIALLY_SUPPORTED | UNSUPPORTED | CONTRADICTED`.
- Runs deterministic checks **first** (cheap, always on), then LLM judge on surviving claims.
- Judge prompt contains the same three-zone security structure (SECURITY.md §4).
- The judge **cannot** add citations or evidence; it can only mark claims unsupported or request more evidence.

### 4.6 Answer Generator
- **In:** query + **verified** claims (unsupported/contradicted removed or explicitly flagged) + QueryPlan.
- **Out:** markdown answer, confidence, citations resolved from claim evidence IDs.
- Instructions: state uncertainty, never emit reference strings not present in evidence, never fabricate numbers.
- Citation attachment is done by code after generation (§7), not by the model.

### 4.7 Agent Orchestrator
- Sequence: analyze → plan → **parallel fan-out** → verify → generate → record.
- Concurrency: `asyncio.TaskGroup`; per-agent `timeout`; per-role `Semaphore` (limits concurrent calls to one Ollama instance); retry policy `max_retries` with exponential backoff on transient provider errors only.
- Failure matrix:

| Failure | Effect |
|---|---|
| Analyzer timeout/error | default plan, degraded flag |
| One modality agent fails | proceed with remaining claims, degraded flag |
| All agents fail | return `status=error` with structured detail (no silent 500) |
| Judge timeout | claims marked `unverified`, overall status `unverified`, degraded flag |
| Evidence empty | `400 EVIDENCE_EMPTY` (before any model call) |
| Image missing | vision/table agent `no_evidence` for that item |
| Malformed model output | one repair attempt (re-ask with format reminder), then drop that agent's output with error record |

- **No partial answers are labelled "supported"**: if the judge did not run, status is `unverified`.

## 5. Model abstraction

```
ModelProvider (Protocol)
├── OllamaProvider          default, local, chat + vision
├── OpenAICompatProvider    covers vLLM, LM Studio, OpenAI, Anthropic-compat gateways
├── MockProvider            deterministic, used by tests/CI
└── (future) HFTransformersProvider, AzureProvider, ...
```

```python
class ModelProvider(Protocol):
    name: str
    async def chat(self, req: ChatRequest) -> ChatResponse: ...
    async def health(self) -> ProviderHealth: ...

# ChatRequest: messages[role, content, media?], model, temperature, max_tokens,
#              timeout_s, response_format ("json" | "text"), metadata(request_id, agent)
# ChatResponse: text, model, finish_reason, usage{prompt,completion}, latency_ms, raw?
```

- `ModelRegistry.resolve(role: ModelRole, settings) -> BoundModel{provider, model_name, capabilities}`
- `ModelRole = analyzer | text_reasoner | table_reasoner | vision_reasoner | judge | generator`
- Roles map to env vars (`ANALYZER_MODEL`, `TEXT_MODEL`, `TABLE_MODEL`, `VISION_MODEL`, `JUDGE_MODEL`, `GENERATOR_MODEL`) and to capability requirements (`vision: true` for `vision_reasoner`, `table_reasoner` when image input is used).
- If a role's model lacks vision capability → agent runs in text mode for that item and records `degraded`.
- JSON output: providers are asked for JSON; a shared `parse_json_response` with repair-then-fail semantics lives in `utils/`. Agents never `eval` or trust raw strings.
- **Adding a provider = one file + one registry entry. Agent code is untouched.**

## 6. Orchestration & execution model

- Fully async (`asyncio` + `httpx`); FastAPI async endpoints; no blocking calls on the event loop (model I/O via async client; CPU-bound table math via thread pool if needed).
- Request-scoped `RunRecord` accumulates `AgentRun`s + timings; returned in `metadata` when `include_agent_outputs=true`, always logged.
- Timeouts: total request budget (default 120 s) > per-agent budget (default 60 s) > per-provider-call (default 45 s). All configurable.
- Degraded-mode ladder: full pipeline → skip failed agent → judge skipped (status `unverified`) → structured error.

## 7. Citation architecture (anti-hallucination)

Core rule: **models reason over evidence; the system attaches citations.**

1. Retrieval/Person 2 assigns immutable `evidence_id` (deterministic: `sha1(paper_id|page|type|reference)[0:12]`, or supplier-provided).
2. Agents cite only by `evidence_id`.
3. Deterministic verifier rejects unknown IDs (`metadata.dropped_evidence_ids`).
4. `AnswerGenerator` receives allowed IDs; after generation, `CitationResolver` maps each claim's IDs → full `Citation{paper_id, page, type, reference, title?}` **from the evidence bundle**, never from model text.
5. Answer text embeds markers (`[e1]` / superscripts) that are resolved to citations in the response; any marker without a resolved evidence ID is stripped and logged.
6. Eval harness audits: any reference string in the answer not present in the bundle = citation hallucination (metric in EVALUATION.md §6).

## 8. Repository structure

```
nlp/                                  ← project repo root (own .git; see DEVELOPMENT_PLAN §Risks)
├── README.md                         module overview, doc index
├── PRD.md                            requirements, scope tiers
├── ARCHITECTURE.md                   this file
├── API_SPEC.md                       contracts & endpoints
├── EVALUATION.md                     research design, metrics, ablations
├── DEVELOPMENT_PLAN.md               phases, acceptance criteria, risks
├── SECURITY.md                       threat model, prompt zones
├── CONTRIBUTING.md                   workflow, commit rules, review checklist
├── .env.example                      all configuration keys, documented
├── .gitignore
├── pyproject.toml                    deps, pytest/ruff/mypy config, package metadata
├── Dockerfile
├── docker-compose.yml                app (+ ollama optional profile)
│
├── app/
│   ├── main.py                       FastAPI app factory, router registration, lifespan
│   ├── config.py                     Settings (pydantic-settings), env parsing
│   ├── core/                         errors (ProblemDetail), ids, time, exceptions
│   ├── api/
│   │   ├── dependencies.py           injected services (registry, settings, evidence provider)
│   │   └── routes/                   health.py, models.py, reason.py, analyze.py, evaluate.py
│   ├── schemas/
│   │   ├── evidence.py               PaperRef, EvidenceItem, EvidenceBundle, RetrievalMeta
│   │   ├── query.py                  QueryPlan, SubQuestion, AgentTask
│   │   ├── claims.py                 Claim, ClaimKind, AgentRun
│   │   ├── verification.py           ClaimVerification, VerificationResult, Verdict
│   │   ├── reasoning.py              ReasoningRequest/Response, Citation, Metadata
│   │   └── errors.py                 ProblemDetail, ErrorCode
│   ├── agents/
│   │   ├── base.py                   Agent protocol, AgentContext, status enums
│   │   ├── query_analyzer.py
│   │   ├── text_agent.py
│   │   ├── table_agent.py
│   │   ├── vision_agent.py
│   │   ├── judge_agent.py
│   │   └── answer_generator.py
│   ├── orchestration/
│   │   ├── orchestrator.py           pipeline sequence, concurrency, degradation
│   │   ├── planner.py                QueryPlan → AgentTasks, evidence routing
│   │   └── policies.py               timeout/retry/semaphore policies
│   ├── models/
│   │   ├── base.py                   ModelProvider protocol, ChatRequest/Response, registry
│   │   ├── ollama.py                 OllamaProvider (chat + vision)
│   │   ├── openai_compat.py          vLLM / OpenAI-compatible / gateways
│   │   ├── mock.py                   deterministic MockProvider (tests, CI, demos)
│   │   └── routing.py                role → provider/model resolution, capability checks
│   ├── evidence/
│   │   ├── provider.py               EvidenceProvider protocol (embedded | http)
│   │   ├── validation.py             schema + path + size + budget validation
│   │   └── selection.py              relevance slicing to fit token budget
│   ├── verification/
│   │   ├── deterministic.py          ID/ref/paper/numeric consistency checks
│   │   └── judge_pipeline.py         deterministic → LLM judge → aggregate
│   ├── prompts/
│   │   ├── loader.py                 versioned template loading + checksum
│   │   └── versions/
│   │       ├── v1/query_analyzer.md
│   │       ├── v1/text_agent.md
│   │       ├── v1/table_agent.md
│   │       ├── v1/vision_agent.md
│   │       ├── v1/judge.md
│   │       └── v1/answer_generator.md
│   ├── observability/
│   │   ├── logging.py                structlog JSON config, request_id binding
│   │   └── run_records.py            RunRecord/AgentRun accumulation & emission
│   ├── cache/
│   │   └── base.py                   Cache protocol + InMemoryCache (Redis later)
│   └── utils/                        json parsing/repair, text windowing, math
│
├── tests/
│   ├── unit/                         agents, verifier, resolver, config (MockProvider)
│   ├── integration/                  end-to-end /reason with fixture evidence
│   └── fixtures/                     mock_evidence.json, mock_model_outputs/*.json
│
├── evaluation/
│   ├── datasets/                     downloaded/curated data (git-ignored except manifests)
│   ├── configs/                      system A–D + ablation YAML (versioned)
│   ├── runners/                      run_benchmark.py, run_ablation.py
│   ├── metrics/                      correctness, grounding, citation, hallucination, latency
│   ├── baselines/                    saved baseline outputs
│   └── results/                      run directories (git-ignored)
│
├── scripts/                          setup_local.ps1/.sh, seed_demo.py, smoke_test.py
└── docs/                             contracts with teammates, decisions (ADR), diagrams
    ├── integration_person2.md
    ├── integration_person4.md
    └── adr/                          0001-evidence-contract.md, 0002-model-abstraction.md, ...
```

## 9. Integration boundaries

### 9.1 Person 2 (RAG / retrieval) — *inbound evidence*
- **Boundary type:** `EvidenceProvider` protocol with two implementations:
  - `EmbeddedEvidenceProvider` (MVP): evidence arrives in the request body — fully decoupled, zero runtime dependency.
  - `HttpEvidenceProvider` (Phase 4): calls Person 2's retrieval endpoint, maps their payload → `EvidenceBundle`.
- Agent code only ever sees `EvidenceBundle`. Switching providers changes configuration (`EVIDENCE_MODE=embedded|http`).
- Requirements on the supplier: stable `evidence_id`, `paper_id`, `page`, `type`, `reference`, `content`, optional `caption`/`image_path`/`table_data`, and a `retrieval` block (query, retriever name, scores). Full contract: API_SPEC.md §4.
- This module never re-ranks or re-indexes; it may **down-select** evidence to a token budget (transparent, logged).

### 9.2 Person 4 (frontend) — *outbound API*
- Consumes JSON over HTTP only; no shared Python imports.
- Synchronous request/response for MVP; `metadata.timings` supports progress UI; long-running jobs later via `202 + job_id` (extension point, not implemented).
- CORS configurable; errors are stable `ProblemDetail` objects with machine-readable `code`.
- Response always includes `request_id` for user-visible feedback and bug reports.

### 9.3 Person 1 (ingestion)
- No direct integration. Ingestion outputs (images, tables) reach this module inside evidence items. Assumption: image paths are relative to `EVIDENCE_ROOT` (SECURITY.md §5).

## 10. Scalability strategy

Local-first today; seams for tomorrow.

| Concern | Now | Extension point (no rewrite) |
|---|---|---|
| Inference | one Ollama process | `ModelProvider` → remote vLLM/GPU pool behind same interface |
| Model routing | 1 model per role via env | `routing.py` policies (cost/latency/quality) |
| Concurrency | in-process `TaskGroup` + semaphore | job queue (Celery/RQ/Arq) calling the same orchestrator function |
| State | stateless request/response | Redis cache for `ChatResponse` keyed by `(provider, model, prompt_version, input_hash)` |
| Evidence volume | slice to token budget | streaming/contextual retrieval, per-paper sub-reasoning map-reduce |
| Papers | 10s | map-reduce across papers → structured rows → synthesis stage (already the shape of FR-20/21) |
| Users | 1 | API keys/middleware layer ahead of unchanged routes |
| Observability | JSON logs | same events → OpenTelemetry/Prometheus |
| Deploy | `uvicorn` / Docker | multiple replicas behind LB — safe because service is stateless |

Explicitly **not** introduced now: message brokers, service meshes, Kubernetes, multiple microservices.

## 11. Technology choices

| Choice | Rationale | Alternative |
|---|---|---|
| Python 3.11+ (verify 3.14) | team stack; pydantic/fastapi already installed | — |
| FastAPI + Pydantic v2 | async, validation, OpenAPI for Person 4 | Flask (no async/validation) |
| Ollama default provider | local, free, vision models available | vLLM later, same interface |
| `structlog` JSON logs | structured observability from day one | stdlib logging |
| `httpx` | async provider/HTTP evidence clients | requests (blocking) |
| pytest + `MockProvider` | tests run without network/GPU | — |
| Modular monolith | correct scale for mini-project; seams allow split later | microservices (rejected: over-engineering) |
| Prompts as files | versionable, diffable, ablatable | inline strings (rejected) |

## 12. Key decisions (ADR index)

| ADR | Decision | Status |
|---|---|---|
| 0001 | Evidence contract (`EvidenceBundle`/`EvidenceItem`) owned here, versioned | proposed |
| 0002 | `ModelProvider` protocol + role-based `ModelRegistry` | proposed |
| 0003 | Deterministic checks before LLM judge | proposed |
| 0004 | Citations resolved server-side from evidence IDs | proposed |
| 0005 | Evidence embedded in request for MVP; HTTP provider later | proposed |
| 0006 | Modular monolith, async in-process orchestration | proposed |

## 13. Risks (architecture level)

1. **Local model quality** may be too weak for reliable JSON plans → mitigation: strict schema validation + repair loop + `MockProvider` fallback; measure, don't assume (EVALUATION.md).
2. **Python 3.14 wheel availability** for pydantic/uvicorn → mitigation: pin/verify in Phase 1, else 3.11/3.12 venv.
3. **Token budget overflow** with many evidence items → `evidence/selection.py` with logged truncation.
4. **Table extraction quality** from Person 1 unknown → dual-mode table reading (structured + image), reading mode surfaced to judge.
5. **Judge self-preference bias** (LLM grading LLM) → deterministic layer + human-labeled subset (EVALUATION.md §7).
6. **Contract drift** with Person 2/4 → contracts versioned in `docs/`, fixture-driven tests, changelog.
