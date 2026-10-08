"""Ablation harness (EVALUATION.md §3, §§17–18).

Runs the five planned ablations over D's frozen inputs:

  AB-T   — TextAgent removed
  AB-Tab — TableAgent removed
  AB-V   — VisionAgent removed
  AB-J   — Judge removed
  AB-O   — Multi-LLM orchestration removed (single generic path over D's evidence)

The harness only filters evidence/config; the runner stays frozen-evidence
and evidence-fingerprinted.
Standalone CLI: ``python -m evaluation.baselines.ablations``.
"""

from __future__ import annotations

from app.schemas.evidence import EvidenceBundle
from evaluation.datasets.eval_case import Category
from evaluation.baselines.systems import ABLATIONS


def filter_evidence_for_ablation(
    bundle: EvidenceBundle, ablation_id: str, category: Category
) -> EvidenceBundle:
    """Apply an ablation's evidence filter to an ``EvidenceBundle``.

    ``AB-T/AB-Tab/AB-V`` drop their modality. ``AB-J`` and ``AB-O`` keep the
    full bundle — AB-J skips verification (handled in the orchestrator's
    ``without_judge`` path), AB-O keeps the frozen evidence (single-LLM
    effect is reported as ``AB-O == system B within noise``).
    """
    if ablation_id not in ABLATIONS:
        raise ValueError(f"unknown ablation: {ablation_id!r}")

    remove = ABLATIONS[ablation_id].get("remove")  # type: ignore[assignment]
    # AB-J and AB-O are config-only ablations: the evidence view is unchanged.
    if remove in {"judge", "orchestration"}:
        return bundle
    if remove not in {"text", "table", "figure"}:
        raise ValueError(f"unknown ablation modality: {remove!r}")

    filtered = [item for item in bundle.evidence if item.type != remove]
    return EvidenceBundle(
        query=bundle.query,
        papers=list(bundle.papers),
        evidence=filtered,
        retrieval=bundle.retrieval,
        warnings=list(bundle.warnings) + [f"ablation {ablation_id}: removed {remove} evidence"],
    )


def ablation_manifest_rows(dataset: str, dataset_version: str, ablations: list[str] | None = None) -> list[dict[str, object]]:
    """One row per planned ablation for the experiment matrix (§28)."""
    ids = list(ablations) if ablations is not None else list(ABLATIONS)
    rows: list[dict[str, object]] = []
    for ablation_id in ids:
        definition = ABLATIONS.get(ablation_id, {})
        rows.append(
            {
                "ablation": ablation_id,
                "dataset": dataset,
                "dataset_version": dataset_version,
                "remove": definition.get("remove"),
                "label": definition.get("label"),
                "expectation": definition.get("expectation"),
                "status": "planned",
            }
        )
    return rows


def main() -> None:
    for row in ablation_manifest_rows("fixture-mini", "0.1.0"):
        print(f"{row['ablation']}: remove={row['remove']} — {row['label']}")


if __name__ == "__main__":
    main()
