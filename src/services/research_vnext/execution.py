"""Opt-in G87 orchestration on the existing Coordinator, Memory and Agent APIs.

Development only. No provider construction, acquisition, new Claim authority or
production publication. The composition root owns exact source dependencies.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, cast

from src.agents.base import AgentGateway
from src.agents.contracts import AgentExecutionResult, ResearchTaskRequest
from src.agents.research_vnext import (
    ManagerFinalReviewRole,
    RoleWork,
    TraderResearchRole,
)
from src.memory.contracts import ResearchContextBundle, ResearchContextSection
from src.memory.controlled import retrieve_memory
from src.memory.incremental import (
    ResearchDependency,
    ReuseInputs,
    SourceSnapshot,
    qualify_reuse,
)
from src.memory.incremental_store import process_sources, retain_reuse
from src.memory.state_dependencies import dependencies_from_state
from src.memory.vnext import ImpactRule, MemoryAccessContext, plan_impact
from src.memory.vnext_contracts import (
    ROLE_STAGES,
    ArtifactRef,
    MemoryReadSet,
    ResearchMandate,
    Role,
    Scope,
)
from src.models.enums import AgentName, AgentStatus
from src.models.types import DomainModel, JsonObject
from src.repositories.memory_journal import MemoryJournalRepository
from src.schemas.agents import (
    AgentRequest,
    BearManagerResponse,
    BullManagerResponse,
    ClaimEvidenceBinding,
)
from src.schemas.research_episode import ResearchEpisode
from src.schemas.research_state import (
    ResearchStateBuildInput,
    ResearchStateClaimInput,
    ResearchStateSnapshot,
)
from src.schemas.research_v2_shared import Reference, Revision, digest, reference
from src.services.research_state import ResearchStateBuilder
from src.services.research_v2_collaboration.state import StateReducer
from src.services.research_vnext.contracts import (
    ProductReferences,
    QuantResearchContext,
    RetainedReader,
    ReviewProduct,
    TraderProduct,
    resolve,
    trader_reference,
)
from src.services.research_vnext.inputs import debate_input, risk_input
from src.services.research_vnext.memory import agent_reads, legacy_context_with_reads
from src.services.research_vnext.radar import require_mandate
from src.services.research_vnext.report import render_review
from src.services.research_vnext.revision import retain_development_revision

if TYPE_CHECKING:
    from src.agents.coordinator import ResearchCoordinator

ROLES = tuple(r for stage in ROLE_STAGES for r in stage)
# Frozen before any observed outcome. Any changed source bytes invalidates only
# readers and their actual downstream results; no numeric materiality tuning.
POLICY_BYTES = b"g87-v1:exact-source-change;dependent-readers;no-price-all-role-reset"


@dataclass(frozen=True)
class RetainedRole:
    """Exact original result and the complete composition-owned input closure."""

    role: Role
    value: AgentExecutionResult | TraderProduct | ReviewProduct
    identity: ArtifactRef
    inputs: ReuseInputs
    payload: JsonObject
    read_set: MemoryReadSet
    parents: tuple[ArtifactRef, ...]


@dataclass
class IncrementalRun:
    """Actual dispatch census; a failed or partial run remains explicit."""

    trace: list[JsonObject] = field(default_factory=list)
    results: dict[Role, RetainedRole] = field(default_factory=dict)
    state: ResearchStateSnapshot | None = None
    report: str | None = None
    revisions: list[Revision] = field(default_factory=list)
    episode: ResearchEpisode | None = None
    state_inputs: ResearchStateBuildInput | None = None
    dependencies: tuple[ResearchDependency, ...] = ()
    impact_plans: list[JsonObject] = field(default_factory=list)
    changes_sha256: str = ""
    impact_sha256: str = ""
    handoff_status: str = "BLOCKED_NO_QUALIFIED_HANDOFF_INPUTS"
    production_admission: bool = False
    research_memory_write_status: str = "BLOCKED_MISSING_V2_SOURCE_AUTHORITY"
    finalization_status: str = "PARTIAL_DEVELOPMENT_PROVENANCE_ONLY"


@dataclass
class IncrementalContext:
    """Trusted local composition inputs, never model-supplied permission flags.

    Retention/claim/revision resolution are existing application authorities. A
    development run does not convert an arbitrary result hash to a verified fact.
    """

    scope: Scope
    mandate: ResearchMandate
    sources: tuple[SourceSnapshot, ...]
    source_roles: Mapping[Role, tuple[str, ...]]
    data_sources: Mapping[str, str]
    dependencies: tuple[ResearchDependency, ...]
    journal: MemoryJournalRepository
    reader: RetainedReader
    retain: Callable[[str, DomainModel, str, datetime], ArtifactRef]
    validate_revision: Callable[[Revision], None]
    validate_claim: Callable[[Reference], None]
    revision: Revision
    memory: ResearchContextBundle
    memory_refs: Mapping[str, ArtifactRef]
    gateway: AgentGateway
    quant: QuantResearchContext
    now: datetime
    policy: ArtifactRef
    detector: ArtifactRef
    reducer: StateReducer
    prior: Mapping[Role, RetainedRole] = field(default_factory=dict)
    prior_state: ResearchStateSnapshot | None = None
    prior_dependencies: tuple[ResearchDependency, ...] = ()
    enabled: bool = False
    max_dispatches: int = 9
    applicable_roles: frozenset[Role] = frozenset(ROLES)
    validator_version: str = "original-agent-v1"
    strategy_version: str = "g87-exact-dependency-v1"
    valid_for: timedelta = timedelta(days=8)

    def validate(self, request: ResearchTaskRequest) -> None:
        """Bind input population, declared policy, cutoff and original scope."""
        if not self.enabled:
            raise ValueError("G87_OPT_IN_REQUIRED")
        if not 0 <= self.max_dispatches <= 9:
            raise ValueError("G87_DISPATCH_BUDGET")
        if request.data_bundle is None or request.context_bundle != self.memory:
            raise ValueError("CANONICAL_DATA_MEMORY_REQUIRED")
        if self.scope.scope_id != "ASSET:" + str(request.data_bundle.asset_id):
            raise ValueError("SOURCE_SUBJECT_MISMATCH")
        if (
            self.quant.asset_id != request.data_bundle.asset_id
            or self.quant.research_as_of != request.data_bundle.as_of
        ):
            raise ValueError("QUANT_SCOPE_CUTOFF")
        if resolve(self.policy, self.reader) != POLICY_BYTES:
            raise ValueError("UNREGISTERED_MATERIALITY_POLICY")
        if set(self.source_roles) != set(ROLES):
            raise ValueError("INCOMPLETE_ROLE_DEPENDENCY_POPULATION")
        keys = {s.key for s in self.sources}
        if any(not ids or set(ids) - keys for ids in self.source_roles.values()):
            raise ValueError("BLOCKED_MISSING_EVIDENCE:SOURCE_DEPENDENCY")
        if self.applicable_roles - set(ROLES):
            raise ValueError("UNKNOWN_APPLICABLE_ROLE")
        for role in self.applicable_roles:
            require_mandate(
                self.mandate,
                role=role,
                scope=self.scope,
                at=self.now,
                reader=self.reader,
            )
        from src.agents.input_contracts import AgentInputProjector
        from src.schemas.research_data import DataCapability, ResearchDataSection

        by_key = {s.key: s for s in self.sources}
        if set(self.data_sources) != {c.value for c in DataCapability}:
            raise ValueError("INCOMPLETE_CANONICAL_DATA_POPULATION")
        for cap in DataCapability:
            snapshot = by_key[self.data_sources[cap.value]]
            section = ResearchDataSection.model_validate_json(
                resolve(snapshot.source, self.reader)
            )
            if section != getattr(request.data_bundle, cap.value):
                raise ValueError("REQUEST_SOURCE_BYTES_MISMATCH")
            expected_evidence = tuple(
                reference("EVIDENCE", i.evidence_id, "ResearchEvidenceItem/1.0", i)
                for i in section.items
            ) or (
                reference("RECEIPT", cap.value, "g87_missing_section_v1", section),
            )
            if snapshot.evidence != expected_evidence:
                raise ValueError("SOURCE_EVIDENCE_POPULATION_MISMATCH")
        for role in ROLE_STAGES[0]:
            assert isinstance(role, AgentName)
            contract = AgentInputProjector.analyst(
                request.data_bundle, self.memory, role, request.sector_context_bundle
            )
            required = {
                self.data_sources[s.capability.value] for s in contract.data.sections
            }
            if not required <= set(self.source_roles[role]):
                raise ValueError("INCOMPLETE_ACTUAL_ROLE_READ_DEPENDENCIES")
        bundle_sources = [
            s
            for s in self.sources
            if s.source.artifact_id == request.data_bundle.bundle_id
        ]
        if len(bundle_sources) != 1 or json.loads(
            resolve(bundle_sources[0].source, self.reader)
        ) != request.data_bundle.model_dump(mode="json"):
            raise ValueError("CANONICAL_BUNDLE_BYTES_REQUIRED")
        self.validate_revision(self.revision)
        if self.revision != self.reducer.head.revision:
            raise ValueError("STALE_COMPOSITION_REVISION")


def _parents(
    role: Role, results: Mapping[Role, RetainedRole]
) -> tuple[RetainedRole, ...]:
    stage = next(i for i, s in enumerate(ROLE_STAGES) if role in s)
    needed = tuple(r for s in ROLE_STAGES[:stage] for r in s)
    if set(needed) - set(results):
        raise ValueError("BLOCKED_MISSING_EVIDENCE:UPSTREAM_ROLE")
    return tuple(results[r] for r in needed)


def _claims(result: AgentExecutionResult) -> tuple[ClaimEvidenceBinding, ...]:
    """Recover only original accepted output bindings, never narrative strings."""
    from src.agents.coordinator import _validated_claims

    claims = _validated_claims(result)
    if {c.claim_id for c in claims} != {
        e.claim_id
        for e in result.evidence
        if e.claim_path
        not in {
            "analysis.quality_score",
            "analysis.growth_score",
            "analysis.valuation_score",
        }
    }:
        raise ValueError("ORIGINAL_CLAIM_CENSUS_MISMATCH")
    if any(c.claim_path.startswith("confirmed_risks[") for c in claims):
        raise ValueError("OCCURRENCE_AUTHORITY_NOT_REGISTERED_FOR_G87")
    return claims


def _dependency_closure(ctx: IncrementalContext) -> tuple[ResearchDependency, ...]:
    """Preserve original Claim dependencies while adding sourced relation edges."""
    index = {d.artifact: d for d in ctx.prior_dependencies}
    for edge in ctx.dependencies:
        old = index.get(edge.artifact)
        if old is None:
            if edge.artifact.namespace == "CLAIM":
                raise ValueError("RELATION_TARGET_NOT_ACCEPTED_CLAIM")
            index[edge.artifact] = edge
            continue
        if old.scope != edge.scope or not edge.relationship_evidence:
            raise ValueError("DEPENDENCY_SCOPE_OR_RELATION_AUTHORITY")
        index[edge.artifact] = old.model_copy(
            update={
                "source_keys": tuple(
                    dict.fromkeys((*old.source_keys, *edge.source_keys))
                ),
                "upstream": tuple(dict.fromkeys((*old.upstream, *edge.upstream))),
                "relationship_evidence": tuple(
                    dict.fromkeys(
                        (*old.relationship_evidence, *edge.relationship_evidence)
                    )
                ),
                "valid_from": max(old.valid_from, edge.valid_from),
                "valid_until": min(old.valid_until, edge.valid_until),
            }
        )
    return tuple(index.values())


def execute_incremental(
    coordinator: ResearchCoordinator,
    request: ResearchTaskRequest,
    ctx: IncrementalContext,
) -> IncrementalRun:
    """Run selective stages using the original Coordinator invocation boundary."""
    from src.agents.coordinator import (
        ANALYST_ORDER,
        _context_for_contract,
        _contract_json,
    )

    ctx.validate(request)
    assert request.data_bundle is not None
    cutoff = request.data_bundle.as_of
    changes, impact = process_sources(
        ctx.journal,
        ctx.scope.scope_id,
        ctx.sources,
        as_of=cutoff,
        created_at=ctx.now,
        resolve=ctx.reader,
        detector=ctx.detector,
        policy=ctx.policy,
        materiality=lambda before, after: True,
        dependencies=_dependency_closure(ctx),
    )
    run = IncrementalRun(changes_sha256=changes.sha256, impact_sha256=impact.sha256)
    # Scope-local policies are derived from exact reader dependencies, never
    # from model assertions or outcome-dependent threshold selection.
    for change in changes.changes:
        delta = change.delta
        if delta is None:
            continue
        roots = tuple(r for r in ROLES if change.key in ctx.source_roles[r])
        if delta.scope != ctx.scope:
            roots = tuple(
                r
                for r in ROLES
                if r in ctx.prior
                and set(ctx.prior[r].inputs.claims).intersection(impact.invalidated)
            )
            if not roots:
                continue
            if not impact.relation_sources:
                raise ValueError("BLOCKED_MISSING_EVIDENCE:CROSS_SCOPE")
            delta = delta.model_copy(
                update={
                    "scope": ctx.scope,
                    "record_id": "sourced-impact:" + delta.sha256,
                    "source_refs": tuple(
                        dict.fromkeys((*delta.source_refs, *impact.relation_sources))
                    ),
                }
            )
        rule = ImpactRule(
            owner="G87_EXACT_READER_POLICY",
            scope=ctx.scope,
            change_kind=delta.change_kind,
            direct_roles=roots,
            rationale="Exact source readers, then G84 downstream stages",
        )
        plan = plan_impact(delta, ctx.mandate, policy=rule, enabled=True)
        run.impact_plans.append(cast(JsonObject, plan.model_dump(mode="json")))
        ctx.journal.append(
            "g87-impact-plans",
            plan.sha256,
            plan.model_dump_json(),
            len(ctx.journal.entries("g87-impact-plans")),
        )
    dispatches = 0
    by_key = {s.key: s for s in changes.checked_population}
    bundle_ref = ctx.retain(
        "memory:" + request.task_id, ctx.memory, "coordinator", ctx.now
    )
    quant_ref = ctx.retain("quant:" + request.task_id, ctx.quant, "quant", ctx.now)
    for role in ROLES:
        if role not in ctx.applicable_roles:
            run.trace.append(
                dict(
                    role=str(role),
                    status="SKIPPED_NOT_APPLICABLE",
                    reason="Explicit trusted task applicability",
                )
            )
            continue
        try:
            parents = _parents(role, run.results)
            access = MemoryAccessContext(
                owner=str(role), role=role, scopes=(ctx.scope,), enabled=True
            )
            # Invoke W6 scope/PIT/invalidation retrieval on the same durable DB.
            controlled = retrieve_memory(
                journal=ctx.journal,
                access=access,
                scope=ctx.scope,
                as_of=cutoff,
                created_at=ctx.now,
                run_id=request.task_id + ":" + str(role),
                revision=ctx.revision,
            )
            # This bridge cannot silently omit checked W6 admissions. Root must
            # project every accepted item into the supplied original bundle.
            supplied = {
                i.memory_id
                for s in ResearchContextSection
                for i in ctx.memory.items_for_section(s)
            }
            if {r.artifact_id for r in controlled.read_set.memory_refs} - supplied:
                raise ValueError("MEMORY_CONTEXT_OMITS_CONTROLLED_RETRIEVAL")
            reads = agent_reads(
                ctx.memory,
                bundle_ref=bundle_ref,
                memory_refs=ctx.memory_refs,
                access=access,
                scope=ctx.scope,
                agent_run_id=request.task_id + ":" + str(role),
                created_at=ctx.now,
            )
            ctx.journal.append(
                "readsets",
                reads.sha256,
                reads.model_dump_json(),
                len(ctx.journal.entries("readsets")),
            )
            source_set = tuple(by_key[k] for k in ctx.source_roles[role])
            if any(
                s.status != "ACTIVE" or (s.expires_at and s.expires_at <= cutoff)
                for s in source_set
            ):
                raise ValueError("BLOCKED_MISSING_EVIDENCE:INACTIVE_OR_EXPIRED_SOURCE")
            old = ctx.prior.get(role)
            parent_ids = tuple(p.identity for p in parents)
            version = (
                coordinator._agents[role]._prompt_loader.load(role).version
                if isinstance(role, AgentName) and role != AgentName.RESEARCH_MANAGER
                else "g86_nonexecuting_roles_v1"
            )
            task = digest(
                {
                    "role": str(role),
                    "subject": ctx.scope.scope_id,
                    "parents": [p.model_dump(mode="json") for p in parent_ids],
                    "mandate": ctx.mandate.sha256,
                }
            )
            current = ReuseInputs(
                scope=ctx.scope,
                task=task,
                revision=old.inputs.revision if old else ctx.revision,
                sources=source_set,
                claims=old.inputs.claims if old else (),
                memories=reads.memory_refs,
                agent_version="g87-original-agent-composition-v1",
                prompt_version=version + ":" + request.model_name,
                validator_version=ctx.validator_version,
                strategy_version=ctx.strategy_version,
                source_policy_version=ctx.policy.sha256_digest,
                scientific_status="VALIDATED",
                valid_from=old.inputs.valid_from if old else cutoff,
                valid_until=old.inputs.valid_until if old else cutoff + ctx.valid_for,
            )
            proof = None
            if old:
                resolve(old.identity, ctx.reader)

                def validate_retained_claim(ref: Reference) -> None:
                    # Original accepted Claim bindings are revalidated by their
                    # actual parent Agent; this does not grant v2 PIT authority.
                    found = False
                    for retained in ctx.prior.values():
                        if not isinstance(retained.value, AgentExecutionResult):
                            continue
                        role_agent = coordinator._agents[retained.value.agent_name]
                        assert retained.value.output is not None
                        _, bindings = role_agent._validate_inference_output(
                            retained.payload, retained.value.output
                        )
                        if (
                            bindings != retained.value.evidence
                            or retained.value.rejected_claims
                        ):
                            raise ValueError("REUSE_CLAIM_REVALIDATION_FAILED")
                        if ref in tuple(
                            reference(
                                "CLAIM",
                                c.claim_id or "",
                                "claim_evidence_binding_v1",
                                c,
                            )
                            for c in _claims(retained.value)
                        ):
                            found = True
                    if not found:
                        raise ValueError("UNRESOLVED_RETAINED_CLAIM")

                proof = qualify_reuse(
                    old.inputs,
                    current,
                    changes,
                    impact,
                    validate_retained_claim,
                    ctx.validate_revision,
                )
                retain_reuse(ctx.journal, proof)
            if proof and proof.disposition == "REUSED":
                assert old is not None
                if isinstance(old.value, AgentExecutionResult):
                    assert isinstance(role, AgentName) and old.value.output is not None
                    _, verified = coordinator._agents[role]._validate_inference_output(
                        old.payload, old.value.output
                    )
                    if verified != old.value.evidence or old.value.rejected_claims:
                        raise ValueError("REUSE_ORIGINAL_CLAIM_AUTHORITY")
                    _claims(old.value)
                run.results[role] = old
                run.trace.append(
                    cast(
                        JsonObject,
                        dict(
                            role=str(role),
                            status="REUSED",
                            result=old.identity.model_dump(mode="json"),
                            reuse=proof.model_dump(mode="json"),
                        ),
                    )
                )
                continue
            if dispatches >= ctx.max_dispatches:
                raise ValueError("BLOCKED_MISSING_EVIDENCE:DISPATCH_BUDGET")
            require_mandate(
                ctx.mandate, role=role, scope=ctx.scope, at=ctx.now, reader=ctx.reader
            )
            context = legacy_context_with_reads(
                request.input_context, ctx.memory, reads, access=access
            )
            context.structured_features = {
                **context.structured_features,
                "g87_source_context": [
                    {
                        "source": s.source.model_dump(mode="json"),
                        "payload": json.loads(resolve(s.source, ctx.reader)),
                    }
                    for s in source_set
                ],
            }
            payload: JsonObject = {}
            if role in ANALYST_ORDER:
                assert isinstance(role, AgentName)
                contract = coordinator._analyst_contract(request, role)
                payload = cast(
                    JsonObject,
                    AgentRequest(
                        run_id=reads.agent_run_id,
                        agent_name=role,
                        model_name=request.model_name,
                        input_context=_context_for_contract(context, contract),
                        research_contract=_contract_json(contract),
                    ).model_dump(mode="json"),
                )
            elif role in (AgentName.BULL_MANAGER, AgentName.BEAR_MANAGER):
                assert isinstance(role, AgentName)
                payload = cast(
                    JsonObject,
                    debate_input(
                        role,
                        context,
                        [
                            cast(AgentExecutionResult, run.results[r].value)
                            for r in ANALYST_ORDER
                        ],
                    ).model_dump(mode="json"),
                )
            elif role == AgentName.RISK_MANAGER:
                payload = cast(
                    JsonObject,
                    risk_input(
                        context,
                        [
                            cast(AgentExecutionResult, run.results[r].value)
                            for r in ANALYST_ORDER
                        ],
                        BullManagerResponse.model_validate(
                            cast(
                                AgentExecutionResult,
                                run.results[AgentName.BULL_MANAGER].value,
                            ).output
                        ),
                        BearManagerResponse.model_validate(
                            cast(
                                AgentExecutionResult,
                                run.results[AgentName.BEAR_MANAGER].value,
                            ).output
                        ),
                    ).model_dump(mode="json"),
                )
            value: AgentExecutionResult | TraderProduct | ReviewProduct
            if role not in ("trader", AgentName.RESEARCH_MANAGER):
                assert isinstance(role, AgentName)
                dispatches += 1
                value = coordinator._invoke(request, role, payload)
                ctx.retain(value.run_id, value, str(role), ctx.now)  # retain errors too
                if value.status != AgentStatus.OK or value.rejected_claims:
                    raise ValueError("ORIGINAL_AGENT_OR_SIBLING_GATE:" + value.run_id)
                _claims(value)
            else:
                results = [
                    p for p in parents if isinstance(p.value, AgentExecutionResult)
                ]
                rows = tuple(
                    ResearchStateClaimInput(
                        agent_role=p.value.agent_name,
                        agent_run_id=p.value.run_id,
                        claim=c,
                    )
                    for p in results
                    if isinstance(p.value, AgentExecutionResult)
                    for c in _claims(p.value)
                )
                run.state_inputs = ResearchStateBuildInput(
                    research_data_bundle=request.data_bundle,
                    accepted_claims=rows,
                    source_run_id=request.task_id,
                )
                run.state = ResearchStateBuilder().build(run.state_inputs)
                run.dependencies = dependencies_from_state(
                    run.state_inputs, ctx.sources, valid_until=cutoff + ctx.valid_for
                )
                work = RoleWork(
                    owner=str(role),
                    record_id=reads.agent_run_id,
                    revision=1,
                    created_at=ctx.now,
                    research_as_of=cutoff,
                    scope=ctx.scope,
                    source_refs=tuple(s.source for s in source_set),
                    mandate=ctx.mandate,
                    memory_reads=reads,
                    quant_context=quant_ref,
                    risk_review=run.results[AgentName.RISK_MANAGER].identity,
                    products=ProductReferences(
                        hypotheses=tuple(p.identity for p in results)
                    ),
                )

                def check(ref: ArtifactRef, role: Role | None, scope: Scope) -> None:
                    matches = [p for p in parents if p.identity == ref]
                    if (
                        scope != ctx.scope
                        or len(matches) != 1
                        or (role is not None and matches[0].role != role)
                    ):
                        raise ValueError("UNACCEPTED_ROLE_LINEAGE")
                    resolve(ref, ctx.reader)

                def check_quant(q: QuantResearchContext) -> None:
                    if q != ctx.quant:
                        raise ValueError("QUANT_AUTHORITY_CHANGED")

                dispatches += 1
                if role == "trader":
                    value = TraderResearchRole().run(
                        work,
                        model=request.model_name,
                        gateway=ctx.gateway,
                        access=access,
                        reader=ctx.reader,
                        validate_role=check,
                        validate_quant=check_quant,
                    )
                    ctx.retain(
                        value.proposal.record_id, value.proposal, "trader", ctx.now
                    )
                    # Exact G86 content reference, not a new authority registry.
                    ctx.retain(
                        trader_reference(value).artifact_id, value, "trader", ctx.now
                    )
                else:
                    run.revisions.append(
                        retain_development_revision(
                            ctx.reducer,
                            ctx.journal,
                            state=run.state,
                            task_id=request.task_id,
                            stage="working",
                            execution={
                                "trace": run.trace,
                                "read_set": reads.model_dump(mode="json"),
                            },
                            at=ctx.now,
                        )
                    )
                    state_ref = ctx.retain(
                        run.state.research_state_id, run.state, "coordinator", ctx.now
                    )
                    value = ManagerFinalReviewRole().run(
                        work,
                        cast(TraderProduct, run.results["trader"].value),
                        working_state=state_ref,
                        model=request.model_name,
                        gateway=ctx.gateway,
                        access=access,
                        reader=ctx.reader,
                        validate_role=check,
                        validate_quant=check_quant,
                    )
                    run.revisions.append(
                        retain_development_revision(
                            ctx.reducer,
                            ctx.journal,
                            state=run.state,
                            task_id=request.task_id,
                            stage="reviewed",
                            execution={
                                "trace": run.trace,
                                "review": value.model_dump(mode="json"),
                            },
                            at=ctx.now,
                        )
                    )
                    if value.decision == "RETURN_FOR_RESEARCH":
                        run.finalization_status = (
                            "BLOCKED_PENDING_BOUNDED_COORDINATOR_REWORK"
                        )
                    run.report = render_review(
                        cast(TraderProduct, run.results["trader"].value), value
                    )
            name = (
                value.run_id
                if isinstance(value, AgentExecutionResult)
                else (
                    trader_reference(value).artifact_id
                    if isinstance(value, TraderProduct)
                    else value.review.record_id
                )
            )
            identity = ctx.retain(name, value, str(role), ctx.now)
            if isinstance(value, AgentExecutionResult):
                current = current.model_copy(
                    update={
                        "claims": tuple(
                            reference(
                                "CLAIM",
                                c.claim_id or "",
                                "claim_evidence_binding_v1",
                                c,
                            )
                            for c in _claims(value)
                        )
                    }
                )
            run.results[role] = RetainedRole(
                role, value, identity, current, payload, reads, parent_ids
            )
            run.trace.append(
                cast(
                    JsonObject,
                    dict(
                        role=str(role),
                        status="EXECUTED",
                        result=identity.model_dump(mode="json"),
                        read_set=reads.sha256,
                    ),
                )
            )
        except (ValueError, KeyError) as error:
            run.trace.append(
                dict(
                    role=str(role), status="BLOCKED_MISSING_EVIDENCE", reason=str(error)
                )
            )
    if run.state is None and len(run.results) == 9:
        run.state = ctx.prior_state
        run.dependencies = ctx.prior_dependencies
        if "trader" in run.results and AgentName.RESEARCH_MANAGER in run.results:
            run.report = render_review(
                cast(TraderProduct, run.results["trader"].value),
                cast(ReviewProduct, run.results[AgentName.RESEARCH_MANAGER].value),
            )
    if run.state is not None:
        from src.schemas.research_episode import (
            AgentExecutionTrace,
            ResearchEpisodeBuildInput,
            ResearchEpisodeTraceQuality,
        )
        from src.schemas.research_quant_handoff import ResearchQuantHandoffBuildInput
        from src.services.research_episode import ResearchEpisodeBuilder
        from src.services.research_quant_handoff import ResearchQuantHandoffBuilder

        traces = []
        for retained in run.results.values():
            if not isinstance(retained.value, AgentExecutionResult):
                continue
            result = retained.value
            ids = tuple(c.claim_id for c in _claims(result) if c.claim_id is not None)
            metadata = result.llm_run_metadata
            traces.append(
                AgentExecutionTrace(
                    agent_role=result.agent_name,
                    agent_run_id=result.run_id,
                    status=result.status,
                    output_claim_ids=ids,
                    accepted_claim_ids=ids,
                    accepted_claim_count=len(ids),
                    rejected_claim_count=0,
                    input_context_ids=(retained.read_set.record_id,),
                    provider=metadata.provider if metadata else "UNKNOWN",
                    model=request.model_name,
                    prompt_version=retained.inputs.prompt_version,
                    trace_quality=(
                        ResearchEpisodeTraceQuality.COMPLETE
                        if metadata
                        else ResearchEpisodeTraceQuality.PARTIAL
                    ),
                    missing_metadata=(
                        () if metadata else ("original_provider_metadata",)
                    ),
                )
            )
        run.episode = ResearchEpisodeBuilder().build(
            ResearchEpisodeBuildInput(
                research_state=run.state,
                agent_traces=tuple(traces),
                created_at=ctx.now,
                source_artifact_ids=tuple(s.source.artifact_id for s in ctx.sources),
            )
        )
        ctx.retain(run.episode.episode_id, run.episode, "coordinator", ctx.now)
        try:
            ResearchQuantHandoffBuilder().build(
                ResearchQuantHandoffBuildInput(
                    research_state=run.state,
                    research_episode=run.episode,
                    created_at=ctx.now,
                )
            )
        except ValueError as error:
            run.handoff_status = "BLOCKED:" + str(error)
        else:
            raise ValueError("UNEXPECTED_HANDOFF_WITHOUT_QUALIFIED_OBSERVATIONS")
    body = json.dumps(
        {
            "task_id": request.task_id,
            "trace": run.trace,
            "changes": run.changes_sha256,
            "impact": run.impact_sha256,
            "impact_plans": run.impact_plans,
            "dependencies": [d.model_dump(mode="json") for d in run.dependencies],
            "state": run.state.model_dump(mode="json") if run.state else None,
            "report": run.report,
            "episode": run.episode.model_dump(mode="json") if run.episode else None,
            "handoff_status": run.handoff_status,
            "revisions": [r.model_dump(mode="json") for r in run.revisions],
            "production_admission": False,
            "research_memory_write_status": run.research_memory_write_status,
            "finalization_status": run.finalization_status,
        },
        sort_keys=True,
    )
    ctx.journal.append(
        "g87-runs",
        hashlib.sha256(body.encode()).hexdigest(),
        body,
        len(ctx.journal.entries("g87-runs")),
    )
    return run
