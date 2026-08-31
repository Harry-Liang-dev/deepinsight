"""DuckDB persistence for versioned Sector Ontology and research scopes."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import cast

import duckdb
from pydantic import BaseModel, ValidationError

from src.models.enums import SectorId
from src.models.identifiers import AssetId
from src.models.types import JsonValue
from src.repositories.base import (
    BaseRepository,
    RepositoryError,
    decode_json_value,
    encode_json,
)
from src.schemas.sectors import (
    ResearchScopeDefinition,
    SectorAnomalyEvent,
    SectorBenchmarkMapping,
    SectorEdge,
    SectorMacroSnapshot,
    SectorMembership,
    SectorNode,
    SectorOntologySeed,
    SectorResearchSnapshot,
    SectorUniverseSnapshot,
)

_NODE_COLUMNS = (
    "node_id",
    "node_type",
    "name",
    "sector_id",
    "chain_id",
    "asset_id",
    "description",
    "status",
    "valid_from",
    "valid_to",
    "source",
    "version",
)
_EDGE_COLUMNS = (
    "edge_id",
    "source_node_id",
    "target_node_id",
    "edge_type",
    "confidence",
    "source",
    "valid_from",
    "valid_to",
    "version",
)
_MEMBERSHIP_COLUMNS = (
    "asset_id",
    "sector_id",
    "chain_ids_json",
    "role",
    "valid_from",
    "valid_to",
    "weight",
    "confidence",
    "source",
    "version",
)
_SCOPE_COLUMNS = (
    "scope_id",
    "scope_type",
    "parent_scope_id",
    "name",
    "valid_from",
    "valid_to",
    "version",
)
_BENCHMARK_COLUMNS = (
    "sector_id",
    "benchmark_ids_json",
    "status",
    "source",
    "valid_from",
    "valid_to",
    "version",
)
_UNIVERSE_COLUMNS = (
    "snapshot_id",
    "sector_id",
    "as_of",
    "asset_ids_json",
    "benchmark_ids_json",
    "membership_version",
    "source",
    "coverage_json",
    "quality",
)
_RESEARCH_COLUMNS = (
    "snapshot_id",
    "sector_id",
    "as_of",
    "market_state_json",
    "breadth_state_json",
    "fundamental_state_json",
    "valuation_state_json",
    "coverage_json",
    "source_ids_json",
    "feature_version",
    "status",
)
_MACRO_COLUMNS = (
    "snapshot_id",
    "sector_id",
    "as_of",
    "cycle_state_json",
    "macro_sensitivity_json",
    "source_sector_snapshot_id",
    "feature_version",
    "status",
)
_ANOMALY_COLUMNS = (
    "event_id",
    "event_type",
    "sector_id",
    "chain_ids_json",
    "source_asset_ids_json",
    "affected_asset_ids_json",
    "direction",
    "severity",
    "confidence",
    "event_time",
    "published_at",
    "available_at",
    "ingested_at",
    "as_of",
    "source_evidence_ids_json",
    "summary",
    "propagation_hypothesis",
    "status",
    "version",
)


class SectorOntologyRepository(BaseRepository):
    """Store immutable ontology revisions and query them point in time."""

    def install_seed(self, seed: SectorOntologySeed) -> None:
        """Idempotently install one validated, versioned seed as one transaction."""

        try:
            with self._database.transaction() as connection:
                for node in seed.nodes:
                    connection.execute(
                        _insert_sql("sector_nodes", _NODE_COLUMNS),
                        _node_values(node),
                    )
                for edge in seed.edges:
                    connection.execute(
                        _insert_sql("sector_edges", _EDGE_COLUMNS),
                        _edge_values(edge),
                    )
                for membership in seed.memberships:
                    connection.execute(
                        _insert_sql("sector_memberships", _MEMBERSHIP_COLUMNS),
                        _membership_values(membership),
                    )
                for scope in seed.scopes:
                    connection.execute(
                        _insert_sql("research_scopes", _SCOPE_COLUMNS),
                        _scope_values(scope),
                    )
        except duckdb.Error as exc:
            raise RepositoryError("failed to install Sector Ontology seed") from exc

    def add_membership(self, membership: SectorMembership) -> None:
        """Append one immutable membership revision without replacing history."""

        self._execute(
            _insert_sql(
                "sector_memberships",
                _MEMBERSHIP_COLUMNS,
                ignore_conflict=False,
            ),
            _membership_values(membership),
        )

    def list_memberships(
        self,
        asset_id: AssetId,
        *,
        as_of: date,
    ) -> list[SectorMembership]:
        """Return membership revisions effective on the inclusive cutoff date."""

        rows = self._fetch_all(
            f"""
            SELECT {", ".join(_MEMBERSHIP_COLUMNS)}
            FROM sector_memberships
            WHERE asset_id = ?
              AND valid_from <= ?
              AND (valid_to IS NULL OR ? < valid_to)
            ORDER BY sector_id, role, valid_from, version
            """,
            (str(asset_id), as_of, as_of),
        )
        return [_membership_from_row(row) for row in rows]

    def list_sector_memberships(
        self,
        sector_id: SectorId,
        *,
        as_of: date,
        membership_version: str | None = None,
    ) -> list[SectorMembership]:
        """Return one Sector's effective membership without rewriting history."""

        version_clause = " AND version = ?" if membership_version is not None else ""
        parameters: tuple[object, ...] = (sector_id.value, as_of, as_of)
        if membership_version is not None:
            parameters = (*parameters, membership_version)
        rows = self._fetch_all(
            f"""
            SELECT {", ".join(_MEMBERSHIP_COLUMNS)}
            FROM sector_memberships
            WHERE sector_id = ?
              AND valid_from <= ?
              AND (valid_to IS NULL OR ? < valid_to)
              {version_clause}
            ORDER BY asset_id, role, valid_from, version
            """,
            parameters,
        )
        return [_membership_from_row(row) for row in rows]

    def add_benchmark_mapping(self, mapping: SectorBenchmarkMapping) -> None:
        """Append one immutable point-in-time benchmark mapping."""

        self._execute(
            _insert_sql(
                "sector_benchmark_mappings",
                _BENCHMARK_COLUMNS,
                ignore_conflict=False,
            ),
            _benchmark_values(mapping),
        )

    def get_benchmark_mapping(
        self,
        sector_id: SectorId,
        *,
        as_of: date,
    ) -> SectorBenchmarkMapping | None:
        """Return the latest mapping revision effective at a point in time."""

        row = self._fetch_one(
            f"""
            SELECT {", ".join(_BENCHMARK_COLUMNS)}
            FROM sector_benchmark_mappings
            WHERE sector_id = ?
              AND valid_from <= ?
              AND (valid_to IS NULL OR ? < valid_to)
            ORDER BY valid_from DESC, version DESC
            LIMIT 1
            """,
            (sector_id.value, as_of, as_of),
        )
        return None if row is None else _benchmark_from_row(row)

    def save_universe_snapshot(self, snapshot: SectorUniverseSnapshot) -> None:
        """Persist one immutable universe snapshot; never update an old snapshot."""

        self._execute(
            _insert_sql(
                "sector_universe_snapshots",
                _UNIVERSE_COLUMNS,
                ignore_conflict=False,
            ),
            _universe_values(snapshot),
        )

    def get_universe_snapshot(self, snapshot_id: str) -> SectorUniverseSnapshot | None:
        """Load one immutable universe snapshot by stable identity."""

        row = self._fetch_one(
            f"""
            SELECT {", ".join(_UNIVERSE_COLUMNS)}
            FROM sector_universe_snapshots
            WHERE snapshot_id = ?
            """,
            (snapshot_id,),
        )
        return None if row is None else _universe_from_row(row)

    def get_latest_universe_snapshot(
        self, sector_id: SectorId, *, as_of: date
    ) -> SectorUniverseSnapshot | None:
        """Return the newest immutable universe snapshot available by date."""

        row = self._fetch_one(
            f"""
            SELECT {", ".join(_UNIVERSE_COLUMNS)}
            FROM sector_universe_snapshots
            WHERE sector_id = ? AND as_of <= ?
            ORDER BY as_of DESC, snapshot_id DESC
            LIMIT 1
            """,
            (sector_id.value, as_of),
        )
        return None if row is None else _universe_from_row(row)

    def save_research_snapshot(self, snapshot: SectorResearchSnapshot) -> None:
        """Persist one immutable deterministic Sector research state."""

        self._execute(
            _insert_sql(
                "sector_research_snapshots",
                _RESEARCH_COLUMNS,
                ignore_conflict=False,
            ),
            _research_values(snapshot),
        )

    def get_research_snapshot(self, snapshot_id: str) -> SectorResearchSnapshot | None:
        """Load one deterministic Sector research state by identity."""

        row = self._fetch_one(
            f"""
            SELECT {", ".join(_RESEARCH_COLUMNS)}
            FROM sector_research_snapshots
            WHERE snapshot_id = ?
            """,
            (snapshot_id,),
        )
        return None if row is None else _research_from_row(row)

    def get_latest_research_snapshot(
        self, sector_id: SectorId, *, as_of: date
    ) -> SectorResearchSnapshot | None:
        """Return the newest deterministic Sector state available by date."""

        row = self._fetch_one(
            f"""
            SELECT {", ".join(_RESEARCH_COLUMNS)}
            FROM sector_research_snapshots
            WHERE sector_id = ? AND as_of <= ?
            ORDER BY as_of DESC, snapshot_id DESC
            LIMIT 1
            """,
            (sector_id.value, as_of),
        )
        return None if row is None else _research_from_row(row)

    def save_macro_snapshot(self, snapshot: SectorMacroSnapshot) -> None:
        """Persist one immutable deterministic Sector-to-macro state."""

        self._execute(
            _insert_sql(
                "sector_macro_snapshots",
                _MACRO_COLUMNS,
                ignore_conflict=False,
            ),
            _macro_values(snapshot),
        )

    def get_macro_snapshot(self, snapshot_id: str) -> SectorMacroSnapshot | None:
        """Load one deterministic Sector-to-macro state by identity."""

        row = self._fetch_one(
            f"""
            SELECT {", ".join(_MACRO_COLUMNS)}
            FROM sector_macro_snapshots
            WHERE snapshot_id = ?
            """,
            (snapshot_id,),
        )
        return None if row is None else _macro_from_row(row)

    def get_latest_macro_snapshot(
        self,
        sector_id: SectorId,
        *,
        as_of: date,
    ) -> SectorMacroSnapshot | None:
        """Return the newest Sector macro state available by date."""

        row = self._fetch_one(
            f"""
            SELECT {', '.join(_MACRO_COLUMNS)}
            FROM sector_macro_snapshots
            WHERE sector_id = ? AND as_of <= ?
            ORDER BY as_of DESC, snapshot_id DESC
            LIMIT 1
            """,
            (sector_id.value, as_of),
        )
        return None if row is None else _macro_from_row(row)

    def save_anomaly_event(
        self,
        event: SectorAnomalyEvent,
        *,
        scope_ids: tuple[str, ...],
    ) -> None:
        """Persist one immutable Radar event and its hierarchical scope links."""

        if not scope_ids or len(scope_ids) != len(set(scope_ids)):
            raise ValueError("Radar event requires unique scope IDs")
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    _insert_sql("sector_anomaly_events", _ANOMALY_COLUMNS),
                    _anomaly_values(event),
                )
                for scope_id in scope_ids:
                    connection.execute(
                        """
                        INSERT INTO sector_anomaly_scopes (event_id, scope_id)
                        VALUES (?, ?) ON CONFLICT DO NOTHING
                        """,
                        (event.event_id, scope_id),
                    )
        except duckdb.Error as exc:
            raise RepositoryError("failed to persist Sector anomaly event") from exc

    def get_anomaly_event(self, event_id: str) -> SectorAnomalyEvent | None:
        """Load one immutable Radar event by stable identity."""

        row = self._fetch_one(
            f"""
            SELECT {', '.join(_ANOMALY_COLUMNS)}
            FROM sector_anomaly_events WHERE event_id = ?
            """,
            (event_id,),
        )
        return None if row is None else _anomaly_from_row(row)

    def list_anomalies_for_scope(
        self,
        scope_id: str,
        *,
        as_of: datetime,
    ) -> list[SectorAnomalyEvent]:
        """Return scope-linked Radar events available at the cutoff."""

        row_as_of = _utc_naive(as_of)
        rows = self._fetch_all(
            f"""
            SELECT {', '.join(f'e.{column}' for column in _ANOMALY_COLUMNS)}
            FROM sector_anomaly_events e
            JOIN sector_anomaly_scopes s ON s.event_id = e.event_id
            WHERE s.scope_id = ? AND e.available_at <= ? AND e.ingested_at <= ?
            ORDER BY e.event_time, e.event_id
            """,
            (scope_id, row_as_of, row_as_of),
        )
        return [_anomaly_from_row(row) for row in rows]

    def list_nodes(self, *, as_of: date) -> list[SectorNode]:
        """Return graph node revisions effective at one point in time."""

        rows = self._fetch_all(
            f"""
            SELECT {", ".join(_NODE_COLUMNS)}
            FROM sector_nodes
            WHERE valid_from <= ?
              AND (valid_to IS NULL OR ? < valid_to)
            ORDER BY node_id, valid_from, version
            """,
            (as_of, as_of),
        )
        return [_model_from_row(SectorNode, _NODE_COLUMNS, row) for row in rows]

    def list_edges(self, *, as_of: date) -> list[SectorEdge]:
        """Return graph edge revisions effective at one point in time."""

        rows = self._fetch_all(
            f"""
            SELECT {", ".join(_EDGE_COLUMNS)}
            FROM sector_edges
            WHERE valid_from <= ?
              AND (valid_to IS NULL OR ? < valid_to)
            ORDER BY edge_id, valid_from, version
            """,
            (as_of, as_of),
        )
        return [_model_from_row(SectorEdge, _EDGE_COLUMNS, row) for row in rows]

    def list_scopes(self, *, as_of: date) -> list[ResearchScopeDefinition]:
        """Return hierarchical scopes effective at one point in time."""

        rows = self._fetch_all(
            f"""
            SELECT {", ".join(_SCOPE_COLUMNS)}
            FROM research_scopes
            WHERE valid_from <= ?
              AND (valid_to IS NULL OR ? < valid_to)
            ORDER BY scope_id, valid_from, version
            """,
            (as_of, as_of),
        )
        return [
            _model_from_row(ResearchScopeDefinition, _SCOPE_COLUMNS, row)
            for row in rows
        ]


def _insert_sql(
    table: str,
    columns: tuple[str, ...],
    *,
    ignore_conflict: bool = True,
) -> str:
    conflict = " ON CONFLICT DO NOTHING" if ignore_conflict else ""
    return (
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)}){conflict}"
    )


def _node_values(node: SectorNode) -> tuple[object, ...]:
    return (
        node.node_id,
        node.node_type.value,
        node.name,
        node.sector_id.value if node.sector_id is not None else None,
        node.chain_id,
        str(node.asset_id) if node.asset_id is not None else None,
        node.description,
        node.status.value,
        node.valid_from,
        node.valid_to,
        node.source,
        node.version,
    )


def _edge_values(edge: SectorEdge) -> tuple[object, ...]:
    return (
        edge.edge_id,
        edge.source_node_id,
        edge.target_node_id,
        edge.edge_type.value,
        edge.confidence,
        edge.source,
        edge.valid_from,
        edge.valid_to,
        edge.version,
    )


def _membership_values(membership: SectorMembership) -> tuple[object, ...]:
    return (
        str(membership.asset_id),
        membership.sector_id.value,
        encode_json(cast(JsonValue, list(membership.chain_ids))),
        membership.role.value,
        membership.valid_from,
        membership.valid_to,
        membership.weight,
        membership.confidence,
        membership.source,
        membership.version,
    )


def _scope_values(scope: ResearchScopeDefinition) -> tuple[object, ...]:
    return (
        scope.scope_id,
        scope.scope_type.value,
        scope.parent_scope_id,
        scope.name,
        scope.valid_from,
        scope.valid_to,
        scope.version,
    )


def _benchmark_values(mapping: SectorBenchmarkMapping) -> tuple[object, ...]:
    return (
        mapping.sector_id.value,
        encode_json(cast(JsonValue, [str(item) for item in mapping.benchmark_ids])),
        mapping.status.value,
        mapping.source,
        mapping.valid_from,
        mapping.valid_to,
        mapping.version,
    )


def _universe_values(snapshot: SectorUniverseSnapshot) -> tuple[object, ...]:
    return (
        snapshot.snapshot_id,
        snapshot.sector_id.value,
        snapshot.as_of,
        encode_json(cast(JsonValue, [str(item) for item in snapshot.asset_ids])),
        encode_json(cast(JsonValue, [str(item) for item in snapshot.benchmark_ids])),
        snapshot.membership_version,
        snapshot.source,
        encode_json(cast(JsonValue, snapshot.coverage.model_dump(mode="json"))),
        snapshot.quality.value,
    )


def _research_values(snapshot: SectorResearchSnapshot) -> tuple[object, ...]:
    return (
        snapshot.snapshot_id,
        snapshot.sector_id.value,
        snapshot.as_of,
        encode_json(cast(JsonValue, snapshot.market_state.model_dump(mode="json"))),
        encode_json(cast(JsonValue, snapshot.breadth_state.model_dump(mode="json"))),
        encode_json(
            cast(JsonValue, snapshot.fundamental_state.model_dump(mode="json"))
        ),
        encode_json(cast(JsonValue, snapshot.valuation_state.model_dump(mode="json"))),
        encode_json(cast(JsonValue, snapshot.coverage.model_dump(mode="json"))),
        encode_json(cast(JsonValue, list(snapshot.source_ids))),
        snapshot.feature_version,
        snapshot.status.value,
    )


def _macro_values(snapshot: SectorMacroSnapshot) -> tuple[object, ...]:
    return (
        snapshot.snapshot_id,
        snapshot.sector_id.value,
        snapshot.as_of,
        encode_json(cast(JsonValue, snapshot.cycle_state.model_dump(mode="json"))),
        encode_json(
            cast(JsonValue, snapshot.macro_sensitivity.model_dump(mode="json"))
        ),
        snapshot.source_sector_snapshot_id,
        snapshot.feature_version,
        snapshot.status.value,
    )


def _anomaly_values(event: SectorAnomalyEvent) -> tuple[object, ...]:
    return (
        event.event_id,
        event.event_type.value,
        event.sector_id.value,
        encode_json(cast(JsonValue, list(event.chain_ids))),
        encode_json(cast(JsonValue, [str(item) for item in event.source_asset_ids])),
        encode_json(cast(JsonValue, [str(item) for item in event.affected_asset_ids])),
        event.direction.value,
        event.severity.value,
        event.confidence,
        _utc_naive(event.event_time),
        _utc_naive(event.published_at),
        _utc_naive(event.available_at),
        _utc_naive(event.ingested_at),
        _utc_naive(event.as_of),
        encode_json(cast(JsonValue, list(event.source_evidence_ids))),
        event.summary,
        event.propagation_hypothesis,
        event.status.value,
        event.version,
    )


def _membership_from_row(row: tuple[object, ...]) -> SectorMembership:
    values = dict(zip(_MEMBERSHIP_COLUMNS, row, strict=True))
    decoded = decode_json_value(values.pop("chain_ids_json"))
    if not isinstance(decoded, list) or not all(
        isinstance(item, str) for item in decoded
    ):
        raise RepositoryError("stored membership chain IDs are invalid")
    values["chain_ids"] = decoded
    try:
        return SectorMembership.model_validate(values)
    except ValidationError as exc:
        raise RepositoryError("stored Sector membership is invalid") from exc


def _benchmark_from_row(row: tuple[object, ...]) -> SectorBenchmarkMapping:
    values = dict(zip(_BENCHMARK_COLUMNS, row, strict=True))
    values["benchmark_ids"] = _decode_string_list(
        values.pop("benchmark_ids_json"), "benchmark IDs"
    )
    try:
        return SectorBenchmarkMapping.model_validate(values)
    except ValidationError as exc:
        raise RepositoryError("stored Sector benchmark mapping is invalid") from exc


def _universe_from_row(row: tuple[object, ...]) -> SectorUniverseSnapshot:
    values = dict(zip(_UNIVERSE_COLUMNS, row, strict=True))
    values["asset_ids"] = _decode_string_list(
        values.pop("asset_ids_json"), "universe asset IDs"
    )
    values["benchmark_ids"] = _decode_string_list(
        values.pop("benchmark_ids_json"), "universe benchmark IDs"
    )
    coverage = decode_json_value(values.pop("coverage_json"))
    if not isinstance(coverage, dict):
        raise RepositoryError("stored Sector universe coverage is invalid")
    values["coverage"] = coverage
    try:
        return SectorUniverseSnapshot.model_validate(values)
    except ValidationError as exc:
        raise RepositoryError("stored Sector universe snapshot is invalid") from exc


def _research_from_row(row: tuple[object, ...]) -> SectorResearchSnapshot:
    values = dict(zip(_RESEARCH_COLUMNS, row, strict=True))
    for stored_name, model_name in (
        ("market_state_json", "market_state"),
        ("breadth_state_json", "breadth_state"),
        ("fundamental_state_json", "fundamental_state"),
        ("valuation_state_json", "valuation_state"),
        ("coverage_json", "coverage"),
    ):
        decoded = decode_json_value(values.pop(stored_name))
        if not isinstance(decoded, dict):
            raise RepositoryError(f"stored Sector {model_name} is invalid")
        values[model_name] = decoded
    values["source_ids"] = _decode_string_list(
        values.pop("source_ids_json"), "Sector research source IDs"
    )
    try:
        return SectorResearchSnapshot.model_validate(values)
    except ValidationError as exc:
        raise RepositoryError("stored Sector research snapshot is invalid") from exc


def _macro_from_row(row: tuple[object, ...]) -> SectorMacroSnapshot:
    values = dict(zip(_MACRO_COLUMNS, row, strict=True))
    for stored_name, model_name in (
        ("cycle_state_json", "cycle_state"),
        ("macro_sensitivity_json", "macro_sensitivity"),
    ):
        decoded = decode_json_value(values.pop(stored_name))
        if not isinstance(decoded, dict):
            raise RepositoryError(f"stored Sector {model_name} is invalid")
        values[model_name] = decoded
    try:
        return SectorMacroSnapshot.model_validate(values)
    except ValidationError as exc:
        raise RepositoryError("stored Sector macro snapshot is invalid") from exc


def _anomaly_from_row(row: tuple[object, ...]) -> SectorAnomalyEvent:
    values = dict(zip(_ANOMALY_COLUMNS, row, strict=True))
    values["chain_ids"] = _decode_string_list(
        values.pop("chain_ids_json"), "anomaly chain IDs"
    )
    values["source_asset_ids"] = _decode_string_list(
        values.pop("source_asset_ids_json"), "anomaly source assets"
    )
    values["affected_asset_ids"] = _decode_string_list(
        values.pop("affected_asset_ids_json"), "anomaly affected assets"
    )
    values["source_evidence_ids"] = _decode_string_list(
        values.pop("source_evidence_ids_json"), "anomaly Evidence IDs"
    )
    for field in ("event_time", "published_at", "available_at", "ingested_at", "as_of"):
        value = values[field]
        if isinstance(value, datetime) and value.tzinfo is None:
            values[field] = value.replace(tzinfo=UTC)
    try:
        return SectorAnomalyEvent.model_validate(values)
    except ValidationError as exc:
        raise RepositoryError("stored Sector anomaly event is invalid") from exc


def _utc_naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def _decode_string_list(value: object, label: str) -> list[str]:
    decoded = decode_json_value(value)
    if not isinstance(decoded, list) or not all(
        isinstance(item, str) for item in decoded
    ):
        raise RepositoryError(f"stored {label} are invalid")
    return cast(list[str], decoded)


def _model_from_row[ModelT: BaseModel](
    model_type: type[ModelT],
    columns: tuple[str, ...],
    row: tuple[object, ...],
) -> ModelT:
    try:
        return model_type.model_validate(dict(zip(columns, row, strict=True)))
    except ValidationError as exc:
        raise RepositoryError("stored Sector ontology row is invalid") from exc
