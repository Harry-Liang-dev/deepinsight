"""Repositories for source metadata and normalized structured market data."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

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
    "total_liabilities",
    "shareholders_equity",
    "operating_cash_flow",
    "free_cash_flow",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "roe",
    "roa",
    "debt_to_equity",
    "current_ratio",
    "pe_ttm",
    "pb",
    "filing_url",
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
        limit: int = 60,
    ) -> list[EodBarRecord]:
        """Return recent bars in chronological order for feature computation.

        Args:
            asset_id: Canonical security identifier.
            end_date: Inclusive latest trading date.
            limit: Maximum number of recent observations.

        Returns:
            At most ``limit`` normalized bars ordered oldest to newest.
        """

        if limit <= 0:
            raise ValueError("EOD bar limit must be positive")
        rows = self._fetch_all(
            f"""
            SELECT {", ".join(_EOD_COLUMNS)}
            FROM eod_bars
            WHERE asset_id = ? AND trade_date <= ?
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            (str(asset_id), end_date, limit),
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
