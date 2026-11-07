"""Append development execution provenance using the original StateReducer CAS."""

from __future__ import annotations

from datetime import datetime

from src.memory.incremental_store import apply_state_event
from src.repositories.memory_journal import MemoryJournalRepository
from src.schemas.research_state import ResearchStateSnapshot
from src.schemas.research_v2_collaboration import (
    AnalystResult,
    Confidence,
    Coverage,
    SlotDisposition,
    SlotDispositions,
)
from src.schemas.research_v2_shared import Reference, Revision, reference
from src.services.research_v2_collaboration.state import Mutation, StateReducer


def retain_development_revision(
    reducer: StateReducer,
    journal: MemoryJournalRepository,
    *,
    state: ResearchStateSnapshot,
    task_id: str,
    stage: str,
    execution: object,
    at: datetime,
) -> Revision:
    """Retain exact State/output ancestry without inventing v2 PIT Claim receipts.

    Original accepted claims remain in the v1 development State. Its reference
    is a dependency, not an automatically eligible v2 Claim; coverage is PARTIAL.
    This deliberately does not finalize or publish production State.
    """
    plan = reducer.plan
    if (
        str(state.asset_id) not in plan.requested_assets
        or state.research_as_of != plan.research_as_of
    ):
        raise ValueError("DEVELOPMENT_REVISION_SCOPE_CUTOFF")
    if "research_manager" not in plan.requested_roles:
        raise ValueError("MANAGER_REVISION_PERMISSION")
    refs: list[Reference] = []
    for key, version, value in [
        (
            "g87-state-reference:" + state.research_state_id,
            "g87_development_state_reference_v1",
            {
                "original_state": state.model_dump(mode="json"),
                "production_admission": False,
            },
        ),
        (
            "g87-execution:" + task_id + ":" + stage,
            "g87_development_execution_v1",
            execution,
        ),
    ]:
        ref = reference("RECEIPT", key, version, value)
        reducer.validator.bind(ref, value)
        refs.append(ref)
    missing = SlotDisposition(
        status="MISSING_INPUT",
        reason=(
            "No new v2 PIT Claim authority; "
            "original development results remain retained dependencies"
        ),
    )
    slots = {name: missing for name in SlotDispositions.model_fields}
    slots["dependencies"] = SlotDisposition(
        status="COMPLETE", reason="Exact original State and execution receipt bytes"
    )
    confidence = Confidence(
        level="UNKNOWN",
        meaning="UNCALIBRATED_RESEARCH_CONFIDENCE_NOT_RETURN_PROBABILITY",
        reason="Development provenance only",
        support=(),
    )
    result = AnalystResult(
        schema_version="analyst_result_v2",
        result_id=task_id + ":" + stage,
        run_id=plan.run_id,
        episode=plan.episode,
        plan=plan.reference,
        participant="research_manager",
        scope_id=str(state.asset_id),
        research_as_of=plan.research_as_of,
        generated_at=at,
        read_state=reducer.head.revision.state,
        model=plan.model,
        prompt=plan.prompt,
        producer_build=plan.producer_build,
        coverage=tuple(
            Coverage(
                scope_id=str(state.asset_id),
                role="research_manager",
                capability=slot.capability,
                status="MISSING_INPUT",
                reason="Development review does not grant v2 PIT Claim authority",
                required=slot.required,
                missing_items=("v2_claim_authority",),
                applicability_rule=slot.applicability_rule,
                evidence_refs=(),
            )
            for slot in plan.slots
            if slot.scope_id == str(state.asset_id) and slot.role == "research_manager"
        ),
        slot_dispositions=SlotDispositions(**slots),
        findings=(),
        claims=(),
        evidence_refs=(),
        quantitative_facts=(),
        hypotheses=(),
        risks=(),
        catalysts=(),
        contradictions=(),
        uncertainties=(),
        open_questions=(),
        followup_requests=(),
        confidence=confidence,
        dependencies=tuple(refs),
    )
    event = reducer.make_event(
        Mutation(kind="ANALYST", value=result),
        "research_manager",
        at,
        task_id + ":" + stage,
        read_set=(reducer.head.revision.state,),
    )
    return apply_state_event(journal, reducer, event).revision
