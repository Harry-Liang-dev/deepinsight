"""G113-R1 controlled delivery envelopes; neither admission nor a scheduler."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any, Literal

from pydantic import Field

from src.memory.incremental import (
    MemoryChange,
    MemoryChangeSet,
    ResearchDependency,
    resolve_impact,
)
from src.memory.vnext_contracts import Frozen, Scope
from src.repositories.memory_journal import MemoryJournalRepository
from src.schemas.research_v2_shared import Clock, digest, reference

STREAM = "g113-r1-checkpoints"
ROLES = ("fundamental_analyst", "news_event_analyst")


class DependencyCheckpoint(Frozen):
    """Composition-root verified dependencies, persisted in the original journal."""

    schema_version: Literal["g113_r1_dependency_checkpoint_v1"] = (
        "g113_r1_dependency_checkpoint_v1"
    )
    checked_at: Clock
    memory_snapshot: str
    dependencies: dict[str, str]
    qualification: Literal["CURRENTLY_REVALIDATED"] = "CURRENTLY_REVALIDATED"

    @property
    def identity(self) -> str:
        """Bind all checked clocks and dependencies, not just source bytes."""
        return digest(self.model_dump(mode="json"))


class MemoryDelivery(Frozen):
    """Versioned input candidate; consumers must recheck before any model send."""

    schema_version: Literal["g113_r1_memory_delivery_v1"] = "g113_r1_memory_delivery_v1"
    mode: Literal["ACTUAL_NOCHANGE", "HISTORICAL_DIAGNOSTIC_NOT_NEW_MARKET_EVENT"]
    research_as_of: Clock
    checkpoint: DependencyCheckpoint
    previous_checkpoint_id: str
    historical_memory_ids: tuple[str, ...]
    current_memory: tuple[dict[str, Any], ...]
    sources: tuple[dict[str, Any], ...]
    delta_census: tuple[dict[str, Any], ...]
    relation_delta: tuple[dict[str, Any], ...]
    qualified_memory_readset: dict[str, Any]
    impact_plan: dict[str, Any]
    specialist_inputs: dict[str, Any]
    evidence_view_mapping: tuple[dict[str, Any], ...]
    dependency_receipt: dict[str, Any]
    known_unknowns: tuple[str, ...]
    agent_result_reuse: Literal["NOT_EVALUABLE"] = "NOT_EVALUABLE"
    scientific_admission: Literal[False] = False
    dispatch_authorized: Literal[False] = False
    actually_consumed_memory_ids: tuple[str, ...] = ()
    required_presend_checks: tuple[str, ...] = (
        "CURRENT_PERMISSION",
        "SOURCE_BYTES_AND_SPANS",
        "CLOCK",
        "MEMORY_VERSION",
        "RELATION_ENDPOINTS",
        "TASK_CONTRACT",
        "VALIDATOR_QUALIFICATION",
    )
    evidence_coverage: dict[str, Any] = Field(default_factory=dict)


def record_checkpoint(
    journal: MemoryJournalRepository,
    checkpoint: DependencyCheckpoint,
    *,
    expected: tuple[tuple[int, str, str], ...],
) -> None:
    """Append audit only with original ordered CAS; never mutate Memory content."""
    with journal.serialized():
        journal.append(
            STREAM,
            checkpoint.identity,
            checkpoint.model_dump_json(),
            len(expected),
            expected_snapshot=expected,
        )


def dependency_changes(
    journal: MemoryJournalRepository,
    previous: DependencyCheckpoint,
    current: DependencyCheckpoint,
) -> list[dict[str, Any]]:
    """External checkpoint JSON is not trusted without the exact journal receipt."""
    if (previous.identity, previous.model_dump_json()) not in journal.entries(STREAM):
        raise ValueError("DELIVERY_UNRECORDED_CHECKPOINT")
    if current.checked_at < previous.checked_at:
        raise ValueError("DELIVERY_CLOCK_REGRESSION")
    return [
        {
            "key": k,
            "cause": k.split(":", 1)[0],
            "before": previous.dependencies.get(k),
            "after": current.dependencies.get(k),
        }
        for k in sorted(previous.dependencies.keys() | current.dependencies.keys())
        if previous.dependencies.get(k) != current.dependencies.get(k)
    ]


def selective_plan(
    *,
    at: Clock,
    previous_identity: str,
    changes: list[dict[str, Any]],
    dependencies: dict[str, str],
    tasks: dict[str, Any],
    scope: Scope,
    explicit_roles: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Adapt cause-specific keys to G85; W3 owns semantics and W1 scheduling."""
    if set(tasks) != set(ROLES) or not set(explicit_roles) <= set(ROLES):
        raise ValueError("DELIVERY_UNREGISTERED_TASK_ROLE")
    keys = {r["key"] for r in changes} | {"EXPLICIT_TASK:" + r for r in explicit_roles}
    changeset = MemoryChangeSet(
        as_of=at,
        created_at=at,
        previous_population=previous_identity,
        checked_population=(),
        changes=tuple(
            MemoryChange(
                key=k,
                status="UPDATED",
                before=None,
                after=None,
                delta=None,
                catalyst_identity=k,
            )
            for k in sorted(keys)
        ),
    )
    shared = {
        k
        for k in dependencies.keys() | keys
        if not k.startswith(("TASK_CONTRACT:", "EXPLICIT_TASK:"))
    }
    deps = tuple(
        ResearchDependency(
            artifact=reference("QUESTION", role, "g113_r1_w3_task_v1", tasks[role]),
            scope=scope,
            source_keys=tuple(
                sorted(shared | {"TASK_CONTRACT:" + role, "EXPLICIT_TASK:" + role})
            ),
            upstream=(),
            valid_from=at,
            valid_until=at + timedelta(hours=1),
        )
        for role in ROLES
    )
    impact = resolve_impact(changeset, deps, lambda _: b"")
    affected = [r.id for r in impact.invalidated]
    return {
        "changeset": changeset.model_dump(mode="json"),
        "impact": impact.model_dump(mode="json"),
        "dependencies": [d.model_dump(mode="json") for d in deps],
        "trigger_causes": changes,
        "explicit_task_roles": explicit_roles,
        "affected_specialist_candidates": affected,
        "skipped_tasks": [r for r in ROLES if r not in affected],
        "skip_reason": (
            "ALL_RELEVANT_DEPENDENCIES_REVALIDATED_UNCHANGED" if not keys else None
        ),
        "dispatch_authorized": False,
        "policy_owner": "W3",
        "execution_owner": "W1",
        "real_cross_company": "NOT_DEMONSTRATED",
    }


def require_recorded_delivery(
    journal: MemoryJournalRepository, delivery: MemoryDelivery
) -> None:
    """A matching schema or self-declared fingerprint grants no input authority."""
    body = delivery.model_dump(mode="json")
    if (digest(body), json.dumps(body, sort_keys=True)) not in journal.entries(
        "g113-r1-deliveries"
    ):
        raise ValueError("DELIVERY_UNRECORDED_ENVELOPE")
