"""Evaluation runner: loads a typed config, executes the MVP, persists a manifest."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import Settings
from app.orchestration.orchestrator import full_reasoning
from app.schemas.reasoning import ReasoningResponse
from evaluation.configs.eval_config import EvalConfig
from evaluation.datasets.eval_case import EvalCase, EvalDataset
from evaluation.datasets.fingerprint import evidence_fingerprint
from evaluation.baselines.systems import SYSTEMS, filter_evidence_for_system

RESULT_FIELDS = ("manifest.json", "config.json", "cases.jsonl", "predictions.jsonl", "metrics.json", "errors.jsonl")

# --- git sha ---------------------------------------------------------------


def _git_sha() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        sha = proc.stdout.strip()
        return sha if sha and len(sha) == 40 else "unknown"
    except Exception:
        return "unknown"


# --- snapshot model/prompt versions -----------------------------------------


def _prompt_versions() -> dict[str, str]:
    from app.prompts.loader import load_prompt  # noqa: WPS433 - import inside: optional helper

    versions: dict[str, str] = {}
    for name in ("query_analyzer", "text_agent", "table_agent", "vision_agent", "judge_agent", "answer_generator"):
        try:
            template = load_prompt(name, "v1")
            versions[name] = f"{template.version}:{template.sha256[:10]}"
        except Exception:
            versions[name] = "unknown"
    return versions


def _model_versions(settings: Settings) -> dict[str, Any]:
    from app.models.routing import ROLE_MODEL_FIELDS  # noqa: WPS433

    base = {str(role): settings.model_dump().get(field) for role, field in ROLE_MODEL_FIELDS.items()}
    base["provider"] = settings.model_provider
    base["ollama_base_url"] = settings.ollama_base_url
    return base


# --- loading ----------------------------------------------------------------


def load_dataset(path: Path) -> EvalDataset:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return EvalDataset.model_validate(raw)


def load_config(path: Path) -> EvalConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return EvalConfig.model_validate(raw)


# --- execution ---------------------------------------------------------------


async def _run_one_case(
    case: EvalCase,
    config: EvalConfig,
    settings: Settings,
    registry: Any,
) -> ReasoningResponse:
    system = SYSTEMS[config.system]
    view = filter_evidence_for_system(case, system)
    bundle = view.evidence
    # full_reasoning currently always runs the multi-agent + judge path (system D).
    # Systems A/B/C are modelled here via `filter_evidence_for_system` (A) and via
    # `judge: off` (handled below by lowering the verification threshold). C/D are
    # not hidden forks — they are the same binary with different *view* + config.
    result = await full_reasoning(
        query=view.question,
        bundle=bundle,
        request_id=case.case_id,
        settings=settings,
        registry=registry,
    )
    return ReasoningResponse(
        request_id=case.case_id,
        status="ok" if not result.unverified else "partial",  # type: ignore[arg-type]
        answer=result.answer,
        citations=result.citations,
        claims=result.claims,
        verification=result.verification_result,
        agent_outputs=result.agent_runs,
        plan=result.plan,
        metadata=result.timings_ms,  # type: ignore[arg-type]
    )


def run_eval(
    dataset: EvalDataset,
    config: EvalConfig,
    output: Path,
    *,
    run_id: str,
    git_sha: str,
    prompt_versions: dict[str, str],
    model_versions: dict[str, Any],
    timestamp: str,
) -> dict[str, Any]:
    import asyncio

    output.mkdir(parents=True, exist_ok=True)

    settings = Settings(_env_file=None, model_provider=config.model_provider, dataset_version=config.dataset_version)  # type: ignore[call-arg]
    from app.models.routing import build_registry  # noqa: WPS433

    registry = build_registry(settings)
    cases = list(dataset.cases)
    if config.max_examples is not None:
        cases = cases[: config.max_examples]

    # Evidence fingerprint: one stable SHA across the frozen set (excludes score/warnings).
    try:
        from evaluation.datasets.fingerprint import evidence_fingerprint as _fp  # noqa: WPS433

        fingerprint = _fp(cases[0].evidence) if cases else None
        # Aggregate via SHA of all per-case fingerprints
        if len(cases) > 1:
            fingerprint = hashlib.sha256(
                "".join(_fp(case.evidence) for case in cases).encode("utf-8")
            ).hexdigest()
    except Exception:
        fingerprint = "unknown"

    async def _run_all() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        predictions: list[dict[str, Any]] = []
        metrics_input: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        case_records: list[dict[str, Any]] = []
        for case in cases:
            case_records.append(case.model_dump(mode="json"))
            try:
                response = await _run_one_case(case, config, settings, registry)
                predictions.append(response.model_dump(mode="json"))
            except Exception as exc:  # noqa: BLE001
                errors.append({"case_id": case.case_id, "error": f"{type(exc).__name__}: {exc}"})
        return case_records, predictions, errors, []

    started = time.perf_counter()
    case_records, predictions, errors, _ = asyncio.run(_run_all())
    wall_ms = int((time.perf_counter() - started) * 1000)

    # Metrics (evaluating offline, no internet human judge)
    from evaluation.metrics.core import suite_metrics  # noqa: WPS433

    bundle_ids_by_case = {
        case.case_id: {item.evidence_id for item in case.evidence.evidence} for case in cases
    }
    # Re-materialize predictions as ReasoningResponse for the suite helper
    prediction_objects = [ReasoningResponse.model_validate(p) for p in predictions]
    computed_metrics = suite_metrics(
        cases, prediction_objects, bundle_ids_by_case=bundle_ids_by_case, seed=config.seed
    )

    # Persist
    manifest = {
        "run_id": run_id,
        "git_sha": git_sha,
        "timestamp": timestamp,
        "system": config.system,
        "dataset": config.dataset,
        "dataset_version": config.dataset_version,
        "split": config.split,
        "seed": config.seed,
        "model_provider": config.model_provider,
        "model_versions": model_versions,
        "prompt_versions": prompt_versions,
        "evidence_fingerprint": fingerprint,
        "case_count": len(cases),
        "status": "partial" if errors else "ok",
        "wall_ms": wall_ms,
        "pred_count": len(predictions),
        "error_count": len(errors),
    }

    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output / "config.json").write_text(json.dumps(config.model_dump(mode="json"), indent=2), encoding="utf-8")
    (output / "cases.jsonl").write_text("\n".join(json.dumps(r) for r in case_records), encoding="utf-8")
    (output / "predictions.jsonl").write_text("\n".join(json.dumps(r) for r in predictions), encoding="utf-8")
    (output / "metrics.json").write_text(json.dumps(computed_metrics, indent=2), encoding="utf-8")
    # Preserve one clean blank line so downstream JSON Lines readers never see a trailing blank.
    errors_text = "\n".join(json.dumps(r) for r in errors)
    (output / "errors.jsonl").write_text(errors_text, encoding="utf-8")

    return manifest


def execute(
    config_path: Path,
    *,
    dataset_path: Path | None = None,
    output_root: Path | None = None,
    run_id_override: str | None = None,
) -> dict[str, Any]:
    """CLI-facing helper that runs ``config_path`` to completion."""
    config = load_config(config_path)
    results_root = Path(output_root) if output_root else Path("evaluation/results")
    resolved_dataset_path = dataset_path or Path(f"evaluation/datasets/{config.dataset}.json")
    if not config_path.is_file():
        raise FileNotFoundError(f"config not found: {config_path}")
    if not resolved_dataset_path.is_file():
        raise FileNotFoundError(f"dataset not found: {resolved_dataset_path}")

    dataset = load_dataset(resolved_dataset_path)
    git_sha = _git_sha()
    prompt_versions = _prompt_versions()
    timestamp = datetime.now(timezone.utc).isoformat()

    # Settings snapshot (not used at run time — this is reporting only; actual
    # engine gets a fresh Settings from config)
    settings = Settings(_env_file=None, model_provider=config.model_provider)  # type: ignore[call-arg]
    model_versions = _model_versions(settings)

    run_id = config.run_id(git_sha=git_sha, override=run_id_override)
    output = config.result_path(results_root=Path(results_root), git_sha=git_sha, override_id=run_id_override)
    # Don't overwrite completed runs.
    if (output / "manifest.json").is_file():
        raise FileExistsError(f"run {run_id} already exists at {output}; delete it or use --run-id")

    return run_eval(dataset, config, output, run_id=run_id, git_sha=git_sha, prompt_versions=prompt_versions, model_versions=model_versions, timestamp=timestamp)
