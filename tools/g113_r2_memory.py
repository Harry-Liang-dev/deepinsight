"""Thin receiving-context composition of the original Memory and W6 delivery."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.memory.contracts import ResearchContextRequest
from src.memory.delivery import STREAM, MemoryDelivery, record_checkpoint
from src.memory.hybrid import HybridRead, retrieve_observations
from src.memory.temporal_versions import version_snapshot
from src.memory.vnext import MemoryAccessContext
from src.memory.vnext_contracts import Scope
from src.models.enums import Market, MemoryLevel, ResearchScopeType
from src.schemas.research_data import DataCapability, ResearchDataBundle
from src.schemas.research_episode import ResearchEpisode, ResearchEpisodeBuildInput
from src.schemas.research_state import ResearchStateBuildInput
from src.schemas.research_v2_shared import digest
from src.services.research_episode import ResearchEpisodeBuilder
from src.services.research_state import ResearchStateBuilder
from tools.g111_r1_msft import MSFTMemory
from tools.g113_contract import TaskCatalog
from tools.g113_r1_delivery import checked_state, revalidate_for_send, view_mapping
from tools.g113_r1_prepare import check_delivery


def prospective_episode(
    cutoff: datetime, created: datetime, task: str
) -> ResearchEpisode:
    """Original pure builders: old information cutoff, actual new creation time."""
    body: dict[str, Any] = dict(
        bundle_id="rdb_" + digest(task)[:24],
        input_fingerprint=digest(task),
        asset_id="US:MSFT",
        as_of=cutoff,
        window_start=cutoff.date(),
        window_end=cutoff.date(),
        dataset_version="g113-r2-source-context-only",
    )
    for cap in DataCapability:
        body[cap.value] = dict(
            capability=cap,
            status="missing",
            as_of=cutoff,
            freshness=dict(
                status="unknown",
                evaluated_at=cutoff,
                policy_name="g113-r2",
                policy_version="1",
                reason="No canonical scientific input",
            ),
            quality=dict(
                status="unknown",
                observation_count=0,
                source_count=0,
                reason="No canonical scientific input",
            ),
            requested_field_count=0,
            available_field_count=0,
        )
    state = ResearchStateBuilder().build(
        ResearchStateBuildInput(
            research_data_bundle=ResearchDataBundle.model_validate(body),
            accepted_claims=(),
            source_run_id=task,
        )
    )
    return ResearchEpisodeBuilder().build(
        ResearchEpisodeBuildInput(
            research_state=state,
            agent_traces=(),
            created_at=created,
            missing_metadata=("PROSPECTIVE_DEVELOPMENT_CANDIDATE_NO_AGENT_EXECUTION",),
        )
    )


class ReceivingMemory(MSFTMemory):
    """Existing adapter with explicit receiving Episode; never auto-add ACL scopes."""

    def __init__(self, root: Path, output: Path) -> None:
        """Retain historical scopes, excluding the constructor's empty Episode."""
        super().__init__(root, output)
        self.history_scopes = tuple(s for s in self.history_scopes if s != self.scope)

    def bind_receiver(
        self, ep: ResearchEpisode, access: MemoryAccessContext, invocation: str
    ) -> None:
        """Trusted composition injects context; model/input JSON cannot grant ACL."""
        self.ep = ep
        self.scope = Scope(
            scope_type=ResearchScopeType.RESEARCH_EPISODE,
            scope_id="EPISODE:" + ep.episode_id,
        )
        self.access = access
        self.invocation = invocation
        self.at = datetime.now(UTC)
        for scope in (*self.history_scopes, self.scope):
            access.require("READ_HISTORY", scope)

    def retrieve(self, label: str) -> HybridRead:
        """Reuse original service under supplied ACL and frozen information cutoff."""
        self.at = datetime.now(UTC)
        for scope in (*self.history_scopes, self.scope):
            self.access.require("READ_HISTORY", scope)
        return retrieve_observations(
            self.service(),
            resolver=self.resolver,
            access=self.access,
            journal=self.journal,
            request=ResearchContextRequest(
                query_text="g111 retained context",
                as_of=self.ep.research_as_of,
                market=Market.US,
                namespace_keys=[s.scope_id for s in self.history_scopes],
                memory_levels=[MemoryLevel.L2],
                top_k_per_section=100,
            ),
            episode=self.ep,
            run_id=self.invocation + ":" + label,
            as_created=self.at,
            lane="ATTRIBUTED_SOURCES",
        )


def bind_current(
    memory: ReceivingMemory, catalog: TaskCatalog, template: MemoryDelivery
) -> tuple[MemoryDelivery, dict[str, Any]]:
    """Rebuild a recorded W6 envelope using original IDs, never controlled IDs."""
    expected = memory.journal.entries_with_sequence(STREAM)
    state = checked_state(memory, "r2-freeze")
    binding = check_delivery(memory, state["delivery"], catalog, memory.at)
    cp = state["checkpoint"]
    record_checkpoint(memory.journal, cp, expected=expected)
    views = view_mapping(memory, state)
    candidate = MemoryDelivery.model_validate(
        dict(
            template.model_dump(mode="json"),
            research_as_of=memory.ep.research_as_of,
            checkpoint=cp.model_dump(mode="json"),
            previous_checkpoint_id=cp.identity,
            current_memory=state["records"],
            sources=state["sources"],
            qualified_memory_readset=state["readset"],
            evidence_view_mapping=views,
            specialist_inputs={},
            dependency_receipt={
                "code_fingerprints": state["code_fingerprints"],
                "consumer_task_identity": catalog.identity,
                "consumer_access_identity": digest(memory.access),
                "receiving_episode": memory.ep.episode_id,
            },
        )
    )
    # This envelope describes CURRENT NoChange authority only. The separate
    # W3 experiment describes a historical transition; it grants no daily task.
    if candidate.mode != "ACTUAL_NOCHANGE":
        raise ValueError("R2_CONTROLLED_STORE_NOT_ALLOWED")
    body = candidate.model_dump(mode="json")
    stream = "g113-r1-deliveries"
    with memory.journal.serialized():
        if version_snapshot(memory.journal) != cp.memory_snapshot:
            raise ValueError("DELIVERY_STALE_SNAPSHOT")
        snapshot = memory.journal.entries_with_sequence(stream)
        memory.journal.append(
            stream,
            digest(body),
            json.dumps(body, sort_keys=True),
            len(snapshot),
            expected_snapshot=snapshot,
        )
    return candidate, binding


def recheck(
    memory: ReceivingMemory,
    candidate: MemoryDelivery,
    catalog: TaskCatalog,
    expected_access: str,
) -> dict[str, Any]:
    """No network: repeat W6 checks plus R1 current lifecycle and receiving scope."""
    if (
        digest(memory.access) != expected_access
        or expected_access != candidate.dependency_receipt["consumer_access_identity"]
    ):
        raise ValueError("R2_CURRENT_ACCESS_CHANGED")
    if candidate.dependency_receipt["receiving_episode"] != memory.ep.episode_id:
        raise ValueError("R2_RECEIVING_EPISODE_CHANGED")
    if candidate.dependency_receipt["consumer_task_identity"] != catalog.identity:
        raise ValueError("R2_TASK_VERSION_DRIFT")
    receipt = revalidate_for_send(memory, candidate)
    delivery = memory.retrieve("r2-current-lifecycle")
    receipt["R1_current_binding"] = check_delivery(memory, delivery, catalog, memory.at)
    receipt["dispatch_authorized"] = False
    return receipt
