"""DuckDB persistence for immutable point-in-time research samples."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import duckdb
from pydantic import ValidationError

from src.models.identifiers import AssetId
from src.models.types import JsonValue
from src.repositories.base import (
    BaseRepository,
    RepositoryError,
    decode_json_object,
    encode_json,
)
from src.repositories.records import ResearchDatasetSampleRecord
from src.schemas.research_dataset import ResearchDatasetSample
from src.schemas.temporal import require_utc_aware

_COLUMNS = (
    "sample_id",
    "asset_id",
    "market",
    "research_as_of",
    "research_state_id",
    "research_episode_id",
    "data_snapshot_id",
    "sector_context_id",
    "attribution_bundle_id",
    "quality_status",
    "label_status",
    "dataset_schema_version",
    "dataset_build_version",
    "input_fingerprint",
    "sample_json",
    "created_at",
)


class ResearchDatasetRepository(BaseRepository):
    """Store and retrieve immutable ResearchDatasetSample audit rows."""

    def save(self, sample: ResearchDatasetSample) -> None:
        """Insert one sample without replacing an existing identity."""

        try:
            with self._database.transaction() as connection:
                connection.execute(
                    f"""
                    INSERT INTO research_dataset_samples ({", ".join(_COLUMNS)})
                    VALUES ({", ".join("?" for _ in _COLUMNS)})
                    """,
                    _values(sample),
                )
        except duckdb.Error as exc:
            raise RepositoryError("failed to save research dataset sample") from exc

    def get(self, sample_id: str) -> ResearchDatasetSample | None:
        """Return one sample after validating its duplicated audit columns."""

        row = self._fetch_one(
            f"""
            SELECT {", ".join(_COLUMNS)}
            FROM research_dataset_samples
            WHERE sample_id = ?
            """,
            (sample_id,),
        )
        return None if row is None else _from_row(row)

    def list_for_asset(
        self,
        asset_id: AssetId,
        *,
        as_of: datetime | None = None,
    ) -> tuple[ResearchDatasetSample, ...]:
        """List an Asset's immutable samples through an optional UTC cutoff."""

        clause = " AND research_as_of <= ?" if as_of is not None else ""
        parameters: tuple[object, ...] = (str(asset_id),)
        if as_of is not None:
            parameters = (*parameters, _utc_naive(require_utc_aware(as_of)))
        rows = self._fetch_all(
            f"""
            SELECT {", ".join(_COLUMNS)}
            FROM research_dataset_samples
            WHERE asset_id = ?{clause}
            ORDER BY research_as_of, sample_id
            """,
            parameters,
        )
        return tuple(_from_row(row) for row in rows)


def _values(sample: ResearchDatasetSample) -> tuple[object, ...]:
    return (
        sample.sample_id,
        str(sample.asset_id),
        sample.market.value,
        _utc_naive(sample.research_as_of),
        sample.research_state_id,
        sample.research_episode_id,
        sample.data_snapshot_id,
        sample.sector_context_id,
        sample.attribution_bundle_id,
        sample.quality.status.value,
        sample.label_status.value,
        sample.dataset_schema_version,
        sample.dataset_build_version,
        sample.input_fingerprint,
        encode_json(cast(JsonValue, sample.model_dump(mode="json"))),
        _utc_naive(sample.created_at),
    )


def _from_row(row: tuple[object, ...]) -> ResearchDatasetSample:
    values = dict(zip(_COLUMNS, row, strict=True))
    try:
        sample = ResearchDatasetSample.model_validate(
            decode_json_object(str(values.pop("sample_json")))
        )
        record = ResearchDatasetSampleRecord.model_validate(
            {**values, "sample": sample}
        )
    except ValidationError as exc:
        raise RepositoryError("stored research dataset sample is invalid") from exc
    if (
        record.sample_id != sample.sample_id
        or record.asset_id != sample.asset_id
        or record.market != sample.market.value
        or _utc_naive(record.research_as_of) != _utc_naive(sample.research_as_of)
        or record.research_state_id != sample.research_state_id
        or record.research_episode_id != sample.research_episode_id
        or record.data_snapshot_id != sample.data_snapshot_id
        or record.sector_context_id != sample.sector_context_id
        or record.attribution_bundle_id != sample.attribution_bundle_id
        or record.quality_status is not sample.quality.status
        or record.label_status is not sample.label_status
        or record.dataset_schema_version != sample.dataset_schema_version
        or record.dataset_build_version != sample.dataset_build_version
        or record.input_fingerprint != sample.input_fingerprint
        or _utc_naive(record.created_at) != _utc_naive(sample.created_at)
    ):
        raise RepositoryError("stored research dataset audit columns are inconsistent")
    return sample


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
