# Integration Contract — Person 2 (RAG) → Person 3 (Reasoning)

**Status:** proposed, Phase 0 review · **Source of truth:** [../API_SPEC.md](../API_SPEC.md) §4

## TL;DR

Person 3 consumes an `EvidenceBundle`. We do not import your code, call your index, or
re-rank your results. Two supported modes:

| Mode | How | When |
|---|---|---|
| **A (MVP)** | Evidence is passed **inside the request body** of `POST /api/v1/reason` (your payload becomes `request.evidence`) | now |
| **B** | Your service exposes an HTTP endpoint; we call it via `EVIDENCE_MODE=http` + `RAG_BASE_URL` | Phase 5 |

Mode A means **zero runtime coupling**: your endpoint can evolve while we build.

## What you must provide per evidence item

```json
{
  "evidence_id": "e_p001_p7_t3",      // REQUIRED — stable & unique (see below)
  "paper_id": "paper_001",            // REQUIRED — never merged across papers
  "type": "table",                    // REQUIRED — text | table | figure | equation | metadata
  "content": "| Method | F1 |...",    // REQUIRED ("" allowed for image-only items)
  "reference": "Table 3",             // strongly recommended — display label
  "page": 7,                          // recommended
  "caption": "Table 3: ...",          // required for type=table/figure
  "section": "4.3 Results",           // recommended
  "table_data": {                     // REQUIRED for tables when extraction allows
    "headers": ["Method", "F1"],
    "rows": [["Ours", "91.4"]],
    "caption": "Table 3: ..."
  },
  "image": {"path": "paper_001/p7_table3.png"},  // relative to EVIDENCE_ROOT
  "score": 0.92,                      // retrieval score, pass-through
  "char_span": [1180, 1490],          // optional — enables quote highlighting
  "truncated": false,
  "metadata": {}
}
```

Bundle wrapper: `{query, papers[], evidence[], retrieval{retriever, top_k, run_id, retrieved_at}, warnings[]}`.

## Required behaviors on your side

1. **`evidence_id`** — immutable and unique per item. Preferred scheme: supplier-assigned
   (e.g. `<paper_id>_<page>_<type>_<index>`). If you cannot supply it, Person 3 derives
   `sha1(paper_id|page|type|reference)[:12]` as a fallback — but collisions then become
   our problem, so please assign it.
2. **Images** — paths must be **relative to `EVIDENCE_ROOT`** (we reject `..`, absolute
   paths and drive letters → `400 IMAGE_PATH_FORBIDDEN`). Base64 (`image.b64`) is accepted
   as an alternative if cross-process paths are impractical.
3. **Tables** — supply `table_data` whenever structured extraction succeeds. It lets us
   compute rankings/deltas deterministically (no LLM guessing) and cite exact cells.
   If it is incomplete (merged headers etc.), set `metadata.table_extraction = "partial"`
   — we will fall back to the table image.
4. **Type accuracy** — `type` drives agent routing; misclassifying a table as `text`
   silently changes which agent answers.
5. **`retrieval` block** — needed to separate retrieval errors from reasoning errors in
   the evaluation (EVALUATION.md §6).
6. **Stability** — additive changes only within contract v1; breaking changes get a new
   version and a heads-up.

## Conformance test

`tests/integration/test_contract_conformance.py` (Person 3, Phase 5) validates any payload
you produce. Run it against a sample of your real output before Phase 5 exits.

## Questions to resolve in review

1. HTTP endpoint shape for Mode B (method, params, response wrapper) — draft from your side,
   we adapt the `HttpEvidenceProvider`.
2. Are images produced as files or base64?
3. Will `top_k` be fixed per question, or configurable by us?
