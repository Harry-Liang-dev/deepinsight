"""Repositories for source metadata and normalized structured market data."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from src.models.identifiers import AssetId
from src.repositories.base import (
    BaseRepository,
    decode_json_object,
    encode_json,
    map_row,
)
from src.repositories.records import SourceRegistryRecord
from src.schemas.market_data import (
    CorporateEventRecord,
    EodBarRecord,
    FundamentalRecord,
    InstrumentRecord,
    MacroObservationRecord,
    NewsEvidenceRecord,
    SentimentEvidenceRecord,
    SentimentSnapshotRecord,
)

_INSTRUMENT_COLUMNS = (
    "asset_id",
    "market",
    "ticker",
    "exchange_code",
    "company_name",
    "company_name_en",
    "sector_l1",
    "sector_l2",
    "industry_code",
    "currency",
    "is_active",
    "source_primary",
    "source_secondary",
    "listed_date",
    "delisted_date",
)

_SOURCE_COLUMNS = (
    "source_id",
    "source_name",
    "market_scope",
    "source_type",
    "auth_mode",
    "base_url",
    "enabled",
    "notes",
    "created_at",
    "updated_at",
)

_EOD_COLUMNS = (
    "asset_id",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
    "turnover",
    "vwap",
    "feed_identity",
    "coverage_scope",
    "source_id",
    "ingestion_ts",
)

_FUNDAMENTAL_COLUMNS = (
    "asset_id",
    "fiscal_period_end",
    "report_type",
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "eps_basic",
    "total_assets",
    "current_assets",
    "total_liabilities",
    "current_liabilities",
    "total_debt",
    "shareholders_equity",
    "operating_cash_flow",
    "shares_outstanding",
    "free_cash_flow",
    "revenue_yoy",
    "net_income_yoy",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "roe",
    "roa",
    "debt_to_equity",
    "current_ratio",
    "eps_ttm",
    "book_value_per_share",
    "market_cap",
    "pe_ttm",
    "pb",
    "earnings_yield",
    "source_locator",
    "quality",
    "filing_url",
    "filing_date",
    "accepted_at",
    "source_id",
    "ingestion_ts",
)

_MACRO_COLUMNS = (
    "series_key",
    "region_code",
    "observation_date",
    "indicator_name",
    "value",
    "unit",
    "frequency",
    "realtime_start",
    "realtime_end",
    "source_locator",
    "source_id",
    "ingestion_ts",
)

_EVENT_COLUMNS = (
    "event_id",
    "asset_id",
    "market",
    "event_date",
    "event_type",
    "severity",
    "title",
    "summary",
    "source_document_id",
    "source_id",
    "tags_json",
    "impact_window_days",
    "has_document",
)

_SENTIMENT_SNAPSHOT_COLUMNS = (
    "asset_id",
    "as_of",
    "provider",
    "score",
    "label",
    "bullish_pct",
    "bearish_pct",
    "message_volume_score",
    "message_volume_label",
    "source_timestamp",
    "quality",
    "source_locator",
    "evidence_class",
    "ingestion_ts",
)

_SENTIMENT_EVIDENCE_COLUMNS = (
    "source",
    "message_id",
    "asset_id",
    "created_at",
    "text",
    "declared_sentiment",
    "source_locator",
    "evidence_class",
    "ingestion_ts",
)

_NEWS_COLUMNS = (
    "news_id",
    "asset_id",
    "headline",
    "summary",
    "content",
    "author",
    "created_at",
    "updated_at",
    "source_url",
    "provider",
    "original_source",
    "source_locator",
    "ingestion_ts",
)


class InstrumentRepository(BaseRepository):
    """Persist canonical security master records."""

    def upsert(self, record: InstrumentRecord) -> None:
        """Insert or replace the mutable fields of one instrument.

        Args:
            record: Validated canonical instrument.
        """

        values: tuple[object, ...] = (
            str(record.asset_id),
            record.market.value,
            record.ticker,
            record.exchange_code,
            record.company_name,
            record.company_name_en,
            record.sector_l1,
            record.sector_l2,
            record.industry_code,
            record.currency,
            record.is_active,
            record.source_primary,
            record.source_secondary,
            record.listed_date,
            record.delisted_date,
        )
        updates = ", ".join(
            f"{column} = excluded.{column}"
            for column in _INSTRUMENT_COLUMNS
            if column != "asset_id"
        )
        self._execute(
            f"""
            INSERT INTO instruments ({", ".join(_INSTRUMENT_COLUMNS)})
            VALUES ({_placeholders(_INSTRUMENT_COLUMNS)})
            ON CONFLICT (asset_id) DO UPDATE SET
                {updates},
                updated_at = now()
            """,
            values,
        )

    def get(self, asset_id: AssetId) -> InstrumentRecord | None:
        """Return one instrument by canonical identifier.

        Args:
            asset_id: Canonical security identifier.

        Returns:
            The matching instrument, or ``None``.
        """

        row = self._fetch_one(
            f"""
            SELECT {", ".join(_INSTRUMENT_COLUMNS)}
            FROM instruments
            WHERE asset_id = ?
            """,
            (str(asset_id),),
        )
        return (
            None if row is None else map_row(InstrumentRecord, _INSTRUMENT_COLUMNS, row)
        )


class SourceRegistryRepository(BaseRepository):
    """Persist source registration metadata without credentials."""

    def upsert(self, record: SourceRegistryRecord) -> None:
        """Insert or update one source registration.

        Args:
            record: Credential-free source metadata.
        """

        columns = _SOURCE_COLUMNS[:8]
        values: tuple[object, ...] = (
            record.source_id,
            record.source_name,
            record.market_scope.value,
            record.source_type,
            record.auth_mode,
            record.base_url,
            record.enabled,
            record.notes,
        )
        updates = ", ".join(
            f"{column} = excluded.{column}"
            for column in columns
            if column != "source_id"
        )
        self._execute(
            f"""
            INSERT INTO source_registry ({", ".join(columns)})
            VALUES ({_placeholders(columns)})
            ON CONFLICT (source_id) DO UPDATE SET
                {updates},
                updated_at = now()
            """,
            values,
        )

    def get(self, source_id: str) -> SourceRegistryRecord | None:
        """Return one source registration.

        Args:
            source_id: Stable source identifier.

        Returns:
            The matching registration, or ``None``.
        """

        row = self._fetch_one(
            f"""
            SELECT {", ".join(_SOURCE_COLUMNS)}
            FROM source_registry
            WHERE source_id = ?
            """,
            (source_id,),
        )
        return (
            None if row is None else map_row(SourceRegistryRecord, _SOURCE_COLUMNS, row)
        )


class MarketDataRepository(BaseRepository):
    """Persist normalized bars, fundamentals, macro data, and events."""

    def upsert_eod_bar(self, record: EodBarRecord) -> None:
        """Persist one normalized end-of-day bar.

        Args:
            record: Validated bar record.
        """

        self._upsert(
            "eod_bars",
            _EOD_COLUMNS,
            ("asset_id", "trade_date"),
            (
                str(record.asset_id),
                record.trade_date,
                record.open,
                record.high,
                record.low,
                record.close,
                record.adj_close,
                record.volume,
                record.turnover,
                record.vwap,
                record.feed_identity,
                record.coverage_scope,
                record.source_id,
                record.ingestion_ts,
            ),
        )

    def get_eod_bar(
        self,
        asset_id: AssetId,
        trade_date: date,
    ) -> EodBarRecord | None:
        """Return one end-of-day bar.

        Args:
            asset_id: Canonical security identifier.
            trade_date: Trading date.

        Returns:
            The matching bar, or ``None``.
        """

        row = self._select_one(
            "eod_bars",
            _EOD_COLUMNS,
            ("asset_id", "trade_date"),
            (str(asset_id), trade_date),
        )
        return None if row is None else map_row(EodBarRecord, _EOD_COLUMNS, row)

    def list_eod_bars(
        self,
        asset_id: AssetId,
        *,
        end_date: date,
        start_date: date | None = None,
        ingested_as_of: datetime | None = None,
        limit: int = 60,
    ) -> list[EodBarRecord]:
        """Return point-in-time bars in chronological order.

        Args:
            asset_id: Canonical security identifier.
            end_date: Inclusive latest trading date.
            start_date: Optional inclusive earliest trading date.
            ingested_as_of: Optional inclusive ingestion-time cutoff.
            limit: Maximum number of recent observations.

        Returns:
            At most ``limit`` normalized bars ordered oldest to newest.
        """

        if limit <= 0:
            raise ValueError("EOD bar limit must be positive")
        if start_date is not None and end_date < start_date:
            raise ValueError("EOD bar end_date cannot precede start_date")
        predicates = ["asset_id = ?", "trade_date <= ?"]
        parameters: list[object] = [str(asset_id), end_date]
        if start_date is not None:
            predicates.append("trade_date >= ?")
            parameters.append(start_date)
        if ingested_as_of is not None:
            predicates.append("ingestion_ts <= ?")
            parameters.append(_database_timestamp(ingested_as_of))
        parameters.append(limit)
        rows = self._fetch_all(
            f"""
            SELECT {", ".join(_EOD_COLUMNS)}
            FROM eod_bars
            WHERE {" AND ".join(predicates)}
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            parameters,
        )
        return [map_row(EodBarRecord, _EOD_COLUMNS, row) for row in reversed(rows)]

    def upsert_fundamental(self, record: FundamentalRecord) -> None:
        """Persist one normalized fundamental observation.

        Args:
            record: Validated fundamental record.
        """

        values = tuple(
            str(record.asset_id) if column == "asset_id" else getattr(record, column)
            for column in _FUNDAMENTAL_COLUMNS
        )
        self._upsert(
            "fundamentals",
            _FUNDAMENTAL_COLUMNS,
            ("asset_id", "fiscal_period_end", "report_type"),
            values,
        )

    def get_fundamental(
        self,
        asset_id: AssetId,
        fiscal_period_end: date,
        report_type: str,
    ) -> FundamentalRecord | None:
        """Return one fundamental observation.

        Args:
            asset_id: Canonical security identifier.
            fiscal_period_end: Fiscal period end date.
            report_type: Filing period category.

        Returns:
            The matching observation, or ``None``.
        """

        row = self._select_one(
            "fundamentals",
            _FUNDAMENTAL_COLUMNS,
            ("asset_id", "fiscal_period_end", "report_type"),
            (str(asset_id), fiscal_period_end, report_type),
        )
        return (
            None
            if row is None
            else map_row(FundamentalRecord, _FUNDAMENTAL_COLUMNS, row)
        )

    def list_fundamentals(
        self,
        asset_id: AssetId,
        *,
        end_date: date,
    ) -> list[FundamentalRecord]:
        """Return available fundamental observations through a report date.

        Args:
            asset_id: Canonical security identifier.
            end_date: Inclusive fiscal-period cutoff.

        Returns:
            Normalized observations in chronological order.
        """

        rows = self._fetch_all(
            f"""
            SELECT {", ".join(_FUNDAMENTAL_COLUMNS)}
            FROM fundamentals
            WHERE asset_id = ? AND fiscal_period_end <= ?
            ORDER BY fiscal_period_end, report_type
            """,
            (str(asset_id), end_date),
        )
        return [map_row(FundamentalRecord, _FUNDAMENTAL_COLUMNS, row) for row in rows]

    def upsert_macro_observation(self, record: MacroObservationRecord) -> None:
        """Persist one normalized macro observation.

        Args:
            record: Validated macro observation.
        """

        values = tuple(
            (
                record.region_code.value
                if column == "region_code"
                else getattr(record, column)
            )
            for column in _MACRO_COLUMNS
        )
        self._upsert(
            "macro_series",
            _MACRO_COLUMNS,
            ("series_key", "observation_date"),
            values,
        )
        if record.realtime_start is not None and record.realtime_end is not None:
            self._upsert(
                "macro_series_vintages",
                _MACRO_COLUMNS,
                (
                    "series_key",
                    "observation_date",
                    "realtime_start",
                    "realtime_end",
                ),
                values,
            )

    def upsert_macro_observations(
        self,
        records: Sequence[MacroObservationRecord],
    ) -> None:
        """Persist normalized macro history using bounded batch transactions."""

        rows = [self._macro_values(record) for record in records]
        self._upsert_many(
            "macro_series",
            _MACRO_COLUMNS,
            ("series_key", "observation_date"),
            rows,
        )
        vintage_rows = [
            values
            for record, values in zip(records, rows, strict=True)
            if record.realtime_start is not None and record.realtime_end is not None
        ]
        self._upsert_many(
            "macro_series_vintages",
            _MACRO_COLUMNS,
            ("series_key", "observation_date", "realtime_start", "realtime_end"),
            vintage_rows,
        )

    @staticmethod
    def _macro_values(record: MacroObservationRecord) -> tuple[object, ...]:
        return tuple(
            (
                record.region_code.value
                if column == "region_code"
                else getattr(record, column)
            )
            for column in _MACRO_COLUMNS
        )

    def get_macro_observation(
        self,
        series_key: str,
        observation_date: date,
    ) -> MacroObservationRecord | None:
        """Return one macro observation.

        Args:
            series_key: Stable series identifier.
            observation_date: Observation date.

        Returns:
            The matching observation, or ``None``.
        """

        row = self._select_one(
            "macro_series",
            _MACRO_COLUMNS,
            ("series_key", "observation_date"),
            (series_key, observation_date),
        )
        return (
            None
            if row is None
            else map_row(MacroObservationRecord, _MACRO_COLUMNS, row)
        )

    def list_macro_observations(
        self,
        series_keys: Sequence[str],
        *,
        end_date: date,
        as_of: datetime,
    ) -> list[MacroObservationRecord]:
        """Return the latest stored vintage known by the requested cutoff."""

        if not series_keys:
            return []
        placeholders = ", ".join("?" for _ in series_keys)
        columns = _MACRO_COLUMNS
        rows = self._fetch_all(
            f"""
            SELECT {", ".join(columns)}
            FROM macro_series_vintages AS candidate
            WHERE series_key IN ({placeholders})
              AND observation_date <= ?
              AND realtime_start <= ?
              AND ingestion_ts <= ?
              AND realtime_start = (
                  SELECT max(newer.realtime_start)
                  FROM macro_series_vintages AS newer
                  WHERE newer.series_key = candidate.series_key
                    AND newer.observation_date = candidate.observation_date
                    AND newer.realtime_start <= ?
                    AND newer.ingestion_ts <= ?
              )
            ORDER BY series_key, observation_date
            """,
            (
                *series_keys,
                end_date,
                as_of.date(),
                _database_timestamp(as_of),
                as_of.date(),
                _database_timestamp(as_of),
            ),
        )
        return [map_row(MacroObservationRecord, columns, row) for row in rows]

    def upsert_sentiment_snapshot(self, record: SentimentSnapshotRecord) -> None:
        """Idempotently persist one community sentiment observation."""

        values = tuple(
            str(record.asset_id) if column == "asset_id" else getattr(record, column)
            for column in _SENTIMENT_SNAPSHOT_COLUMNS
        )
        self._upsert(
            "sentiment_snapshots",
            _SENTIMENT_SNAPSHOT_COLUMNS,
            ("asset_id", "source_timestamp", "provider"),
            values,
        )

    def list_sentiment_snapshots(
        self,
        asset_id: AssetId,
        *,
        start_at: datetime,
        as_of: datetime,
    ) -> list[SentimentSnapshotRecord]:
        """Return point-in-time community sentiment history."""

        rows = self._fetch_all(
            f"""
            SELECT {", ".join(_SENTIMENT_SNAPSHOT_COLUMNS)}
            FROM sentiment_snapshots
            WHERE asset_id = ?
              AND source_timestamp >= ?
              AND source_timestamp <= ?
              AND ingestion_ts <= ?
            ORDER BY source_timestamp, provider
            """,
            (
                str(asset_id),
                _database_timestamp(start_at),
                _database_timestamp(as_of),
                _database_timestamp(as_of),
            ),
        )
        return [
            map_row(SentimentSnapshotRecord, _SENTIMENT_SNAPSHOT_COLUMNS, row)
            for row in rows
        ]

    def upsert_sentiment_evidence(self, record: SentimentEvidenceRecord) -> None:
        """Idempotently persist one attributable community message."""

        values = tuple(
            str(record.asset_id) if column == "asset_id" else getattr(record, column)
            for column in _SENTIMENT_EVIDENCE_COLUMNS
        )
        self._upsert(
            "sentiment_evidence",
            _SENTIMENT_EVIDENCE_COLUMNS,
            ("source", "message_id"),
            values,
        )

    def list_sentiment_evidence(
        self,
        asset_id: AssetId,
        *,
        start_at: datetime,
        as_of: datetime,
    ) -> list[SentimentEvidenceRecord]:
        """Return attributable posts created and ingested by the cutoff."""

        rows = self._fetch_all(
            f"""
            SELECT {", ".join(_SENTIMENT_EVIDENCE_COLUMNS)}
            FROM sentiment_evidence
            WHERE asset_id = ?
              AND created_at >= ?
              AND created_at <= ?
              AND ingestion_ts <= ?
            ORDER BY created_at, message_id
            """,
            (
                str(asset_id),
                _database_timestamp(start_at),
                _database_timestamp(as_of),
                _database_timestamp(as_of),
            ),
        )
        return [
            map_row(SentimentEvidenceRecord, _SENTIMENT_EVIDENCE_COLUMNS, row)
            for row in rows
        ]

    def upsert_news_evidence(self, record: NewsEvidenceRecord) -> None:
        """Idempotently persist canonical news attribution metadata."""

        values = tuple(
            str(record.asset_id) if column == "asset_id" else getattr(record, column)
            for column in _NEWS_COLUMNS
        )
        self._upsert("news_evidence", _NEWS_COLUMNS, ("news_id",), values)

    def list_news_evidence(
        self,
        asset_id: AssetId,
        *,
        start_at: datetime,
        as_of: datetime,
    ) -> list[NewsEvidenceRecord]:
        """Return publication-time-safe canonical news records."""

        rows = self._fetch_all(
            f"""
            SELECT {", ".join(_NEWS_COLUMNS)}
            FROM news_evidence
            WHERE asset_id = ?
              AND created_at >= ?
              AND created_at <= ?
              AND ingestion_ts <= ?
            ORDER BY created_at, news_id
            """,
            (
                str(asset_id),
                _database_timestamp(start_at),
                _database_timestamp(as_of),
                _database_timestamp(as_of),
            ),
        )
        return [map_row(NewsEvidenceRecord, _NEWS_COLUMNS, row) for row in rows]

    def upsert_corporate_event(self, record: CorporateEventRecord) -> None:
        """Persist one normalized corporate event.

        Args:
            record: Validated corporate event.
        """

        self._upsert(
            "corporate_events",
            _EVENT_COLUMNS,
            ("event_id",),
            (
                record.event_id,
                None if record.asset_id is None else str(record.asset_id),
                record.market.value,
                record.event_date,
                record.event_type,
                record.severity.value,
                record.title,
                record.summary,
                record.source_document_id,
                record.source_id,
                None if record.tags_json is None else encode_json(record.tags_json),
                record.impact_window_days,
                record.has_document,
            ),
        )

    def get_corporate_event(self, event_id: str) -> CorporateEventRecord | None:
        """Return one corporate event.

        Args:
            event_id: Stable event identifier.

        Returns:
            The matching event, or ``None``.
        """

        row = self._select_one(
            "corporate_events",
            _EVENT_COLUMNS,
            ("event_id",),
            (event_id,),
        )
        if row is None:
            return None
        values = dict(zip(_EVENT_COLUMNS, row, strict=True))
        if values["tags_json"] is not None:
            values["tags_json"] = decode_json_object(values["tags_json"])
        return CorporateEventRecord.model_validate(values)

    def list_corporate_events(
        self,
        asset_id: AssetId,
        *,
        start_at: datetime,
        as_of: datetime,
    ) -> list[CorporateEventRecord]:
        """Return point-in-time asset event candidates in chronological order."""

        rows = self._fetch_all(
            f"""
            SELECT {", ".join(_EVENT_COLUMNS)}
            FROM corporate_events
            WHERE asset_id = ? AND event_date >= ? AND event_date <= ?
            ORDER BY event_date, event_id
            """,
            (
                str(asset_id),
                _database_timestamp(start_at),
                _database_timestamp(as_of),
            ),
        )
        records: list[CorporateEventRecord] = []
        for row in rows:
            values = dict(zip(_EVENT_COLUMNS, row, strict=True))
            if values["tags_json"] is not None:
                values["tags_json"] = decode_json_object(values["tags_json"])
            records.append(CorporateEventRecord.model_validate(values))
        return records

    def _upsert(
        self,
        table: str,
        columns: Sequence[str],
        key_columns: Sequence[str],
        values: Sequence[object],
    ) -> None:
        update_columns = tuple(
            column for column in columns if column not in key_columns
        )
        updates = ", ".join(
            f"{column} = excluded.{column}" for column in update_columns
        )
        self._execute(
            f"""
            INSERT INTO {table} ({", ".join(columns)})
            VALUES ({_placeholders(columns)})
            ON CONFLICT ({", ".join(key_columns)}) DO UPDATE SET {updates}
            """,
            values,
        )

    def _upsert_many(
        self,
        table: str,
        columns: Sequence[str],
        key_columns: Sequence[str],
        rows: Sequence[Sequence[object]],
    ) -> None:
        update_columns = tuple(
            column for column in columns if column not in key_columns
        )
        updates = ", ".join(
            f"{column} = excluded.{column}" for column in update_columns
        )
        self._executemany(
            f"""
            INSERT INTO {table} ({", ".join(columns)})
            VALUES ({_placeholders(columns)})
            ON CONFLICT ({", ".join(key_columns)}) DO UPDATE SET {updates}
            """,
            rows,
        )

    def _select_one(
        self,
        table: str,
        columns: Sequence[str],
        key_columns: Sequence[str],
        values: Sequence[object],
    ) -> tuple[object, ...] | None:
        where_clause = " AND ".join(f"{column} = ?" for column in key_columns)
        return self._fetch_one(
            f"""
            SELECT {", ".join(columns)}
            FROM {table}
            WHERE {where_clause}
            """,
            values,
        )


def _placeholders(columns: Sequence[str]) -> str:
    return ", ".join("?" for _ in columns)


def _database_timestamp(value: datetime) -> datetime:
    """Match DuckDB's timezone-naive local ``TIMESTAMP`` representation."""

    if value.tzinfo is None or value.utcoffset() is None:
        return value
    return value.astimezone().replace(tzinfo=None)
