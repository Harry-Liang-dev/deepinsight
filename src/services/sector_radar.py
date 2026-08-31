"""Persist Sector Radar events and project them into existing Memory scopes."""

from __future__ import annotations

from src.models.enums import (
    EventSeverity,
    MemoryLevel,
    ResearchScopeType,
    SectorAnomalyType,
    SectorNodeType,
)
from src.models.protocols import MemoryServiceProtocol
from src.repositories.sectors import SectorOntologyRepository
from src.schemas.common import SourceReference
from src.schemas.memory import (
    MemorySearchRequest,
    MemorySearchResponse,
    MemoryWriteRequest,
)
from src.schemas.sectors import SectorAnomalyEvent


class SectorRadarMemoryError(RuntimeError):
    """Raised when an event cannot be mapped to valid hierarchical scopes."""


class SectorRadarMemoryService:
    """Use one canonical event body across existing Sector/Chain/Asset Memory."""

    def __init__(
        self,
        repository: SectorOntologyRepository,
        memory: MemoryServiceProtocol,
    ) -> None:
        """Bind the structured Radar repository and existing Memory service."""

        self._repository = repository
        self._memory = memory

    def persist(self, event: SectorAnomalyEvent) -> tuple[str, ...]:
        """Persist one event and write identical attributable scope projections."""

        scope_ids = self._scope_ids(event)
        self._repository.save_anomaly_event(event, scope_ids=scope_ids)
        source_assets = {
            f"ASSET:{str(asset_id).split(':', 1)[1]}": asset_id
            for asset_id in event.source_asset_ids
        }
        memory_ids = []
        for scope_id in scope_ids:
            asset_id = source_assets.get(scope_id)
            result = self._memory.write(
                MemoryWriteRequest(
                    memory_level=(
                        MemoryLevel.L1
                        if event.event_type is SectorAnomalyType.MACRO_SHOCK
                        else MemoryLevel.L2
                    ),
                    namespace_key=scope_id,
                    effective_ts=event.available_at,
                    summary_text=event.summary,
                    asset_id=asset_id,
                    memory_type="sector_anomaly_event",
                    importance_score=_importance(event.severity),
                    source_ref_json=SourceReference(
                        document_id=event.source_evidence_ids[0],
                        excerpt_ref=event.event_id,
                        provider="sector_anomaly_radar",
                    ),
                    created_by="sector_anomaly_radar_v1",
                )
            )
            memory_ids.append(result.memory_id)
        return tuple(memory_ids)

    def search_sector(
        self,
        event: SectorAnomalyEvent,
        *,
        query_text: str,
    ) -> MemorySearchResponse:
        """Search the event's effective Sector scope through existing Memory."""

        sector_scope = next(
            scope_id
            for scope_id in self._scope_ids(event)
            if scope_id.startswith("SECTOR:")
        )
        return self._memory.search(
            MemorySearchRequest(
                memory_levels=[MemoryLevel.L1, MemoryLevel.L2],
                namespace_keys=[sector_scope],
                query_text=query_text,
                top_k=10,
            )
        )

    def _scope_ids(self, event: SectorAnomalyEvent) -> tuple[str, ...]:
        as_of = event.as_of.date()
        scopes = self._repository.list_scopes(as_of=as_of)
        scope_ids = {item.scope_id for item in scopes}
        sector_nodes = {
            item.sector_id: item
            for item in self._repository.list_nodes(as_of=as_of)
            if item.node_type is SectorNodeType.SECTOR and item.sector_id is not None
        }
        sector_node = sector_nodes.get(event.sector_id)
        if sector_node is None:
            raise SectorRadarMemoryError("Radar Sector has no effective ontology node")
        sector_candidates = [
            item.scope_id
            for item in scopes
            if item.scope_type is ResearchScopeType.SECTOR
            and item.name.casefold() == sector_node.name.casefold()
        ]
        if len(sector_candidates) != 1:
            raise SectorRadarMemoryError("Radar Sector scope is missing or ambiguous")
        requested = {sector_candidates[0]}
        requested.update(f"CHAIN:{chain_id}" for chain_id in event.chain_ids)
        requested.update(
            f"ASSET:{str(asset_id).split(':', 1)[1]}"
            for asset_id in event.source_asset_ids
        )
        missing = requested - scope_ids
        if missing:
            raise SectorRadarMemoryError("Radar event references an unknown scope")
        return tuple(sorted(requested))


def _importance(severity: EventSeverity) -> float:
    return {
        EventSeverity.LOW: 0.4,
        EventSeverity.MEDIUM: 0.6,
        EventSeverity.HIGH: 0.8,
        EventSeverity.CRITICAL: 1.0,
    }[severity]
