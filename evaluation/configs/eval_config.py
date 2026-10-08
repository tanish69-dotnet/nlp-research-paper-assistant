"""Typed evaluation configuration (EVALUATION.md §2, §7)."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SystemId = Literal["A", "B", "C", "D"]


class ModelVersions(BaseModel):
    """Resolved model identifiers used in this run."""

    model_config = ConfigDict(extra="forbid")

    provider: str | None = None
    analyzer: str | None = None
    text: str | None = None
    table: str | None = None
    vision: str | None = None
    judge: str | None = None
    generator: str | None = None


class PromptVersions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analyzer: str | None = None
    text: str | None = None
    table: str | None = None
    vision: str | None = None
    judge: str | None = None
    generator: str | None = None


class Manifest(BaseModel):
    """Authoritative run descriptor — one row per :class:`EvalConfig` execution."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    git_sha: str
    timestamp: str
    system: SystemId
    dataset: str
    dataset_version: str
    split: str
    seed: int
    model_provider: str
    model_versions: ModelVersions
    prompt_versions: PromptVersions
    evidence_fingerprint: str | None = None
    case_count: int = Field(ge=0)
    status: Literal["ok", "failed", "partial"] = "ok"


class EvalConfig(BaseModel):
    """Typed harness configuration (one file per experiment).

    A JSON file rather than YAML keeps the run offline and dependency-free
    (no extra parser needed).
    """

    model_config = ConfigDict(extra="forbid")

    system: SystemId = "D"
    dataset: str = "fixture-mini"
    dataset_version: str = "0.1.0"
    split: str = "all"
    seed: int = 17
    model_provider: str = "mock"
    model_versions: ModelVersions = Field(default_factory=ModelVersions)
    prompt_versions: PromptVersions = Field(default_factory=PromptVersions)
    max_examples: int | None = Field(default=None, ge=1)
    output_dir: str | None = Field(default=None, description="Base dir for results")
    evidence_frozen: bool = True
    include_analysis: bool = False

    @field_validator("output_dir")
    @classmethod
    def _not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("output_dir must be blank or a real path")
        return value.strip()

    def run_id(self, git_sha: str | None = None, override: str | None = None) -> str:
        """Deterministic ``run_id`` (EVALUATION.md §8: ``<system>_<dataset>_<date>_<seed>``).

        When ``git_sha`` is known, the short-SHA suffix disambiguates re-runs
        on different commits without forcing the caller to carry it.
        """
        if override:
            return override
        date = datetime.now(timezone.utc).strftime("%Y%m%d")
        base = f"{self.system}_{self.dataset}_{date}_{self.seed}"
        short = (git_sha or "")[:7]
        return f"{base}_{short}" if short and short != "unknown" else base

    def result_path(self, results_root: Path, git_sha: str | None = None, override_id: str | None = None) -> Path:
        run_id = self.run_id(git_sha=git_sha, override=override_id)
        root = Path(self.output_dir) if self.output_dir else results_root
        return root / run_id

    def fingerprint(self) -> str:
        """Stable short-hash for determinism checks — not for cryptographic use."""
        blob = self.model_dump_json(exclude={"output_dir"})
        return sha256(blob.encode("utf-8")).hexdigest()[:12]
