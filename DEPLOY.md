# ResearchLens — free-first public deployment

Two repos, two services. Deploy both; the UI is served by the reasoning
service and talks to the retrieval service.

```
browser ──> reasoning (Render free, CPU) ──> retrieval (HF Spaces, 16 GB CPU)
   │                    │                              │
   │              /ui + /api/v1/*               /retrieve /ingest-pdf
   │              needs INFERENCE_URL           /papers/* /health
```

## 1. Hosting choice (free-first, verified limits)

| Service | Host | Why |
|---|---|---|
| Reasoning (this repo) | **Render free web service** (Docker, 0.1 CPU / 512 MB) | Light deps (fastapi/httpx/pillow/pydantic). No torch. Fits 512 MB. |
| Retrieval (`multimodal_rag_retrieval_person2`) | **Hugging Face Spaces, Docker SDK, CPU Basic (2 vCPU / 16 GB, free)** | Needs torch + transformers + Chroma + cross-encoder (~2 GB RAM). Render free (512 MB, no disk) **cannot** run it. |

### Hard limits you must know before going public
- **Render free sleeps after 15 min idle** (~1 min cold start), **ephemeral
  filesystem** (local changes lost on restart), **750 h/month**, no disk,
  no SSH. The reasoning service is stateless, so this is fine.
- **HF Spaces free sleeps after ~48 h idle** (auto-wakes on visit); disk is
  **not persistent** either. Uploaded papers/indexes survive only in
  memory/disk until the Space restarts — see §4.
- **No free GPU**: HF CPU Basic has no GPU; GPU Spaces start at $0.40/h
  (paid). Local `qwen2.5vl:3b` vision cannot run on either free tier —
  see §3.

## 2. What to create (accounts needed — your approval)

1. **GitHub**: two empty repos (you create these; URLs go to me for
   `git remote add` + push).
2. **Render** (free account): New → Web Service → connect main repo.
   Build: Docker. Health check: `/api/v1/health`.
3. **Hugging Face** (free account): new **Docker** Space for the retrieval
   repo (needs `README.md` with `sdk: docker`; template below).
4. **Inference** (free tier, needs your key): an OpenAI-compatible gateway
   with a free tier (e.g. OpenRouter / Together / Groq — pick one, create a
   **limited** key). No accounts are created by me.

## 3. Model inference (no local Ollama in the cloud)

`MODEL_PROVIDER=openai_compat` (new `app/models/openai_compat.py`,
`/chat/completions` + `image_url` vision parts + `response_format` JSON
mode). Configure per role via env:

```
OPENAI_COMPAT_BASE_URL=https://openrouter.ai/api/v1   # your gateway
OPENAI_COMPAT_API_KEY=<secret, dashboard only>
ANALYZER_MODEL=<gateway text model id>
TEXT_MODEL / TABLE_MODEL / JUDGE_MODEL / GENERATOR_MODEL=<text model id>
VISION_MODEL=<gateway vision model id>   # must accept image_url
```

Reality check on `qwen2.5:1.5b` / `qwen2.5vl:3b`:
- Exact Ollama tags are generally **not** hosted verbatim on gateways.
  Use the gateway's closest equivalents (e.g. a small Qwen2.5-Instruct
  text model + a Qwen2.5-VL vision model) and record the mapping in
  `DEPLOYED_MODELS.md`. Deterministic gates (numeric grounding, table
  ops, citation resolution) are provider-agnostic and keep working.
- Vision on a free CPU gateway is slow; `/ask` timeouts are raised for
  prod (`PROVIDER_TIMEOUT_MS=120000`, `AGENT_TIMEOUT_MS=180000`).
- **Zero-cost fallback**: `MODEL_PROVIDER=mock` serves the UI/health
  without any inference (honest degraded answers). Good for a first
  public smoke test before attaching a key.

## 4. Persistence warning (read this)

- Render free has **no persistent disk**: the reasoning service stores
  nothing locally, so nothing is lost there.
- HF Spaces free disk is **not persistent** either: `chroma_db/`,
  `data/ingested/`, and `/tmp/p2_ingest` figure bytes **vanish on Space
  restart/sleep**. Consequences:
  - Uploaded PDFs must be re-uploaded after a restart.
  - The bundled `data/processed_papers.json` corpus (incl. KEHNN +
    `arch.png`) is baked into the Docker image, so the demo corpus
    **always** re-indexes on boot — the public demo stays queryable.
  - User uploads are explicitly **demo-ephemeral**; the UI states this.
- Paid fix (later): HF persistent storage / Render disk + Postgres.
  Not configured here to stay free.

## 5. Deploy steps

### A. Retrieval → Hugging Face Space (Docker)
1. In the retrieval repo, the `Dockerfile` + `README.md` (sdk: docker)
   below are the Space source — push the repo, create a Docker Space,
   set its files to this repo content (or `git push` to the Space remote).
2. Space exposes port **7860**; the app reads `$PORT`. Health: `GET /health`.
3. Note the public URL: `https://<you>-<space>.hf.space`.

### B. Reasoning → Render (Docker)
1. Push the main repo. Render → New → Web Service → select repo.
2. `render.yaml` is the blueprint (replace `<SET-ME>` repo URLs, or set
   env in the dashboard instead).
3. Required env: `MODEL_PROVIDER=openai_compat`, `OPENAI_COMPAT_BASE_URL`,
   `OPENAI_COMPAT_API_KEY` (secret), role model ids, `RETRIEVAL_MODE=http`,
   `RETRIEVAL_BASE_URL=https://<space>.hf.space`, `REASONING_ENV=prod`,
   `CORS_ORIGINS=*` (or your domain).
4. Health: `GET /api/v1/health`. UI: `GET /ui`.

### C. Wire + verify (definition of deployed)
1. `GET https://<retrieval> /health` → healthy.
2. `GET https://<reasoning>/api/v1/health?deep=true` → provider reachable.
3. `POST <retrieval>/papers/search?q=...` → hits.
4. `POST <reasoning>/api/v1/ask` (text + table + figure) → supported
   answers with citations on the demo corpus.
5. `POST <retrieval>/ingest-pdf` with a small PDF → indexed → `/ask`
   answers about it (until Space sleeps).
6. Only then is it "deployed".

## 6. Safety rails added for public demo
- `DISABLE_UPLOADS=true` env kills heavy ingest endpoints (503) if abused
  (wired in retrieval `app.py`; reasoning has `disable_uploads` config).
- 32 MiB upload cap, magic-byte check, streaming reads (no full-file
  buffering), SSRF allowlist (arxiv hosts only), CORS configurable.
- Timeouts raised for cloud inference; bounded vision retries unchanged.
- No secrets in repo: `.env.example` documents keys; real keys live in
  dashboard secret stores only.

## 7. Files added for deployment
- Main: `Dockerfile`, `render.yaml`, `app/models/openai_compat.py`,
  `tests/unit/test_openai_compat_provider.py`, `DEPLOY.md` (this file).
- Retrieval: `Dockerfile`, `render.yaml` (paid-only warning),
  `README.md` Space header (sdk: docker, port 7860), `DEPLOY.md` pointer.
