# Contributing — ResearchLens Reasoning Module

## Workflow (per phase)

```
PLAN → IMPLEMENT → TEST → REVIEW → FIX → DOCUMENT → COMMIT → NEXT PHASE
```

Detailed phases, acceptance criteria and risks: [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md).

## Ground rules

1. **No untested claims.** Report test output (command + counts), never intent.
2. **No placeholders labelled complete.** Stubs must say `stub` in code and be listed as deferred in the phase report.
3. **Small, meaningful commits.** One commit = one coherent change; never mix unrelated phases.
4. **Docs travel with code.** Schemas, API_SPEC and ARCHITECTURE must match reality after each phase.
5. **Contracts are frozen artifacts.** Changes to `EvidenceBundle` / `ReasoningResponse` require a changelog entry in API_SPEC and a note to the affected teammate (Person 2 / Person 4).
6. **No fabricated results.** Every evaluation number traces to `evaluation/results/<run_id>/`.

## Code standards

- Python 3.11+; type hints everywhere; `mypy` clean on `app/`.
- Pydantic models for every boundary; `extra="forbid"` on request/response models; no untyped `dict` passing between components.
- Async-first: no blocking I/O on the event loop.
- Model calls only through `ModelProvider`; never a provider SDK inside an agent.
- Prompts live in `app/prompts/versions/<version>/` as files — never inline strings.
- Errors: raise domain exceptions from `app/core/errors.py`; routes translate to `ProblemDetail`.
- Logging: `structlog` with `request_id` bound; never log evidence bodies, prompts in full, or keys.

## Testing

```bash
pytest                 # full suite — must pass offline, no Ollama required
pytest tests/unit      # fast
pytest -k injection    # security fixtures
```

- Unit tests use `MockProvider` and `tests/fixtures/`.
- Integration tests cover `/reason` end-to-end on `mock_evidence.json`.
- Security tests (path traversal, prompt injection, size caps) are mandatory for touched code.

## Review checklist (self or peer)

- [ ] Acceptance criteria of the phase met, with evidence
- [ ] Tests added for new behavior; failure paths covered
- [ ] Schemas/ARCHITECTURE/API_SPEC updated or deviations recorded
- [ ] No secrets, no large binaries, no datasets committed
- [ ] Degradation paths behave (`metadata.degraded` correct)
- [ ] Citations still resolve only from supplied evidence

## Commits

```
<phase>: <imperative summary>

Phase: 3 — Table + Vision agents
Tests: pytest -q → 84 passed in 6.2s
```
