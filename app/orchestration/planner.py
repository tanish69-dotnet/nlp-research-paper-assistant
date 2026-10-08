"""Task planner (ARCHITECTURE §3.1, §4.7 — Phase 2 scope).

The planner turns the QueryPlan's abstract tasks into concrete, evidence-routed
PlannedTasks. Only the Text Agent exists in Phase 2, so table and figure tasks
are explicitly deferred — never faked through the text agent (important).
"""

from __future__ import annotations

from app.config import Settings
from app.schemas.analysis import PlannedTask
from app.schemas.evidence import EvidenceBundle
from app.schemas.query import QueryPlan

# Which agents exist in this phase.
_AGENTS_FOR_MODALITY: dict[str, str | None] = {
    "text": "text_reasoner",
    "table": None,
    "figure": None,
    "equation": None,
    "metadata": None,
}

#: Phase 3+ reason why a modality is deferred.
_DEFERRED_REASONS = {
    "table": "table_reasoning_agent not implemented yet (Phase 3)",
    "figure": "vision_reasoning_agent not implemented yet (Phase 3)",
    "equation": "equation handling is planned for a later phase",
    "metadata": "metadata tasks are not routed to an agent",
}


def plan_tasks(
    plan: QueryPlan, bundle: EvidenceBundle, settings: Settings
) -> list[PlannedTask]:
    """Route every :class:`AgentTask` in ``plan`` to an agent or a deferred status.

    Also adds reference-only tasks for explicit mentions that the plan's task
    list did not cover (reference coverage).
    """
    by_evidence_id = {item.evidence_id: item for item in bundle.evidence}
    by_reference = {item.reference: item.evidence_id for item in bundle.evidence if item.reference}
    modality_evidence: dict[str, list[str]] = {m: [] for m in _AGENTS_FOR_MODALITY}
    for item in bundle.evidence:
        modality_evidence.setdefault(item.type, []).append(item.evidence_id)

    tasks: list[PlannedTask] = []

    for index, raw in enumerate(plan.tasks):
        modality = raw.modality
        agent = _AGENTS_FOR_MODALITY.get(modality)

        # Bind claimed evidence_ids to the ones that actually exist in the bundle.
        evidence_ids = [eid for eid in raw.evidence_ids if eid in by_evidence_id]
        if not evidence_ids:
            for ref in raw.target_references:
                if ref in by_reference:
                    evidence_ids.append(by_reference[ref])
            if not evidence_ids and modality_evidence.get(modality):
                evidence_ids = list(modality_evidence[modality])

        sq_ids = [sq.id for sq in plan.sub_questions if raw.task in sq.text]

        if agent is not None:
            status = "executable"
            reason = "ready to run"
            if not evidence_ids:
                status = "skipped"
                reason = f"no evidence of type '{modality}' available"
        else:
            status = "deferred"
            reason = _DEFERRED_REASONS.get(modality, "agent not implemented yet")
            agent = None  # type: ignore[assignment]

        tasks.append(
            PlannedTask(
                task_id=f"t{index + 1}",
                task=raw.task,
                modality=raw.modality,
                agent=agent,  # type: ignore[arg-type]
                status=status,  # type: ignore[arg-type]
                reason=reason,
                target_references=list(raw.target_references),
                evidence_ids=evidence_ids,
                sub_question_ids=sq_ids,
            )
        )

    # Add reference-coverage tasks for target_references that no task addressed.
    covered = {ref for task in tasks for ref in task.target_references}
    for ref in plan.target_references:
        if ref in covered:
            continue
        lower = ref.strip().lower()
        modality = "figure" if lower.startswith("figure") or lower.startswith("fig") else "table" if lower.startswith("table") else "text"
        agent = _AGENTS_FOR_MODALITY.get(modality)
        tasks.append(
            PlannedTask(
                task_id=f"t{len(tasks) + 1}",
                task=f"handle {ref}",
                modality=modality,  # type: ignore[arg-type]
                agent=agent,  # type: ignore[arg-type]
                status=(
                    "executable"
                    if agent == "text_reasoner" and modality_evidence.get("text")
                    else "deferred"
                    if agent is None
                    else "skipped"
                ),
                reason=(
                    "reference binding from plan.target_references"
                    if agent == "text_reasoner"
                    else _DEFERRED_REASONS.get(modality, "agent not implemented yet")
                ),
                target_references=[ref],
                evidence_ids=[by_reference[ref]] if ref in by_reference else [],
            )
        )

    return tasks
