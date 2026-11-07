"""Append-only optimistic State reducer, independent of mutable Agent prose."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import model_validator

from src.schemas.research_v2_collaboration import (
    AnalystResult,
    CollaborationMessage,
    Coverage,
    RequestStatus,
    ResearchPlan,
    SynthesisState,
)
from src.schemas.research_v2_shared import (
    Clock,
    EventProvenance,
    Frozen,
    Reference,
    Revision,
    RunBinding,
    canonical,
    digest,
    reference,
)

from .uncertainty import scenario_uncertainties
from .validation import ReferenceValidator


class RequestTransition(Frozen):
    """A lifecycle transition, never an unvalidated resolution shortcut."""

    request: Reference
    status: RequestStatus
    reason: str


class Mutation(Frozen):
    """Closed union of State mutation payloads; no arbitrary executable payload."""

    kind: Literal["ANALYST", "MESSAGE", "TRANSITION", "SYNTHESIS", "FINALIZE"]
    value: (
        AnalystResult
        | CollaborationMessage
        | RequestTransition
        | SynthesisState
        | tuple[Coverage, ...]
    )

    @model_validator(mode="after")
    def kind_matches(self) -> Self:
        """Reject an otherwise typed object in the wrong mutation channel."""
        classes = {
            "ANALYST": AnalystResult,
            "MESSAGE": CollaborationMessage,
            "TRANSITION": RequestTransition,
            "SYNTHESIS": SynthesisState,
            "FINALIZE": tuple,
        }
        if not isinstance(self.value, classes[self.kind]):
            raise ValueError("MUTATION_KIND")
        return self


class StateEvent(Frozen):
    """Ordered immutable public event with explicit producer role and payload."""

    provenance: EventProvenance
    writer_role: str
    payload: Mutation


class RequestRecord(Frozen):
    """Reducer-derived latest view; its history remains in immutable events."""

    request: CollaborationMessage
    status: RequestStatus
    reason: str
    response: CollaborationMessage | None


class StateSnapshot(Frozen):
    """Full hashed State content, not just a revision integer."""

    binding: RunBinding
    parent: Reference | None
    sequence: int
    event_log_sha256: str
    analyst_results: tuple[AnalystResult, ...]
    messages: tuple[CollaborationMessage, ...]
    requests: tuple[RequestRecord, ...]
    coverage: tuple[Coverage, ...]
    synthesis: SynthesisState | None
    invalidated: tuple[Reference, ...]
    completed: bool

    @property
    def revision(self) -> Revision:
        """Bind full content, parent and ordered event-log digest."""
        return Revision(
            state=reference(
                "STATE",
                "research-state-" + str(self.sequence),
                "research_state_v2",
                self,
            ),
            sequence=self.sequence,
            parent=self.parent,
            event_log_sha256=self.event_log_sha256,
        )


class StateReducer:
    """Compare-and-swap writes with immutable old snapshots and exact replay."""

    def __init__(self, plan: ResearchPlan, validator: ReferenceValidator) -> None:
        """Register genesis against an exact plan and canonical resolver."""
        plan = ResearchPlan.model_validate_json(canonical(plan))
        self.plan = plan
        self.validator = validator
        self.binding = validator.binding
        if (
            self.binding.plan != plan.reference
            or self.binding.episode != plan.episode
            or self.binding.run_id != plan.run_id
            or self.binding.research_as_of != plan.research_as_of
        ):
            raise ValueError("PLAN_BINDING")
        for ref in (
            plan.episode,
            plan.model,
            plan.prompt,
            plan.producer_build,
            *plan.source_permissions,
            *plan.input_snapshots,
        ):
            validator.artifact(ref)
        validator.context(plan)
        self._events: list[StateEvent] = []
        self._snapshots = [
            StateSnapshot(
                binding=self.binding,
                parent=None,
                sequence=0,
                event_log_sha256=digest([]),
                analyst_results=(),
                messages=(),
                requests=(),
                coverage=(),
                synthesis=None,
                invalidated=(),
                completed=False,
            )
        ]
        self._keys: dict[str, tuple[str, StateSnapshot]] = {}
        self.validator.bind(plan.reference, plan)
        self.validator.bind(plan.budgets.reference, plan.budgets)
        self.validator.bind(self.head.revision.state, self.head)

    @property
    def head(self) -> StateSnapshot:
        """Return immutable current content; callers cannot write fields directly."""
        return self._snapshots[-1]

    @property
    def events(self) -> tuple[StateEvent, ...]:
        """Expose the ordered immutable log without a mutable collection."""
        return tuple(self._events)

    def snapshot(self, ref: Reference) -> StateSnapshot:
        """Resolve only an exact locally retained revision identity."""
        for state in self._snapshots:
            if state.revision.state == ref:
                return state
        raise ValueError("UNKNOWN_STATE_REVISION")

    def validate_dependency(self, message: CollaborationMessage) -> None:
        """Reject active dependency cycles before accepting or replaying a request."""
        edges: dict[str, set[str]] = {}
        active = [
            r.request
            for r in self.head.requests
            if r.status in ("OPEN", "ACKNOWLEDGED", "IN_PROGRESS")
        ]
        for request in [*active, message]:
            if request.kind == "DEPENDENCY_REQUEST":
                edges.setdefault(request.sender, set()).add(request.recipient)
        visiting: set[str] = set()
        done: set[str] = set()

        def visit(role: str) -> None:
            if role in visiting:
                raise ValueError("CYCLIC_DEPENDENCY")
            if role in done:
                return
            visiting.add(role)
            for next_role in sorted(edges.get(role, set())):
                visit(next_role)
            visiting.remove(role)
            done.add(role)

        for role in sorted(edges):
            visit(role)

    def make_event(
        self,
        payload: Mutation,
        writer: str,
        created_at: Clock,
        key: str,
        read_set: tuple[Reference, ...] = (),
    ) -> StateEvent:
        """Prepare a CAS event; allocation does not apply a State mutation."""
        refs = list(read_set)
        refs.append(self.head.revision.state)
        value = payload.value
        causal: tuple[Reference, ...] = ()
        if isinstance(value, AnalystResult):
            refs.extend(
                (
                    *value.claims,
                    *value.evidence_refs,
                    *value.dependencies,
                    value.model,
                    value.prompt,
                    value.producer_build,
                )
            )
        elif isinstance(value, CollaborationMessage):
            refs.extend(
                (*value.subject_refs, *value.resolution_evidence, value.budget_ref)
            )
            causal = value.causal_requests
            if value.validation_receipt is not None:
                refs.append(value.validation_receipt)
        elif isinstance(value, RequestTransition):
            refs.append(value.request)
        elif isinstance(value, SynthesisState):
            refs.extend(value.dependencies)
        p = EventProvenance(
            binding=self.binding,
            producer=self.plan.producer_build,
            read_revision=self.head.revision,
            read_set=tuple(dict.fromkeys(refs)),
            event=reference("EVENT", key, "research_state_event_v2", payload),
            payload_sha256=digest(payload),
            occurred_at=created_at,
            idempotency_key=key,
            causal_refs=causal,
        )
        return StateEvent(provenance=p, writer_role=writer, payload=payload)

    def census(self) -> tuple[Coverage, ...]:
        """Retain every requested tuple, including missing Analysts and budget gaps."""
        returned = {
            (c.scope_id, c.role, c.capability): c
            for r in self.head.analyst_results
            for c in r.coverage
        }
        result = []
        for slot in self.plan.slots:
            c = returned.get(slot.key)
            if c is None:
                c = Coverage(
                    scope_id=slot.scope_id,
                    role=slot.role,
                    capability=slot.capability,
                    status="NOT_RESEARCHED" if slot.applicable else "NOT_APPLICABLE",
                    reason="MISSING_ANALYST" if slot.applicable else slot.reason,
                    required=slot.required,
                    missing_items=(slot.capability,) if slot.applicable else (),
                    applicability_rule=slot.applicability_rule,
                    evidence_refs=(),
                )
            result.append(c)
        return tuple(result)

    def apply(self, event: StateEvent) -> StateSnapshot:
        """Validate all references before one atomic in-memory append."""
        event = StateEvent.model_validate_json(canonical(event))
        p = event.provenance
        fingerprint = digest(event)
        if p.idempotency_key in self._keys:
            oldhash, state = self._keys[p.idempotency_key]
            if fingerprint != oldhash:
                raise ValueError("IDEMPOTENCY_CONFLICT")
            return state
        if self.head.completed:
            raise ValueError("COMPLETED_STATE_IMMUTABLE")
        if p.read_revision != self.head.revision:
            raise ValueError("STALE_REVISION")
        if p.binding != self.binding or p.producer != self.plan.producer_build:
            raise ValueError("EVENT_BINDING")
        if event.writer_role not in (*self.plan.requested_roles, "research_manager"):
            raise ValueError("UNAUTHORIZED_WRITER")
        if p.payload_sha256 != digest(event.payload) or p.event.sha256 != digest(
            event.payload
        ):
            raise ValueError("EVENT_PAYLOAD_HASH")
        if any(old.provenance.event.id == p.event.id for old in self._events):
            raise ValueError("DUPLICATE_EVENT_ID")
        if self._events and p.occurred_at < self._events[-1].provenance.occurred_at:
            raise ValueError("EVENT_CLOCK_REGRESSION")
        required_reads = self.make_event(
            event.payload, event.writer_role, p.occurred_at, p.idempotency_key
        ).provenance.read_set
        if not set(required_reads) <= set(p.read_set):
            raise ValueError("MISSING_REQUIRED_READ_SET")
        for ref in (*p.read_set, *p.causal_refs):
            if ref.namespace == "STATE":
                if ref != self.head.revision.state:
                    raise ValueError("STALE_READ_SET")
            else:
                self.validator.artifact(ref)
        state = self.head
        changes: dict[str, object] = {}
        value = event.payload.value
        if isinstance(value, AnalystResult):
            self.validator.analyst(value, state.revision)
            if (
                value.participant != event.writer_role
                or value.participant not in self.plan.requested_roles
                or value.scope_id not in self.plan.requested_assets
            ):
                raise ValueError("ANALYST_POPULATION")
            if (value.model, value.prompt, value.producer_build) != (
                self.plan.model,
                self.plan.prompt,
                self.plan.producer_build,
            ):
                raise ValueError("ANALYST_VERSION")
            if value.generated_at > p.occurred_at:
                raise ValueError("EVENT_BEFORE_RESULT")
            expected = {
                s.key: s
                for s in self.plan.slots
                if s.scope_id == value.scope_id and s.role == value.participant
            }
            if {(c.scope_id, c.role, c.capability) for c in value.coverage} != set(
                expected
            ) or len(value.coverage) != len(expected):
                raise ValueError("ANALYST_SLOT_OMISSION")
            for c in value.coverage:
                slot = expected[(c.scope_id, c.role, c.capability)]
                if (
                    c.required != slot.required
                    or c.applicability_rule != slot.applicability_rule
                    or (c.status == "NOT_APPLICABLE") == slot.applicable
                ):
                    raise ValueError("FALSE_APPLICABILITY")
                self.validator.artifact(slot.applicability_rule)
            superseded = [
                r
                for r in state.analyst_results
                if (r.participant, r.scope_id) == (value.participant, value.scope_id)
            ]
            invalid = state.invalidated + tuple(r.reference for r in superseded)
            changes.update(
                analyst_results=tuple(
                    r for r in state.analyst_results if r not in superseded
                )
                + (value,),
                invalidated=invalid,
                synthesis=None,
                coverage=(),
            )
        elif isinstance(value, CollaborationMessage):
            if (
                value.run_id != self.binding.run_id
                or value.episode != self.binding.episode
                or value.state_revision != state.revision.state
                or value.budget_ref != self.plan.budgets.reference
            ):
                raise ValueError("MESSAGE_BINDING")
            if value.sender != event.writer_role or any(
                r not in self.plan.requested_roles
                for r in (value.sender, value.recipient)
            ):
                raise ValueError("UNREGISTERED_RECIPIENT")
            if (
                value.created_at > p.occurred_at
                or value.created_at < self.binding.research_as_of
            ):
                raise ValueError("MESSAGE_CLOCK")
            if any(
                m.message_id == value.message_id
                or m.idempotency_key == value.idempotency_key
                for m in state.messages
            ):
                raise ValueError("DUPLICATE_MESSAGE")
            for ref in value.subject_refs:
                self.validator.artifact(ref)
            if len(state.messages) >= self.plan.budgets.max_messages:
                raise ValueError("STATE_MESSAGE_BUDGET_EXHAUSTED")
            if (
                value.kind == "FOLLOWUP_REQUEST"
                and sum(m.kind == "FOLLOWUP_REQUEST" for m in state.messages)
                >= self.plan.budgets.max_followups
            ):
                raise ValueError("STATE_FOLLOWUP_BUDGET_EXHAUSTED")
            requests = state.requests
            if value.kind != "RESOLUTION":
                self.validate_dependency(value)
                known = {r.request.reference for r in requests}
                if not set(value.causal_requests) <= known:
                    raise ValueError("UNKNOWN_CAUSAL_REQUEST")
                requests = requests + (
                    RequestRecord(
                        request=value,
                        status="OPEN",
                        reason="REQUEST_OPEN",
                        response=None,
                    ),
                )
            else:
                from .resolution import validate_resolution

                found = [
                    r for r in requests if r.request.reference in value.causal_requests
                ]
                if len(found) != 1 or found[0].status != "IN_PROGRESS":
                    raise ValueError("RESOLUTION_REQUEST_NOT_IN_PROGRESS")
                current = found[0]
                if value.created_at > current.request.deadline:
                    raise ValueError("RESOLUTION_DEADLINE")
                validate_resolution(
                    self.plan, self.validator, state.revision, current.request, value
                )
                updated = current.model_copy(
                    update={
                        "status": value.resolution_status,
                        "reason": value.purpose,
                        "response": value,
                    }
                )
                requests = tuple(updated if r == current else r for r in requests)
            changes.update(
                messages=state.messages + (value,), requests=requests, synthesis=None
            )
        elif isinstance(value, RequestTransition):
            found = [r for r in state.requests if r.request.reference == value.request]
            if len(found) != 1:
                raise ValueError("UNKNOWN_REQUEST")
            current = found[0]
            if event.writer_role not in (
                current.request.sender,
                current.request.recipient,
                "research_manager",
            ):
                raise ValueError("UNAUTHORIZED_TRANSITION")
            allowed = {
                "OPEN": {"ACKNOWLEDGED", "CANCELLED", "UNRESOLVED", "FAILED"},
                "ACKNOWLEDGED": {"IN_PROGRESS", "CANCELLED", "UNRESOLVED", "FAILED"},
                "IN_PROGRESS": {"UNRESOLVED", "FAILED", "CANCELLED"},
            }
            if value.status not in allowed.get(current.status, set()):
                raise ValueError("INVALID_REQUEST_TRANSITION")
            updated = current.model_copy(
                update={"status": value.status, "reason": value.reason}
            )
            changes.update(
                requests=tuple(updated if r == current else r for r in state.requests),
                synthesis=None,
            )
        elif isinstance(value, SynthesisState):
            if event.writer_role != "research_manager":
                raise ValueError("UNAUTHORIZED_SYNTHESIS")
            owners = {
                ref: r.scope_id
                for r in state.analyst_results
                for ref in (*r.claims, *r.evidence_refs)
            }
            self.validator.synthesis(value, state.revision, owners)
            for case, role in zip(
                (value.base_case, value.bull_case, value.bear_case),
                ("research_manager", "bull_manager", "bear_manager"),
                strict=True,
            ):
                present = {canonical(s) for s in case.uncertainties}
                if any(
                    canonical(s) not in present
                    for s in scenario_uncertainties(case, state.analyst_results, role)
                ):
                    raise ValueError("MISSING_RELEVANT_SYNTHESIS_UNCERTAINTY")
            if value.generated_at > p.occurred_at:
                raise ValueError("EVENT_BEFORE_SYNTHESIS")
            if any(ref in state.invalidated for ref in value.dependencies):
                raise ValueError("INVALIDATED_DEPENDENCY")
            if any(
                c.status == "COMPLETE"
                for c in (value.base_case, value.bull_case, value.bear_case)
            ) and (
                any(r.status not in ("RESOLVED", "CANCELLED") for r in state.requests)
                or any(
                    c.required
                    and c.status != "COMPLETE"
                    and c.status != "NOT_APPLICABLE"
                    for c in self.census()
                )
            ):
                raise ValueError("INCOMPLETE_STATE_SYNTHESIS")
            changes["synthesis"] = value
        else:
            if (
                event.writer_role != "research_manager"
                or value != self.census()
                or any(
                    r.status in ("OPEN", "ACKNOWLEDGED", "IN_PROGRESS")
                    for r in state.requests
                )
            ):
                raise ValueError("FINAL_CENSUS_OR_OPEN_REQUEST")
            changes.update(coverage=value, completed=True)
        events = (*self._events, event)
        result = StateSnapshot.model_validate(
            {
                **state.model_dump(),
                **changes,
                "sequence": state.sequence + 1,
                "parent": state.revision.state,
                "event_log_sha256": digest(events),
            }
        )
        if isinstance(value, AnalystResult):
            self.validator.bind(value.reference, value)
        if isinstance(value, CollaborationMessage):
            self.validator.bind(value.reference, value)
        self.validator.bind(result.revision.state, result)
        self._events.append(event)
        self._snapshots.append(result)
        self._keys[p.idempotency_key] = (fingerprint, result)
        return result
