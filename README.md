# ResearchLens — Reasoning Module (Person 3)

**Multi-LLM · Multimodal · Evidence-Verified Reasoning Service for Scientific Literature.**

This repository contains the **reasoning subsystem** of ResearchLens: a high-scalability
multi-LLM multimodal RAG research-paper intelligence platform.

Person 3 owns:

| Area | Components |
|---|---|
| Multi-LLM reasoning | specialized agents + model routing |
| Multimodal reasoning | text / table / figure reasoning |
| Scientific text reasoning | claims, limitations, experimental context |
| Query decomposition | query analyzer, task planning |
| Agent orchestration | parallel execution, failure isolation |
| Evidence verification | judge/verifier, hallucination detection |
| Citation grounding | deterministic citation attachment |
| Final answer generation | grounded synthesis |
| Cross-paper reasoning | paper-identity-preserving pipelines |
| Evaluation | benchmarks, ablations, metrics |
| Service | FastAPI reasoning-service API |

**Not owned here:** PDF ingestion (Person 1), primary RAG retrieval/indexing (Person 2),
frontend/UI (Person 4). Integration happens through versioned contracts only —
see [API_SPEC.md](API_SPEC.md).

---

## Status

**Phase 0 — Planning & Design (in review).** No implementation code yet.

| Document | Purpose |
|---|---|
| [PRD.md](PRD.md) | Product requirements, scope (MVP / research-grade / future) |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Components, agent boundaries, model abstraction, scalability |
| [API_SPEC.md](API_SPEC.md) | Data contracts, endpoints, Person 2 & Person 4 integration |
| [EVALUATION.md](EVALUATION.md) | Research questions, systems A–D, metrics, ablations |
| [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) | Phases, acceptance criteria, risks, dependencies |
| [SECURITY.md](SECURITY.md) | Threat model, prompt zones, input validation |

## Research question

> Does multi-LLM collaborative reasoning and verification improve the accuracy and
> factual grounding of multimodal RAG for scientific paper question answering?

Baseline A (single LLM + RAG) → System B (multimodal RAG + single LLM) →
System C (multimodal RAG + multi-LLM) → System D (System C + Judge).

## Local-first

Python · FastAPI · Pydantic · Ollama. **No paid API is mandatory.**
Cloud models are optional providers behind the same `ModelProvider` interface.

## Quickstart (after implementation begins)

```bash
pip install -e ".[dev]"
cp .env.example .env
ollama serve
uvicorn app.main:app --reload
pytest
```

## Repository layout

See [ARCHITECTURE.md § Repository structure](ARCHITECTURE.md#8-repository-structure).
