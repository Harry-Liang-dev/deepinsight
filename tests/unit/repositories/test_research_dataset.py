"""DuckDB ResearchDatasetSample persistence tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.models.identifiers import AssetId
from src.repositories import (
    DuckDBDatabase,
    RepositoryError,
    ResearchDatasetRepository,
)
from src.schemas.research_dataset import (
    ResearchDatasetBuildInput,
    ResearchDatasetSample,
)
from src.schemas.research_episode import ResearchEpisode
from src.schemas.research_state import ResearchStateSnapshot
from src.services.research_dataset import ResearchDatasetBuilder

ROOT = Path(__file__).parents[3]


@pytest.fixture
def database(tmp_path: Path) -> DuckDBDatabase:
    """Return an initialized isolated DuckDB database."""
    database = DuckDBDatabase(tmp_path / "dataset.duckdb")
    database.bootstrap()
    return database


@pytest.fixture
def repository(database: DuckDBDatabase) -> ResearchDatasetRepository:
    """Return an isolated dataset Repository."""

    return ResearchDatasetRepository(database)


def _sample() -> ResearchDatasetSample:
    state = ResearchStateSnapshot.model_validate_json(
        (
            ROOT / "data/research_state/day38/phase3_aapl_golden.research_state.json"
        ).read_text(encoding="utf-8")
    )
    episode = ResearchEpisode.model_validate_json(
        (
            ROOT
            / "data/research_episode/day39/phase3_aapl_golden.research_episode.json"
        ).read_text(encoding="utf-8")
    )
    return ResearchDatasetBuilder().build(
        ResearchDatasetBuildInput(
            research_state=state,
            research_episode=episode,
            dataset_build_version="pit_research_dataset_build_v1",
            created_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
    )


def test_repository_roundtrip_and_point_in_time_listing(
    repository: ResearchDatasetRepository,
) -> None:
    """Stored samples retain their typed audit object and replay cutoff."""

    sample = _sample()
    repository.save(sample)

    assert repository.get(sample.sample_id) == sample
    assert repository.list_for_asset(AssetId("US:AAPL")) == (sample,)
    assert repository.list_for_asset(
        AssetId("US:AAPL"),
        as_of=sample.research_as_of,
    ) == (sample,)
    assert (
        repository.list_for_asset(
            AssetId("US:AAPL"),
            as_of=sample.research_as_of.replace(year=2025),
        )
        == ()
    )


def test_repository_never_overwrites_immutable_sample(
    repository: ResearchDatasetRepository,
) -> None:
    """A duplicate stable sample identity fails instead of being replaced."""

    sample = _sample()
    repository.save(sample)
    with pytest.raises(RepositoryError, match="failed to save"):
        repository.save(sample)


def test_repository_rejects_naive_query_cutoff(
    repository: ResearchDatasetRepository,
) -> None:
    """Replay queries cannot silently interpret a local timezone."""

    with pytest.raises(ValueError, match="timezone-aware"):
        repository.list_for_asset(
            AssetId("US:AAPL"),
            as_of=datetime(2026, 8, 14),
        )


def test_repository_rejects_inconsistent_audit_columns(
    repository: ResearchDatasetRepository,
    database: DuckDBDatabase,
) -> None:
    """Duplicated query columns cannot silently disagree with sample JSON."""

    sample = _sample()
    repository.save(sample)
    with database.transaction() as connection:
        connection.execute(
            "UPDATE research_dataset_samples SET quality_status = 'available' "
            "WHERE sample_id = ?",
            (sample.sample_id,),
        )

    with pytest.raises(RepositoryError, match="audit columns"):
        repository.get(sample.sample_id)
