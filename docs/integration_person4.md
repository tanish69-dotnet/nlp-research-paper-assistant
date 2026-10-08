# Integration Contract — Person 3 (Reasoning) → Person 4 (Frontend)

**Status:** proposed, Phase 0 review · **Source of truth:** [../API_SPEC.md](../API_SPEC.md)

## TL;DR

Pure HTTP/JSON service at `/api/v1`. No shared Python. OpenAPI schema at `/docs` is live
and should be your integration reference.

```bash
uvicorn app.main:app --reload      # http://127.0.0.1:8000
GET  /api/v1/health
GET  /api/v1/models
POST /api/v1/analyze
POST /api/v1/reason                # main endpoint
```

## What you send

```json
{
  "query": "Which method performed best in Table 3 ...?",
  "evidence": { "papers": [...], "evidence": [...], "retrieval": {...} },
  "options": {"include_agent_outputs": true, "include_plan": true, "timeout_ms": 120000}
}
```

In MVP you (or the eval runner) place Person 2's retrieval payload into `evidence` — see
`docs/integration_person2.md`. Later this can come directly from Person 2's service.

## What you get (`ReasoningResponse`)

| Field | Use it for |
|---|---|
| `answer` | markdown answer text with `[c1]` citation markers |
| `confidence` 0..1 | confidence badge |
| `citations[]` | `{citation_id, evidence_id, paper_id, page, type, reference, title}` — render under the answer; **always sourced from the supplied evidence, never model-invented** |
| `claims[]` | per-claim text, agent, kind, confidence, `verification.verdict` → "show reasoning" drawer |
| `verification.status` | `supported / partially_supported / unsupported / mixed / unverified` → prominent badge |
| `status` | `ok / partial / error` — `partial` means degraded; show `metadata.degraded` as a warning |
| `metadata.timings_ms` | progress/latency display; `metadata.agent_status` for per-agent indicators |
| `metadata` (general) | `request_id` for bug reports; `evidence_used` for "sources" highlighting |

## Guarantees you can rely on

1. Every `citation_id` referenced in `answer` exists in `citations[]`; `citations[]` ⊆ evidence you sent.
2. Unsupported claims are excluded from `answer` unless `options.include_unverified_claims=true`
   (then they are explicitly marked in the text).
3. Errors are stable `ProblemDetail` objects: `{code, title, status, detail, request_id, retryable}`
   with machine codes (`EVIDENCE_EMPTY`, `MODEL_TIMEOUT`, `MODEL_UNAVAILABLE`, ...).
   Retry only when `retryable: true`.
4. `request_id` always present — surface it in the UI for support.
5. Provider keys never appear in responses.

## Your side

- **Render `answer` as sanitized markdown — no raw HTML injection** (SECURITY.md §7).
- Synchronous requests in MVP; if p95 latency exceeds your UX budget, tell us —
  the reserved future pattern is `202 + job_id` polling (not implemented yet).
- CORS is configured via `CORS_ORIGINS` (default `http://localhost:5173`); tell us your dev origin.
- Do not parse our markdown to reconstruct citations — use `citations[]`.

## UI evidence we need from you (for the paper's demo)

- Verification badge per answer.
- Clickable citations that open the source passage/page (we provide `page`, `reference`, `evidence_id`).
- A "degraded/incomplete" indicator driven by `metadata.degraded`.
