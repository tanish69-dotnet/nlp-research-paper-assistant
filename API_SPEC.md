# API_SPEC — ResearchLens Reasoning Module (Person 3)

| Field | Value |
|---|---|
| Status | Draft v0.1 — Phase 0, **contract freeze candidate** |
| Base path | `/api/v1` |
| Format | JSON, UTF-8, `application/json` |
| Schema source of truth | `app/schemas/*.py` (Pydantic v2) — this document mirrors it |
| Versioning | additive changes only within `v1`; breaking change → `/api/v2` |

All types below are the contract. **Person 2 and Person 4 should review §4 (evidence
contract) and §5 (response contract) before Phase 1 implementation.**

---

## 1. Conventions

- Every response contains `request_id` (UUIDv4, generated if absent in request).
- Timestamps: ISO-8601 UTC.
- Errors use `ProblemDetail` (RFC 9457 style) with a stable machine-readable `code`.
- Unknown/extra fields are rejected on input (`extra="forbid"`) so typos fail loudly.
- Evidence content is **untrusted data**; see SECURITY.md — it must never be interpreted as instructions.
- All schema enums are lowercase except `Verdict`, which is uppercase for visibility in logs/eval.

## 2. Common types

```python
EvidenceType = Literal["text", "table", "figure", "equation", "metadata"]
Modality     = Literal["text", "table", "figure", "equation", "metadata"]
QuestionType = Literal[
    "definition", "lookup", "numeric_lookup", "comparison",
    "cross_modal_comparison", "multi_paper_comparison", "causal_explanation",
    "trend_analysis", "aggregation_list", "ablation_analysis", "other",
]
AgentStatus  = Literal["ok", "partial", "no_evidence", "timeout", "error", "skipped", "degraded"]
Verdict      = Literal["SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONTRADICTED"]
ClaimKind    = Literal[
    "author_claim", "inference", "limitation", "methodology", "definition",
    "table_observation", "table_comparison", "table_interpretation",
    "figure_observation", "cross_modal_link", "comparison_row",
]


class PaperRef(BaseModel):
    paper_id: str                       # stable id, e.g. "paper_001"
    title: str | None = None
    authors: list[str] = []
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    num_pages: int | None = None


class TableData(BaseModel):
    headers: list[str]
    rows: list[list[str | None]]
    caption: str | None = None
    # optional cell provenance for exact citation of a value
    cell_locators: dict[str, str] = {}   # "r{row}|c{col}" -> "p7:T3:R4C3"


class ImageRef(BaseModel):
    path: str | None = None             # relative to EVIDENCE_ROOT (preferred)
    b64: str | None = None              # alternative transport; mutually exclusive w/ path
    mime: str | None = None
    sha256: str | None = None


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str                    # immutable, supplier-assigned, unique across bundle
    paper_id: str                       # identity preserved; never merged across papers
    type: EvidenceType
    content: str = ""                   # canonical text representation (may be "")
    caption: str | None = None
    reference: str | None = None        # human label: "Table 3", "Figure 5", "Section 4.2"
    page: int | None = None
    section: str | None = None
    table_data: TableData | None = None # structured tables when extraction provides them
    image: ImageRef | None = None
    char_span: tuple[int, int] | None = None   # offsets of content in original block
    score: float | None = None          # retrieval score (0..1), pass-through
    truncated: bool = False
    metadata: dict[str, JsonValue] = {}


class RetrievalMeta(BaseModel):
    query: str | None = None
    retriever: str | None = None        # e.g. "hybrid_bm25_vss"
    top_k: int | None = None
    retrieved_at: datetime | None = None
    run_id: str | None = None


class EvidenceBundle(BaseModel):
    """Person 2 → Person 3 boundary object."""
    model_config = ConfigDict(extra="forbid")

    query: str | None = None            # echo of retrieval query (may differ from user query)
    papers: list[PaperRef] = []
    evidence: list[EvidenceItem]        # min_length=1 on the request wrapper
    retrieval: RetrievalMeta | None = None
    warnings: list[str] = []
```

## 3. Endpoints

### 3.1 `GET /api/v1/health`

```json
{
  "status": "ok",
  "version": "0.1.0",
  "request_id": "…",
  "providers": [{"name": "ollama", "reachable": true, "models": ["llama3.1:8b"]}],
  "checks": {"evidence_root": "ok", "prompts": "ok"},
  "uptime_s": 123.4
}
```
`?deep=true` performs live provider pings (slower; used by docker-compose healthcheck only when needed). `status ∈ {ok, degraded, error}` → HTTP 200/200/503.

### 3.2 `GET /api/v1/models`

```json
{
  "request_id": "…",
  "provider": "ollama",
  "roles": [
    {"role": "judge", "model": "llama3.1:8b", "vision": false, "available": true},
    {"role": "vision_reasoner", "model": "llama3.2-vision", "vision": true, "available": true}
  ]
}
```
Never exposes API keys. Used by Person 4 to show capability badges and by ops to detect misconfiguration.

### 3.3 `POST /api/v1/analyze`

Query decomposition only — no modality agents, no judge.

Request:
```json
{
  "query": "Which method performed best in Table 3 and why does Figure 5 show a drop?",
  "papers": [{"paper_id": "paper_001"}],
  "evidence_hints": [
    {"evidence_id": "e_t3", "type": "table",  "reference": "Table 3",  "paper_id": "paper_001"},
    {"evidence_id": "e_f5", "type": "figure", "reference": "Figure 5", "paper_id": "paper_001"}
  ],
  "options": {"model_role": "analyzer"}
}
```
`evidence_hints` are **summaries only** (id/type/reference), not full content: cheaper, and reduces injection surface for a step that only classifies.

Response → `QueryPlan`:
```json
{
  "request_id": "…",
  "plan": {
    "question_type": "cross_modal_comparison",
    "required_modalities": ["table", "figure", "text"],
    "tasks": [
      {"task": "table_lookup",   "modality": "table",  "target_references": ["Table 3"], "evidence_ids": ["e_t3"]},
      {"task": "figure_analysis", "modality": "figure", "target_references": ["Figure 5"], "evidence_ids": ["e_f5"]},
      {"task": "text_explanation", "modality": "text",  "target_references": [], "evidence_ids": []}
    ],
    "target_references": ["Table 3", "Figure 5"],
    "requires_cross_modal": true,
    "paper_scope": "single",
    "paper_ids": ["paper_001"],
    "sub_questions": [
      {"id": "sq1", "text": "Which method performed best in Table 3?", "modalities": ["table"]},
      {"id": "sq2", "text": "Why does Figure 5 show a performance drop?", "modalities": ["figure", "text"]}
    ],
    "confidence": 0.9
  },
  "metadata": {"model": "llama3.1:8b", "prompt_version": "query_analyzer/v1", "latency_ms": 410}
}
```

### 3.4 `POST /api/v1/reason`  ← primary endpoint

Request:
```json
{
  "request_id": "optional-client-uuid",
  "query": "Which method performed best in Table 3, and why does Figure 5 show a drop?",
  "evidence": {
    "query": "Table 3 results Figure 5 ablation",
    "papers": [{"paper_id": "paper_001", "title": "…"}],
    "evidence": [ /* EvidenceItem[] — see §4 */ ],
    "retrieval": {"retriever": "hybrid", "top_k": 12, "run_id": "r_2026_10_08_001"}
  },
  "options": {
    "include_agent_outputs": true,
    "include_plan": true,
    "confidence_threshold": 0.5,
    "max_evidence_items": 40,
    "timeout_ms": 120000,
    "language": "en"
  }
}
```

Response — `ReasoningResponse`:
```json
{
  "request_id": "…",
  "status": "ok",
  "answer": "Transformer-XL attains the highest F1 in Table 3 … [c1]. Figure 5 suggests the drop is caused by … [c2].",
  "confidence": 0.83,
  "citations": [
    {"citation_id": "c1", "evidence_id": "e_t3", "paper_id": "paper_001", "page": 7,
     "type": "table", "reference": "Table 3", "title": "…"},
    {"citation_id": "c2", "evidence_id": "e_f5", "paper_id": "paper_001", "page": 8,
     "type": "figure", "reference": "Figure 5", "title": "…"}
  ],
  "claims": [
    {"claim_id": "cl1", "agent": "table_reasoner", "kind": "table_comparison",
     "text": "Transformer-XL attains the highest F1 in Table 3",
     "evidence_ids": ["e_t3"], "confidence": 0.9,
     "verification": {"verdict": "SUPPORTED", "verifier": "deterministic+judge",
                      "rationale": "Row 'Transformer-XL' F1=91.4 is the maximum in column F1."}},
    {"claim_id": "cl2", "agent": "vision_reasoner", "kind": "figure_observation",
     "text": "Performance drops for longer contexts in Figure 5",
     "evidence_ids": ["e_f5"], "confidence": 0.7,
     "verification": {"verdict": "PARTIALLY_SUPPORTED", "verifier": "judge",
                      "rationale": "Trend visible; stated cause not established by the figure alone.",
                      "missing_aspects": ["causal explanation"]}}
  ],
  "verification": {
    "status": "partially_supported",
    "supported": 1, "partially_supported": 1, "unsupported": 0, "contradicted": 0,
    "unsupported_claims": [],
    "contradicted_claims": [],
    "needs_more_evidence": false
  },
  "agent_outputs": [ /* AgentRun[] — see §3.6 */ ],
  "plan": { /* QueryPlan, optional */ },
  "metadata": {
    "models": {"analyzer": "llama3.1:8b", "vision_reasoner": "llama3.2-vision"},
    "prompt_versions": {"judge": "judge/v2"},
    "timings_ms": {"analyze": 410, "agents": 5200, "verify": 2100, "generate": 1500, "total": 9300},
    "agent_status": {"text_reasoner": "ok", "table_reasoner": "ok", "vision_reasoner": "ok"},
    "degraded": [],
    "dropped_evidence_ids": [],
    "evidence_used": ["e_t3", "e_f5", "e_p42"],
    "evidence_total": 12,
    "pipeline_version": "0.1.0",
    "cache_hit": false
  }
}
```

`status` (response-level): `ok | partial | error`.
- `partial` — pipeline completed with degradation (agent/judge skipped, timeouts). `metadata.degraded` explains.
- `error` — nothing usable produced; body contains `ProblemDetail`.

`verification.status`: `supported | partially_supported | unsupported | mixed | unverified`.
`unverified` = judge did not run (never presented as supported).

### 3.5 `POST /api/v1/verify` (internal; used by ablations & Person 4 "why?" view)

Request: `{ "query": "...", "evidence": {...}, "claims": [Claim...] }`
Response: `{"request_id", "verifications": [ClaimVerification...], "metadata": {...}}`

### 3.6 `AgentRun` (inside `agent_outputs`)

```json
{
  "agent": "table_reasoner",
  "model": "llama3.1:8b",
  "provider": "ollama",
  "prompt_version": "table_agent/v1",
  "status": "ok",
  "latency_ms": 1840,
  "evidence_ids_used": ["e_t3"],
  "findings": ["cl1"],
  "usage": {"prompt_tokens": 1930, "completion_tokens": 210},
  "error": null
}
```
`error` shape: `{"code": "MODEL_TIMEOUT", "message": "…", "retriable": true, "attempts": 2}`.

### 3.7 `POST /api/v1/evaluate` (feature-flagged: `ENABLE_EVAL_API=false` by default)

```json
{"dataset": "spiqa", "subset": "dev", "system": "D", "config": "evaluation/configs/system_D.yaml", "limit": 50, "seed": 17}
```
Response: `{"run_id": "…", "status": "started", "results_uri": "evaluation/results/run_…/"}`.
Batch evaluation also runs offline via `python -m evaluation.runners.run_benchmark` — HTTP is optional sugar, not a requirement.

## 4. Evidence contract (Person 2 → Person 3) — FINAL

### 4.1 Original contract (accepted, with additions required)

The team-provided shape is accepted as the base: `{query, evidence: [{paper_id, page, type, content, caption, image_path, reference}]}`.

### 4.2 Required additions (justification)

| Addition | Why |
|---|---|
| **`evidence_id`** (immutable, unique) | Citation attachment and claim verification need a stable handle; `paper_id+page+reference` can collide/duplicate. Person 3 may compute a deterministic fallback, but supplier-assigned IDs are preferred. |
| **`table_data: {headers, rows}`** | PDF table extraction is unreliable as text; structured rows enable *deterministic* ranking/delta computation (no LLM hallucination on numbers). |
| **`image.path` (+ optional `b64`, `sha256`)** | Replaces bare `image_path`; allows base64 transport for cross-process integration and integrity checks. Path must be **relative to `EVIDENCE_ROOT`** (security). |
| **`section`** | "Section 4.2" context matters for methodology questions; cheap to supply. |
| **`char_span`** | Enables exact-quote verification and highlight-in-UI for Person 4. |
| **`score` / `truncated`** | Observability + honest handling of cut-off evidence. |
| **`papers: PaperRef[]`** | Paper identity/metadata for multi-paper answers (titles in citations). |
| **`retrieval: RetrievalMeta`** | Reproducibility of evaluation; attribution of retrieval vs reasoning errors. |
| **`type` extended** | `equation`, `metadata` alongside `text/table/figure`. |
| **`extra="forbid"`** | Catch contract drift early. |

Fields marked optional are optional; `evidence_id`, `paper_id`, `type` are mandatory.

### 4.3 Two supported integration modes

| Mode | Mechanism | Phase |
|---|---|---|
| **A (MVP)** | Person 4 (or eval runner) posts the `EvidenceBundle` inside `POST /reason`. Reasoning service has **zero** runtime dependency on Person 2. | 1–3 |
| **B** | `EvidenceProvider` implementation `HttpEvidenceProvider` calls Person 2's endpoint `GET /retrieve?query=…&top_k=…` (their side) and maps the payload to `EvidenceBundle`. Enabled by `EVIDENCE_MODE=http` + `RAG_BASE_URL`. | 4 |

Person 3 commits to: `EvidenceBundle` schema stability within v1; a fixture-driven conformance test
(`tests/integration/test_contract_conformance.py`) that Person 2 can run against their payload.
Person 2 commits to: stable `evidence_id`, correct `type`, and image paths resolving under `EVIDENCE_ROOT`.

### 4.4 Example bundle (matches `tests/fixtures/mock_evidence.json`)

```json
{
  "query": "best method table 3 figure 5 drop",
  "papers": [{"paper_id": "paper_001", "title": "Sparse Retrieval for Scientific QA", "year": 2024}],
  "evidence": [
    {"evidence_id": "e_p001_p4_s42", "paper_id": "paper_001", "type": "text",
     "content": "We evaluate on SPIQA … Table 3 summarizes F1 …",
     "reference": "Section 4.2", "page": 4, "section": "4.2 Experimental Setup",
     "char_span": [1180, 1490], "score": 0.87},
    {"evidence_id": "e_p001_p7_t3", "paper_id": "paper_001", "type": "table",
     "content": "| Method | SPIQA-F1 | Latency |\n|---|---|---|\n| Ours | 91.4 | 0.8s |\n| Baseline-A | 84.2 | 0.6s |",
     "table_data": {"headers": ["Method", "SPIQA-F1", "Latency"],
                    "rows": [["Ours", "91.4", "0.8s"], ["Baseline-A", "84.2", "0.6s"]]},
     "caption": "Table 3: Results on SPIQA dev.", "reference": "Table 3", "page": 7,
     "image": {"path": "paper_001/p7_t3.png", "sha256": "…"}, "score": 0.92},
    {"evidence_id": "e_p001_p8_f5", "paper_id": "paper_001", "type": "figure",
     "content": "x-axis: context length; y-axis: SPIQA-F1; curves: Ours, Baseline-A",
     "caption": "Figure 5: Effect of context length on F1.",
     "reference": "Figure 5", "page": 8,
     "image": {"path": "paper_001/p8_f5.png", "sha256": "…"}, "score": 0.81}
  ],
  "retrieval": {"retriever": "hybrid_bm25_vss", "top_k": 12, "run_id": "r_001",
                "retrieved_at": "2026-10-08T08:00:00Z"}
}
```

## 5. Output contract (Person 3 → Person 4)

Guarantees Person 4 may rely on:

1. `citations[]` ⊆ evidence supplied; every `citation_id` referenced by `answer` markers exists.
2. `claims[]` each carry a verdict when `verification.status != "unverified"`.
3. Unsupported/contradicted claims are **excluded from `answer`** unless `options.include_unverified_claims=true`, in which case the answer text explicitly marks them.
4. `metadata.timings_ms.total` always present; `metadata.degraded[]` non-empty ⇒ `status="partial"`.
5. Paper identity preserved: every citation carries `paper_id`; multi-paper answers never mix IDs inside one citation.
6. No model-authored citation objects are trusted: `Citation` rows are rebuilt from the input bundle.

## 6. Error model

```python
class ProblemDetail(BaseModel):
    type: str          # "https://researchlens.local/errors/EVIDENCE_EMPTY"
    title: str
    status: int
    detail: str        # human-readable, no stack traces
    code: ErrorCode    # stable machine code
    request_id: str
    retryable: bool
```

| HTTP | code | When |
|---|---|---|
| 400 | `INVALID_REQUEST` | Pydantic validation failure (field-level detail included) |
| 400 | `EVIDENCE_EMPTY` | zero evidence items |
| 400 | `EVIDENCE_INVALID` | schema violation inside bundle |
| 400 | `IMAGE_PATH_FORBIDDEN` | image path escapes `EVIDENCE_ROOT` (SECURITY.md §5) |
| 413 | `PAYLOAD_TOO_LARGE` | body > `MAX_REQUEST_BYTES` or evidence > `MAX_EVIDENCE_CHARS` |
| 422 | `PROMPT_TOO_LONG` | evidence cannot be reduced under context window |
| 503 | `MODEL_UNAVAILABLE` | provider unreachable / no model for required role |
| 504 | `MODEL_TIMEOUT` | budget exhausted across retries |
| 500 | `INTERNAL_ERROR` | unexpected; logged with stack, response has no stack |

Retryable: `MODEL_UNAVAILABLE`, `MODEL_TIMEOUT`, `503/504` — clients may retry with backoff.

## 7. Endpoint summary

| Method | Path | Purpose | Auth (future) |
|---|---|---|---|
| GET | `/api/v1/health` | liveness + provider reachability | none |
| GET | `/api/v1/models` | role→model map, availability | none |
| POST | `/api/v1/analyze` | query decomposition only | key |
| POST | `/api/v1/reason` | full pipeline | key |
| POST | `/api/v1/verify` | standalone claim verification (ablations) | key |
| POST | `/api/v1/evaluate` | trigger eval run (flagged off) | admin key |

Rate limiting, API keys, and multi-tenant headers are **extension points** (middleware slot in `app/main.py`), not MVP scope.

## 8. Person 4 quick-start

```bash
uvicorn app.main:app --reload
curl -s localhost:8000/api/v1/health
curl -s -X POST localhost:8000/api/v1/reason -H "content-type: application/json" \
     -d @examples/reason_example.json
```

- OpenAPI schema at `/docs` (auto-generated from Pydantic) is the integration reference.
- Recommended UX: show `verification.status` as a badge, `citations` with `reference` + `page`,
  and `claims[]` in a "show reasoning" drawer; surface `metadata.degraded` as a warning.
- Long requests: MVP is synchronous; if p95 exceeds UI budget, adopt `202 + job_id` polling (reserved, not implemented).
