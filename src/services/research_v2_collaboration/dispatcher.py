"""Finite offline dispatch embedded in the existing Coordinator's versioned path."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Literal

from src.schemas.research_v2_collaboration import (
    AnalystResult,
    CollaborationMessage,
    SynthesisState,
)
from src.schemas.research_v2_shared import Frozen, Reference

from .resolution import assess_resolution
from .state import Mutation, RequestTransition, StateReducer, StateSnapshot


class BudgetExceeded(ValueError):
    """A finite limit was reached; no provider or unbounded retry is attempted."""


class BudgetUsage(Frozen):
    """Logical usage; operational elapsed time lives in a separate receipt."""

    rounds: int
    messages: int
    followups: int
    retries: int
    tool_calls: Literal[0]
    provider_calls: Literal[0]
    llm_calls: Literal[0]
    tokens: Literal[0]
    exhausted: tuple[str, ...]


class ResponseEvidence(Frozen):
    """An Analyst's proposed references, not a self-declared accepted resolution."""

    evidence: tuple[Reference, ...]
    reason: str


Handler = Callable[[CollaborationMessage, StateSnapshot], ResponseEvidence]


class BoundedDispatcher:
    """Serial CAS scheduling with bounded offline capabilities and explicit census."""

    def __init__(
        self,
        reducer: StateReducer,
        clock: Callable[[], datetime],
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Inject clocks and registered handlers; no implicit live Gateway default."""
        self.reducer = reducer
        self.plan = reducer.plan
        self.clock = clock
        self.monotonic = monotonic
        self.started = monotonic()
        self.rounds = 0
        self.messages = 0
        self.followups = 0
        self.retries: dict[str, int] = {}
        self.exhausted: list[str] = []

    @property
    def usage(self) -> BudgetUsage:
        """Expose complete non-performance usage for deterministic evaluation."""
        return BudgetUsage(
            rounds=self.rounds,
            messages=self.messages,
            followups=self.followups,
            retries=sum(self.retries.values()),
            tool_calls=0,
            provider_calls=0,
            llm_calls=0,
            tokens=0,
            exhausted=tuple(dict.fromkeys(self.exhausted)),
        )

    def check_time(self) -> None:
        """Reject work after the configured wall budget."""
        if self.monotonic() - self.started >= self.plan.budgets.max_wall_seconds:
            self.exhausted.append("WALL_TIME")
            raise BudgetExceeded("WALL_TIME")

    def consume_external(
        self, *, tools: int = 0, tokens: int = 0, provider: int = 0, llm: int = 0
    ) -> None:
        """Offline policy never grants external work, even on a zero-use request."""
        if min(tools, tokens, provider, llm) < 0:
            raise ValueError("NEGATIVE_BUDGET_USAGE")
        if any((tools, tokens, provider, llm)):
            self.exhausted.append("OFFLINE_EXTERNAL_BUDGET")
            raise BudgetExceeded("OFFLINE_EXTERNAL_BUDGET")

    def _write(self, payload: Mutation, writer: str, key: str) -> StateSnapshot:
        event = self.reducer.make_event(
            payload,
            writer,
            self.clock(),
            key,
            read_set=(self.reducer.head.revision.state,),
        )
        return self.reducer.apply(event)

    def publish(self, result: AnalystResult) -> StateSnapshot:
        """Validate a whole AnalystResult, including every invalid sibling."""
        self.check_time()
        return self._write(
            Mutation(kind="ANALYST", value=result), result.participant, result.result_id
        )

    def request(self, message: CollaborationMessage) -> StateSnapshot:
        """Check finite limits and dependency cycles before an atomic request append."""
        self.check_time()
        if message.kind == "RESOLUTION":
            raise ValueError("USE_VALIDATED_RESPONSE_PATH")
        if self.messages >= self.plan.budgets.max_messages:
            self.exhausted.append("MESSAGES")
            raise BudgetExceeded("MESSAGES")
        if (
            message.kind == "FOLLOWUP_REQUEST"
            and self.followups >= self.plan.budgets.max_followups
        ):
            self.exhausted.append("FOLLOWUPS")
            raise BudgetExceeded("FOLLOWUPS")
        self._check_cycle(message)
        state = self._write(
            Mutation(kind="MESSAGE", value=message),
            message.sender,
            message.idempotency_key,
        )
        self.messages += 1
        self.followups += int(message.kind == "FOLLOWUP_REQUEST")
        return state

    def _check_cycle(self, message: CollaborationMessage) -> None:
        self.reducer.validate_dependency(message)

    def transition(
        self,
        request: Reference,
        status: Literal[
            "ACKNOWLEDGED", "IN_PROGRESS", "UNRESOLVED", "FAILED", "CANCELLED"
        ],
        reason: str,
    ) -> StateSnapshot:
        """Terminal exhaustion is administrative, not an extra Agent message."""
        return self._write(
            Mutation(
                kind="TRANSITION",
                value=RequestTransition(request=request, status=status, reason=reason),
            ),
            "research_manager",
            request.id + "-" + status,
        )

    def respond(
        self, request: CollaborationMessage, answer: ResponseEvidence
    ) -> StateSnapshot:
        """Validate original conditions before issuing a typed response."""
        self.check_time()
        if self.messages >= self.plan.budgets.max_messages:
            self.exhausted.append("MESSAGES")
            return self.transition(
                request.reference, "UNRESOLVED", "MESSAGE_BUDGET_EXHAUSTED"
            )
        revision = self.reducer.head.revision
        proof = assess_resolution(
            self.plan, self.reducer.validator, revision, request, answer.evidence
        )
        self.reducer.validator.bind(proof.reference, proof)
        response = CollaborationMessage(
            schema_version="research_collaboration_message_v1",
            message_id="response-" + request.message_id,
            kind="RESOLUTION",
            run_id=request.run_id,
            episode=request.episode,
            state_revision=revision.state,
            sender=request.recipient,
            recipient=request.sender,
            created_at=self.clock(),
            deadline=request.deadline,
            priority=request.priority,
            idempotency_key="response-" + request.idempotency_key,
            causal_requests=(request.reference,),
            subject_refs=request.subject_refs,
            purpose=answer.reason,
            acceptance_conditions=request.acceptance_conditions,
            budget_ref=request.budget_ref,
            resolution_status="RESOLVED" if proof.satisfied else "UNRESOLVED",
            resolution_evidence=answer.evidence,
            validation_receipt=proof.reference,
        )
        state = self._write(
            Mutation(kind="MESSAGE", value=response),
            response.sender,
            response.idempotency_key,
        )
        self.messages += 1
        return state

    def run(self, handlers: Mapping[str, Handler]) -> StateSnapshot:
        """Schedule by stable priority and terminate unavailable work."""
        while any(r.status == "OPEN" for r in self.reducer.head.requests):
            if self.rounds >= self.plan.budgets.max_rounds:
                self.exhausted.append("ROUNDS")
                break
            self.rounds += 1
            pending = sorted(
                (r.request for r in self.reducer.head.requests if r.status == "OPEN"),
                key=lambda r: (-r.priority, r.created_at, r.message_id),
            )
            for request in pending:
                try:
                    self.check_time()
                except BudgetExceeded:
                    break
                if self.clock() > request.deadline:
                    self.transition(request.reference, "UNRESOLVED", "DEADLINE_EXPIRED")
                    continue
                if request.recipient not in handlers:
                    self.transition(request.reference, "UNRESOLVED", "MISSING_ANALYST")
                    continue
                dependencies = [
                    r
                    for r in self.reducer.head.requests
                    if r.request.reference in request.causal_requests
                ]
                if any(r.status != "RESOLVED" for r in dependencies):
                    continue
                self.transition(
                    request.reference, "ACKNOWLEDGED", "REQUEST_ACKNOWLEDGED"
                )
                self.transition(request.reference, "IN_PROGRESS", "REQUEST_IN_PROGRESS")
                for attempt in range(self.plan.budgets.max_retries_per_request + 1):
                    try:
                        answer = handlers[request.recipient](request, self.reducer.head)
                        self.respond(request, answer)
                        break
                    except (ValueError, RuntimeError) as error:
                        if (
                            isinstance(error, BudgetExceeded)
                            or attempt == self.plan.budgets.max_retries_per_request
                        ):
                            self.transition(
                                request.reference,
                                "UNRESOLVED",
                                type(error).__name__ + ":" + str(error),
                            )
                            break
                        self.retries[request.message_id] = (
                            self.retries.get(request.message_id, 0) + 1
                        )
        for record in self.reducer.head.requests:
            if record.status in ("OPEN", "ACKNOWLEDGED", "IN_PROGRESS"):
                self.transition(
                    record.request.reference,
                    "UNRESOLVED",
                    "DISPATCH_BUDGET_OR_DEPENDENCY_EXHAUSTED",
                )
        return self.reducer.head

    def synthesize(self, synthesis: SynthesisState) -> StateSnapshot:
        """Delegate factual traceability to the canonical validator before CAS."""
        self.check_time()
        return self._write(
            Mutation(kind="SYNTHESIS", value=synthesis),
            "research_manager",
            "synthesis-" + str(self.reducer.head.sequence),
        )

    def finalize(self) -> StateSnapshot:
        """Commit the whole census, preserving missing Analyst outcomes."""
        return self._write(
            Mutation(kind="FINALIZE", value=self.reducer.census()),
            "research_manager",
            "final-census",
        )
