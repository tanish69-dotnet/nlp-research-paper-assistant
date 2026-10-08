"""Dataset registry + graft (EVALUATION.md §§4–11 — no invented data).

``dataset_registry.json`` holds one row per known dataset with
``availability: {available, reason, license, source, local_path}``. Helper
functions in this module read it, gate experiments, and surface the same
information in every run manifest so paper tables are reproducible.

Gating rules (Phase 6 §8):
- the mini fixture ``fixture-mini`` is always ``available``
- a real benchmark (SPIQA, ResearchLens-XM, QASper, ...) is ``available`` only
  when its JSON evidence file exists locally and its license row is approved
- a runner that encounters ``availability: not available`` raises
  ``DatasetUnavailableError`` — empty dirs or fabricated ``0.0`` metrics are
  never written

"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

Status = Literal["available", "unavailable", "unknown"]
DatasetName = str

REGISTRY_FILE = Path("evaluation/datasets/dataset_registry.json")


class DatasetUnavailableError(FileNotFoundError):
    """Raised when an unavailable dataset is requested (no fabrication)."""


_DEFAULTS: dict[DatasetName, dict[str, Any]] = {
    "fixture-mini": {
        "version": "0.1.0",
        "path": "evaluation/datasets/fixture-mini.json",
        "license": "local fixture, built from mock evidence",
        "source": "tests/fixtures/mock_evidence.json",
        "notes": "Offline fixture (7 categories); not a benchmark.",
    },
    "spiqa": {
        "version": "replica-v1",
        "path": "evaluation/datasets/spiqa.json",
        "license": "pending",
        "source": "https://huggingface.co/datasets/spiqa (TBD)",
        "notes": "Primary benchmark — run if licensed locally; see docs/dataset_manifest.md.",
    },
    "researchlens-xm": {
        "version": "0.1.0",
        "path": "evaluation/datasets/researchlens-xm.json",
        "license": "pending",
        "source": "local papers + human labels (TBD)",
        "notes": "Controlled cross-modal set (80–120 questions).",
    },
    "qasper": {
        "version": "1.3",
        "path": "evaluation/datasets/qasper.json",
        "license": "pending",
        "source": "https://allenai.org/data/qasper",
        "notes": "Evidence annotations present.",
    },
}


def _registry_path() -> Path:
    return Path(__file__).parent / "dataset_registry.json"


def _read_registry() -> dict[str, Any]:
    path = _registry_path()
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    # Bootstrap from defaults (used before a human has produced dataset_manifest.md)
    return {"datasets": _DEFAULTS, "generated": "defaults-only"}


def _status_for(name: DatasetName, row: dict[str, Any]) -> tuple[Status, str | None]:
    path = Path(row.get("path", ""))
    if path.is_file():
        return "available", None
    if name == "fixture-mini":
        return "unavailable", f"expected fixture at {path} (run python -m evaluation.datasets.build_fixture)"
    return "unavailable", f"dataset file not found at {path}"


def dataset_status(name: DatasetName) -> dict[str, Any]:
    """One row for ``name``: ``{available, reason, version, path, license}``."""
    registry = _read_registry()
    row = dict(registry.get("datasets", {}).get(name, {}))
    if not row:
        return {
            "dataset": name,
            "status": "unknown",
            "reason": "no registry row for this dataset",
            "version": "unknown",
            "path": None,
            "license": None,
        }

    status, reason = _status_for(name, row)
    return {
        "dataset": name,
        "status": status,
        "reason": reason,
        "version": row.get("version"),
        "path": row.get("path"),
        "license": row.get("license"),
        "source": row.get("source"),
    }


def list_all_statuses() -> list[dict[str, Any]]:
    """One row per dataset row in the registry — machine-readable matrix."""
    registry = _read_registry()
    return [dataset_status(name) for name in sorted(registry.get("datasets", {}))]


def dataset_path_for(name: DatasetName) -> Path:
    row = dataset_status(name)
    if row["status"] != "available" or not row["path"]:
        raise DatasetUnavailableError(
            f"dataset_status = unavailable for {name!r}: {row.get('reason')}"
        )
    return Path(row["path"])


def write_manifest_snapshot(output_dir: Path, dataset: DatasetName, seed: int) -> dict[str, Any]:
    """Extra rows for ``runs --matrix`` and manifest tracing."""
    row = dataset_status(dataset)
    return {
        "dataset": dataset,
        "status": row["status"],
        "reason": row.get("reason"),
        "dataset_version": row.get("version"),
        "seed": seed,
        "output_dir": str(output_dir),
    }
