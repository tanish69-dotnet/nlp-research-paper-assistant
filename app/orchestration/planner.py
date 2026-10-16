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
    "table": "table_reasoner",
    "figure": "vision_reasoner",
    "equation": None,
    "metadata": None,
}

#: Phases 3+ deferred reasons (only modalities still without an agent appear).
_DEFERRED_REASONS = {
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
    # Keep all matches: a PDF can legitimately expose multiple extracted
    # image records with the same human reference (for example, a split
    # Figure 1).  More importantly, bind references only within the task's
    # modality so a text task mentioning Figure 1 cannot receive a figure id
    # and then be reduced to ``no_evidence`` by TextAgent.
    by_reference: dict[str, list[str]] = {}
    for item in bundle.evidence:
        if item.reference:
            by_reference.setdefault(item.reference, []).append(item.evidence_id)
    modality_evidence: dict[str, list[str]] = {m: [] for m in _AGENTS_FOR_MODALITY}
    for item in bundle.evidence:
        modality_evidence.setdefault(item.type, []).append(item.evidence_id)

    tasks: list[PlannedTask] = []

    for index, raw in enumerate(plan.tasks):
        modality = raw.modality
        agent = _AGENTS_FOR_MODALITY.get(modality)

        # Bind claimed evidence_ids to the ones that actually exist in the bundle.
        # Never assign evidence of another modality merely because a model
        # echoed an id.  Specialist agents must receive the evidence they were
        # actually routed to handle.
        evidence_ids = [
            eid
            for eid in raw.evidence_ids
            if eid in by_evidence_id and by_evidence_id[eid].type == modality
        ]
        if not evidence_ids:
            for ref in raw.target_references:
                evidence_ids.extend(
                    eid
                    for eid in by_reference.get(ref, [])
                    if by_evidence_id[eid].type == modality
                )
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
        has_evidence = bool(modality_evidence.get(modality))
        # Executable assignment follows implemented agents; only when that modality
        # has actual evidence in the bundle. Otherwise skipped.
        if agent is not None:
            status = "executable" if has_evidence else "skipped"
            reason = (
                "reference binding from plan.target_references"
                if has_evidence
                else f"no evidence of type '{modality}' available"
            )
        else:
            status = "deferred"
            reason = _DEFERRED_REASONS.get(modality, "agent not implemented yet")
        tasks.append(
            PlannedTask(
                task_id=f"t{len(tasks) + 1}",
                task=f"handle {ref}",
                modality=modality,  # type: ignore[arg-type]
                agent=agent,  # type: ignore[arg-type]
                status=status,  # type: ignore[arg-type]
                reason=reason,
                target_references=[ref],
                evidence_ids=[
                    eid
                    for eid in by_reference.get(ref, [])
                    if by_evidence_id[eid].type == modality
                ],
            )
        )

    return tasks


def evidence_for_modality_tasks(
    tasks: list[PlannedTask], bundle: EvidenceBundle, modality: str
) -> tuple:
    """Return the evidence IDs assigned to one modality, in bundle order."""
    assigned = {
        evidence_id
        for task in tasks
        if task.modality == modality and task.status == "executable"
        for evidence_id in task.evidence_ids
    }
    return tuple(item for item in bundle.evidence if item.evidence_id in assigned)
