"""Adapter interface for external benchmarks (SPIQA / Qasper / ResearchLens-XM).

This file holds the *contract* only (Adapter Protocol + registration). Real
ingest code for a benchmark's source data lives in a separate, per-dataset
module that implements :class:`BenchmarkAdapter` (registered by dataset
name) — and never runs at test time (no files required). Determinism and the
``evidence fingerprint`` trace are carried by the registry layer (``reference
sources are frozen at publish time; availability is explicitly recorded).

Ghosts are never fabricated beyond these contracts: calling an unknown adapter
raises ``DatasetUnavailableError`` rather than inventing screenshots of a
benchmark.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from evaluation.datasets.eval_case import EvalDataset
from evaluation.datasets.registry import DatasetUnavailableError


class BenchmarkAdapter(Protocol):
    """One implementation per benchmark that can be *ingested* deterministically."""

    dataset: str
    version: str

    def is_available(self) -> bool:
        """True when source files and licensing allow an ingest."""

    def fingerprint(self) -> str | None:
        """Stable short-hash for the ingested snapshot, or ``None`` when unknown."""

    def ingest(self, out: Path, *, seed: int = 17) -> EvalDataset:
        """Deterministically map upstream JSON/Lines → ``EvalDataset`` (frozen)."""

    def manifest_row(self) -> dict[str, Any]:
        """Row describing the dataset version + provenance for the paper."""


_ADAPTERS: dict[str, Any] = {}


def register_adapter(adapter: Any) -> None:
    _ADAPTERS[adapter.dataset] = adapter


def adapter_for(dataset: str) -> BenchmarkAdapter:
    if dataset not in _ADAPTERS:
        raise DatasetUnavailableError(f"no adapter registered for dataset {dataset!r}")
    return _ADAPTERS[dataset]
