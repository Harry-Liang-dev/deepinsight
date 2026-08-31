"""Structured Radar persistence and existing Memory-scope integration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.models.enums import (
    AgentStatus,
    AnomalyDirection,
    EventSeverity,
    SectorAnomalyStatus,
    SectorAnomalyType,
    SectorId,
)
from src.models.identifiers import AssetId
from src.repositories import DuckDBDatabase, SectorOntologyRepository
from src.schemas.memory import (
    MemorySearchRequest,
    MemorySearchResponse,
    MemorySearchResult,
    MemoryWriteRequest,
    MemoryWriteResult,
)
from src.schemas.sectors import SectorAnomalyEvent
from src.services import SectorRadarMemoryService, build_sector_ontology_seed_v1

_AS_OF = datetime(2026, 8, 30, 23, 59, tzinfo=UTC)


class _Memory:
    def __init__(self) -> None:
        self.requests: list[MemoryWriteRequest] = []

    def write(self, request: MemoryWriteRequest) -> MemoryWriteResult:
        self.requests.append(request)
        return MemoryWriteResult(
            memory_id=f"memory-{len(self.requests)}",
            faiss_namespace=f"memory_{request.memory_level.value}_v1",
            faiss_vector_id=len(self.requests),
            status=AgentStatus.OK,
        )

    def search(self, request: MemorySearchRequest) -> MemorySearchResponse:
        matching = [
            item
            for item in self.requests
            if item.namespace_key in request.namespace_keys
            and item.memory_level in request.memory_levels
        ]
        return MemorySearchResponse(
            results=[
                MemorySearchResult(
                    memory_id=f"memory-{index}",
                    memory_level=item.memory_level,
                    namespace_key=item.namespace_key,
                    summary_text=item.summary_text,
                    score=1.0,
                    effective_ts=item.effective_ts,
                    asset_id=item.asset_id,
                    memory_type=item.memory_type,
                    importance_score=item.importance_score,
                    source_ref_json=item.source_ref_json,
                    created_by=item.created_by,
                )
                for index, item in enumerate(matching, start=1)
            ]
        )


def _event() -> SectorAnomalyEvent:
    return SectorAnomalyEvent(
        event_id="sector_anomaly_0123456789abcdef01234567",
        event_type=SectorAnomalyType.EARNINGS,
        sector_id=SectorId.SEMICONDUCTORS_AI_COMPUTE,
        chain_ids=("NVIDIA_AI_INFRA",),
        source_asset_ids=(AssetId("US:NVDA"),),
        affected_asset_ids=(AssetId("US:NVDA"),),
        direction=AnomalyDirection.POSITIVE,
        severity=EventSeverity.HIGH,
        confidence=0.9,
        event_time=_AS_OF - timedelta(hours=2),
        published_at=_AS_OF - timedelta(hours=2),
        available_at=_AS_OF - timedelta(hours=1),
        ingested_at=_AS_OF - timedelta(minutes=30),
        as_of=_AS_OF,
        source_evidence_ids=("earnings:nvda:2026q2",),
        summary="NVDA structured earnings surprise event",
        status=SectorAnomalyStatus.DETECTED,
    )


def test_radar_event_is_pit_retrievable_from_sector_and_memory_scope(
    tmp_path: Path,
) -> None:
    """One canonical body can be linked and retrieved through Sector scope."""

    database = DuckDBDatabase(tmp_path / "radar.duckdb")
    database.bootstrap()
    repository = SectorOntologyRepository(database)
    repository.install_seed(build_sector_ontology_seed_v1())
    memory = _Memory()
    service = SectorRadarMemoryService(repository, memory)
    event = _event()

    memory_ids = service.persist(event)
    stored = repository.list_anomalies_for_scope(
        "SECTOR:SEMICONDUCTORS_AI", as_of=_AS_OF
    )
    searched = service.search_sector(event, query_text="earnings anomaly")

    assert len(memory_ids) == 3
    assert stored == [event]
    assert [item.summary_text for item in searched.results] == [event.summary]
    assert {item.namespace_key for item in memory.requests} == {
        "ASSET:NVDA",
        "CHAIN:NVIDIA_AI_INFRA",
        "SECTOR:SEMICONDUCTORS_AI",
    }
    assert len({item.summary_text for item in memory.requests}) == 1
    assert all(item.memory_type == "sector_anomaly_event" for item in memory.requests)


def test_scope_query_excludes_event_after_cutoff(tmp_path: Path) -> None:
    """Availability time remains a hard query cutoff."""

    database = DuckDBDatabase(tmp_path / "radar-cutoff.duckdb")
    database.bootstrap()
    repository = SectorOntologyRepository(database)
    repository.install_seed(build_sector_ontology_seed_v1())
    SectorRadarMemoryService(repository, _Memory()).persist(_event())

    assert (
        repository.list_anomalies_for_scope(
            "SECTOR:SEMICONDUCTORS_AI", as_of=_AS_OF - timedelta(hours=3)
        )
        == []
    )
