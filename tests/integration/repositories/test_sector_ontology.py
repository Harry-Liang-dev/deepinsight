"""DuckDB integration tests for point-in-time Sector Ontology storage."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import cast

import pytest

from src.models.enums import (
    SectorCapabilityStatus,
    SectorId,
    SectorMembershipRole,
)
from src.models.identifiers import AssetId
from src.operators import SectorStateOperator
from src.repositories import DuckDBDatabase, SectorOntologyRepository
from src.schemas.sectors import SectorBenchmarkMapping, SectorMembership
from src.services import (
    SectorOntologyService,
    SectorUniverseError,
    SectorUniverseService,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def repository(tmp_path: Path) -> SectorOntologyRepository:
    """Return an isolated, bootstrapped Sector Repository."""

    database = DuckDBDatabase(tmp_path / "sector-ontology.duckdb")
    database.bootstrap()
    return SectorOntologyRepository(database)


def test_seed_round_trips_graph_memberships_and_scopes(
    repository: SectorOntologyRepository,
) -> None:
    """The minimal AAPL/NVDA/AMD/TSM/MU seed persists without parallel storage."""

    seed = SectorOntologyService(repository).install_v1_seed()
    SectorOntologyService(repository).install_v1_seed()
    as_of = date(2026, 8, 30)

    nodes = repository.list_nodes(as_of=as_of)
    edges = repository.list_edges(as_of=as_of)
    scopes = repository.list_scopes(as_of=as_of)
    seeded_assets = {str(item.asset_id) for item in seed.memberships}

    assert seeded_assets == {"US:AAPL", "US:NVDA", "US:AMD", "US:TSM", "US:MU"}
    assert len(nodes) == 26
    assert len(edges) == 9
    assert len(scopes) == 14
    assert repository.list_memberships(AssetId("US:NVDA"), as_of=as_of) == [
        next(item for item in seed.memberships if str(item.asset_id) == "US:NVDA")
    ]


def test_membership_history_is_preserved_by_point_in_time_reads(
    repository: SectorOntologyRepository,
) -> None:
    """Appending a new revision never overwrites an earlier membership period."""

    old = SectorMembership(
        asset_id=AssetId("US:AAPL"),
        sector_id=SectorId.CONSUMER_ELECTRONICS_HARDWARE,
        chain_ids=("APPLE_CHAIN",),
        role=SectorMembershipRole.CORE,
        valid_from=date(2020, 1, 1),
        valid_to=date(2025, 1, 1),
        weight=1.0,
        confidence=0.7,
        source="historical_test_source",
        version="membership_v1",
    )
    current = old.model_copy(
        update={
            "valid_from": date(2025, 1, 1),
            "valid_to": None,
            "confidence": 0.9,
            "version": "membership_v2",
        }
    )
    repository.add_membership(old)
    repository.add_membership(current)

    historical = repository.list_memberships(
        AssetId("US:AAPL"),
        as_of=date(2024, 12, 31),
    )
    latest = repository.list_memberships(
        AssetId("US:AAPL"),
        as_of=date(2025, 1, 1),
    )

    assert historical == [old]
    assert latest == [current]


def test_universe_snapshot_round_trip_and_versioning(
    repository: SectorOntologyRepository,
) -> None:
    """Later snapshots append new state and preserve the earlier PIT universe."""

    SectorOntologyService(repository).install_v1_seed()
    repository.add_benchmark_mapping(
        SectorBenchmarkMapping(
            sector_id=SectorId.SEMICONDUCTORS_AI_COMPUTE,
            benchmark_ids=(AssetId("US:SOXX"),),
            status=SectorCapabilityStatus.AVAILABLE,
            source="alpaca_market_data:eod_bar_validation",
            valid_from=date(2026, 8, 1),
            version="us_sector_benchmarks_v1",
        )
    )
    service = SectorUniverseService(repository)
    first = service.create_snapshot(
        sector_id=SectorId.SEMICONDUCTORS_AI_COMPUTE,
        as_of=date(2026, 8, 30),
        membership_version="phase4_day30_seed_v1",
        source="test_universe_v1",
    )
    second = service.create_snapshot(
        sector_id=SectorId.SEMICONDUCTORS_AI_COMPUTE,
        as_of=date(2026, 8, 31),
        membership_version="phase4_day30_seed_v1",
        source="test_universe_v1",
    )

    assert first.snapshot_id != second.snapshot_id
    assert repository.get_universe_snapshot(first.snapshot_id) == first
    assert repository.get_universe_snapshot(second.snapshot_id) == second
    assert first.asset_ids == (AssetId("US:AMD"), AssetId("US:NVDA"), AssetId("US:TSM"))
    assert first.benchmark_ids == (AssetId("US:SOXX"),)


def test_unknown_sector_behavior_is_explicit(
    repository: SectorOntologyRepository,
) -> None:
    """Runtime strings cannot silently create an unknown Sector universe."""

    service = SectorUniverseService(repository)

    with pytest.raises(SectorUniverseError, match="unknown Sector"):
        service.create_snapshot(
            sector_id=cast(SectorId, "S99"),
            as_of=date(2026, 8, 30),
            membership_version="v1",
            source="test",
        )


def test_sector_research_snapshot_round_trip(
    repository: SectorOntologyRepository,
) -> None:
    """Deterministic Sector state persists through the existing Repository."""

    SectorOntologyService(repository).install_v1_seed()
    universe = SectorUniverseService(repository).create_snapshot(
        sector_id=SectorId.CLOUD_SOFTWARE_AI_APPLICATIONS,
        as_of=date(2026, 8, 30),
        membership_version="sector_universe_membership_v1",
        source="empty_test_universe",
    )
    snapshot = SectorStateOperator().compute(
        universe=universe,
        bars_by_asset={},
        fundamentals_by_asset={},
    )

    repository.save_research_snapshot(snapshot)

    assert repository.get_research_snapshot(snapshot.snapshot_id) == snapshot
