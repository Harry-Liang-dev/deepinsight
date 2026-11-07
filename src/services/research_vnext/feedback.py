"""G88 bounded feedback on the existing opt-in Coordinator and StateReducer.

No new runner, model factory, evidence authority or production admission.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import TYPE_CHECKING

from src.agents.contracts import ResearchTaskRequest
from src.memory.incremental_store import apply_state_event
from src.memory.vnext import content_sha256
from src.memory.vnext_contracts import ROLE_STAGES, Role
from src.models.enums import AgentName
from src.schemas.research_v2_shared import Revision, digest
from src.services.research_v2_collaboration.state import Mutation
from src.services.research_vnext.contracts import (
    ReviewProduct,
    TraderProduct,
    artifact,
    resolve,
)
from src.services.research_vnext.execution import (
    ROLES,
    IncrementalContext,
    IncrementalRun,
)

if TYPE_CHECKING:
    from src.agents.contracts import AgentExecutionResult
    from src.agents.coordinator import ResearchCoordinator
    from src.memory import MemoryService
    from src.memory.controlled import AdmissionReceipt
    from src.memory.vnext_contracts import ArtifactRef, MemoryReadSet, Scope
    from src.repositories.memory_journal import MemoryJournalRepository
    from src.schemas.research_v2_collaboration import AnalystResult
    from src.schemas.research_v2_shared import Reference
    from src.services.research_v2_collaboration.state import StateReducer

Refresh = Callable[
    [IncrementalRun, ReviewProduct], tuple[ResearchTaskRequest, IncrementalContext]
]


@dataclass
class FeedbackRun:
    """Keep both attempts and the terminal disposition separate from science."""

    attempts: list[IncrementalRun] = field(default_factory=list)
    status: str = "BLOCKED"
    final_revision: Revision | None = None
    scientific_status: str = "BLOCKED_MISSING_V2_SOURCE_AUTHORITY"
    rework_roles: tuple[Role, ...] = ()
    unrelated_reexecutions: int = 0


def finalize_review(run: IncrementalRun, ctx: IncrementalContext) -> Revision:
    """Finalize the development census without granting factual qualification."""
    if set(run.results) != set(ROLES) or run.state is None or not run.revisions:
        raise ValueError("INCOMPLETE_MANAGER_REVIEW")
    manager = run.results[AgentName.RESEARCH_MANAGER]
    review = manager.value
    trader = run.results["trader"].value
    if (
        not isinstance(review, ReviewProduct)
        or not isinstance(trader, TraderProduct)
        or review.decision == "RETURN_FOR_RESEARCH"
    ):
        raise ValueError("UNRESOLVED_MANAGER_REVIEW")
    if run.revisions[-1] != ctx.reducer.head.revision:
        raise ValueError("STALE_MANAGER_REVIEW_REVISION")
    for retained in run.results.values():
        if json.loads(
            resolve(retained.identity, ctx.reader)
        ) != retained.value.model_dump(mode="json"):
            raise ValueError("CHANGED_REVIEW_INPUT")
        if (
            retained.read_set.sha256,
            retained.read_set.model_dump_json(),
        ) not in ctx.journal.entries("readsets"):
            raise ValueError("UNDELIVERED_REVIEW_READSET")
    expected = tuple(
        run.results[r].identity for stage in ROLE_STAGES[:-1] for r in stage
    )
    if (
        manager.parents != expected
        or review.trader_product_sha256 != content_sha256(trader)
        or review.memory_read_set != artifact(manager.read_set)
    ):
        raise ValueError("MANAGER_PARENT_BINDING")
    if json.loads(
        resolve(review.review.working_state, ctx.reader)
    ) != run.state.model_dump(mode="json"):
        raise ValueError("MANAGER_STATE_BINDING")
    # The original reducer validates the actual census and all outstanding requests.
    before = ctx.reducer.head.revision
    event = ctx.reducer.make_event(
        Mutation(kind="FINALIZE", value=ctx.reducer.census()),
        "research_manager",
        ctx.now,
        "g88-final:" + review.sha256,
        read_set=(before.state,),
    )
    after = apply_state_event(ctx.journal, ctx.reducer, event).revision
    body = json.dumps(
        {
            "status": "REVIEWED_DEVELOPMENT_STATE",
            "scientific_status": "BLOCKED_MISSING_V2_SOURCE_AUTHORITY",
            "review": review.model_dump(mode="json"),
            "risk": run.results[AgentName.RISK_MANAGER].identity.model_dump(
                mode="json"
            ),
            "trader": trader.model_dump(mode="json"),
            "before": before.model_dump(mode="json"),
            "after": after.model_dump(mode="json"),
            "production_admission": False,
        },
        sort_keys=True,
    )
    ctx.journal.append(
        "g88-finalization",
        digest(body),
        body,
        len(ctx.journal.entries("g88-finalization")),
    )
    run.finalization_status = "REVIEWED_DEVELOPMENT_STATE"
    return after


def execute_feedback(
    coordinator: ResearchCoordinator,
    request: ResearchTaskRequest,
    ctx: IncrementalContext,
    *,
    refresh: Refresh,
    max_dispatches: int = 15,
) -> FeedbackRun:
    """Run once and at most one evidence-justified, targeted Coordinator rework."""
    from src.services.llm_gateway import LLMGateway
    from src.services.llm_provider import FakeLLMProvider

    if (
        not isinstance(ctx.gateway, LLMGateway)
        or not isinstance(ctx.gateway._provider, FakeLLMProvider)
        or any(a._llm_gateway is not ctx.gateway for a in coordinator._agents.values())
    ):
        raise ValueError("G88_OFFLINE_GATEWAY_REQUIRED")
    if not ctx.enabled or not 0 <= max_dispatches <= 18:
        raise ValueError("G88_OPT_IN_OR_BUDGET")
    # The per-episode journal makes repeated invocations and renamed tasks fail closed.
    stream = "g88-feedback:" + ctx.reducer.binding.episode.sha256
    with ctx.journal.serialized():
        if ctx.journal.entries(stream):
            raise ValueError("EPISODE_FEEDBACK_ALREADY_STARTED")
        ctx.journal.append(
            stream,
            "STARTED",
            json.dumps(
                {
                    "task": request.task_id,
                    "budget": max_dispatches,
                    "plan": ctx.reducer.plan.reference.model_dump(mode="json"),
                }
            ),
            0,
        )
    out = FeedbackRun()
    active = replace(ctx, max_dispatches=min(ctx.max_dispatches, max_dispatches))
    first = coordinator.run_incremental(request, active)
    out.attempts.append(first)
    used = sum(r["status"] == "EXECUTED" for r in first.trace)
    try:
        if set(first.results) != set(ROLES):
            raise ValueError("UPSTREAM_OR_RISK_BLOCKED")
        review = first.results[AgentName.RESEARCH_MANAGER].value
        assert isinstance(review, ReviewProduct)
        if review.decision == "RETURN_FOR_RESEARCH":
            roles = review.return_to_roles
            allowed = {r for stage in ROLE_STAGES[:-2] for r in stage}
            if not roles or len(set(roles)) != len(roles) or set(roles) - allowed:
                raise ValueError("INVALID_REWORK_ROLE")
            if (
                ctx.reducer.plan.budgets.max_rounds < 2
                or ctx.reducer.plan.budgets.max_followups
                <= len(ctx.reducer.head.requests)
            ):
                raise ValueError("COLLABORATION_REWORK_BUDGET")
            next_request, next_ctx = refresh(first, review)
            if (
                next_ctx.reducer is not ctx.reducer
                or next_ctx.journal is not ctx.journal
                or next_ctx.mandate != ctx.mandate
                or next_ctx.gateway is not ctx.gateway
                or next_request.model_name != request.model_name
            ):
                raise ValueError("REWORK_AUTHORITY_CHANGED")
            if (
                next_request.task_id == request.task_id
                or next_ctx.prior != first.results
            ):
                raise ValueError("REWORK_RUN_OR_PARENT_IDENTITY")
            next_ctx.validate(next_request)
            before = {s.key: s for s in ctx.sources}
            changed = {s.key for s in next_ctx.sources if before.get(s.key) != s}
            changed.update(set(before) - {s.key for s in next_ctx.sources})
            direct = {
                r for r in ROLES if changed.intersection(next_ctx.source_roles[r])
            }
            if not set(roles) <= direct:
                raise ValueError("NO_NEW_INPUT_FOR_REQUESTED_ROLE")
            stages = [
                i
                for i, stage in enumerate(ROLE_STAGES)
                if set(roles).intersection(stage)
            ]
            closure = set(roles) | {
                r for stage in ROLE_STAGES[min(stages) + 1 :] for r in stage
            }
            if direct - closure:
                raise ValueError("UNRELATED_SOURCE_CHANGE_REQUIRES_SEPARATE_PLAN")
            if used + len(closure) > max_dispatches:
                raise ValueError("REWORK_DISPATCH_BUDGET")
            # Preserve unchanged parents; invalidate only the scoped work.
            next_ctx = replace(
                next_ctx,
                prior={r: v for r, v in first.results.items() if r not in closure},
                max_dispatches=len(closure),
            )
            next_request = next_request.model_copy(
                update={
                    "input_context": next_request.input_context.model_copy(
                        update={
                            "structured_features": {
                                **next_request.input_context.structured_features,
                                "g88_rework_request": {
                                    "review": review.review.record_id,
                                    "reasons": list(review.review.reasons),
                                    "roles": [str(r) for r in roles],
                                },
                            }
                        }
                    )
                }
            )
            ctx.journal.append(
                stream,
                "REWORK_RESERVED",
                json.dumps(
                    {
                        "review": review.sha256,
                        "roles": [str(r) for r in roles],
                        "closure": [str(r) for r in ROLES if r in closure],
                        "changed": sorted(changed),
                    }
                ),
                len(ctx.journal.entries(stream)),
            )
            second = coordinator.run_incremental(next_request, next_ctx)
            out.attempts.append(second)
            out.rework_roles = tuple(r for r in ROLES if r in closure)
            out.unrelated_reexecutions = sum(
                t["status"] == "EXECUTED" and t["role"] not in closure
                for t in second.trace
            )
            if out.unrelated_reexecutions:
                raise ValueError("UNRELATED_REEXECUTION")
            if set(second.results) != set(ROLES):
                raise ValueError("REWORK_UPSTREAM_OR_RISK_BLOCKED")
            final = second.results[AgentName.RESEARCH_MANAGER].value
            assert isinstance(final, ReviewProduct)
            if final.decision == "RETURN_FOR_RESEARCH":
                raise ValueError("REWORK_LIMIT_REACHED")
            active = next_ctx
        out.final_revision = finalize_review(out.attempts[-1], active)
        out.status = "REVIEWED_DEVELOPMENT_STATE"
    except (ValueError, KeyError) as error:
        out.status = "BLOCKED:" + str(error)
    body = json.dumps(
        {
            "status": out.status,
            "scientific_status": out.scientific_status,
            "attempt_traces": [a.trace for a in out.attempts],
            "final_revision": (
                out.final_revision.model_dump(mode="json")
                if out.final_revision
                else None
            ),
            "rework_roles": [str(r) for r in out.rework_roles],
            "unrelated_reexecutions": out.unrelated_reexecutions,
        },
        sort_keys=True,
    )
    ctx.journal.append(stream, "TERMINAL", body, len(ctx.journal.entries(stream)))
    return out


def admit_role_memory(
    run: IncrementalRun,
    ctx: IncrementalContext,
    service: MemoryService,
    *,
    role: AgentName,
    accepted: AnalystResult,
    statement_id: str,
    sources: Mapping[Reference, ArtifactRef],
) -> AdmissionReceipt:
    """Connect actual role results to W6 with independent v2 authority."""
    from src.agents.contracts import AgentExecutionResult

    retained = run.results[role]
    if not isinstance(retained.value, AgentExecutionResult):
        raise ValueError("MEMORY_ORIGINAL_AGENT_RESULT_REQUIRED")
    receipt = admit_execution_memory(
        retained.value,
        retained.read_set,
        service,
        reducer=ctx.reducer,
        journal=ctx.journal,
        at=ctx.now,
        scope=ctx.scope,
        enabled=ctx.enabled,
        role=role,
        accepted=accepted,
        statement_id=statement_id,
        sources=sources,
    )
    run.research_memory_write_status = receipt.validation_status
    return receipt


def admit_execution_memory(
    result: AgentExecutionResult,
    reads: MemoryReadSet,
    service: MemoryService,
    *,
    reducer: StateReducer,
    journal: MemoryJournalRepository,
    at: datetime,
    scope: Scope,
    enabled: bool,
    role: AgentName,
    accepted: AnalystResult,
    statement_id: str,
    sources: Mapping[Reference, ArtifactRef],
) -> AdmissionReceipt:
    """Shared G88 admission body for coordinator or a single original Analyst run."""
    from src.memory.controlled import admit_memory
    from src.memory.feedback import propose_from_execution, retain_execution
    from src.memory.vnext import MemoryAccessContext

    execution = retain_execution(
        result=result,
        reads=reads,
        accepted=accepted,
        reducer=reducer,
        journal=journal,
        at=at,
    )
    request = propose_from_execution(
        execution,
        statement_id=statement_id,
        scope=scope,
        owner=reads.owner,
        subject_owner=accepted.scope_id,
        sources=sources,
        at=at,
        journal=journal,
    )
    receipt = admit_memory(
        service,
        request,
        access=MemoryAccessContext(
            owner=reads.owner,
            role=role,
            scopes=(scope,),
            enabled=enabled,
        ),
        reducer=reducer,
        journal=journal,
        scope_owners={scope: accepted.scope_id},
        source_identities=sources,
    )
    return receipt
