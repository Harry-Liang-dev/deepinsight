"""Raw and normalized multi-market data records."""

from __future__ import annotations

from datetime import date, datetime
from typing import Self

from pydantic import Field, model_validator

from src.models.enums import EventSeverity, Market, MarketScope
from src.models.identifiers import AssetId
from src.models.types import DomainModel, JsonObject


class RawDataRecord(DomainModel):
    """Provider payload before field-level normalization."""

    source_id: str = Field(min_length=1)
    market_scope: MarketScope
    object_type: str = Field(min_length=1)
    payload: JsonObject
    received_at: datetime
    source_record_id: str | None = None


class InstrumentRecord(DomainModel):
    """Canonical security master record."""

    asset_id: AssetId
    market: Market
    ticker: str = Field(min_length=1)
    exchange_code: str = Field(min_length=1)
    company_name: str | None = None
    company_name_en: str | None = None
    sector_l1: str | None = None
    sector_l2: str | None = None
    industry_code: str | None = None
    currency: str | None = None
    is_active: bool = True
    source_primary: str = Field(min_length=1)
    source_secondary: str | None = None
    listed_date: date | None = None
    delisted_date: date | None = None
    p2_factor_universe: str | None = None
    p2_strategy_bucket: str | None = None
    p2_router_group: str | None = None

    @model_validator(mode="after")
    def validate_identity_and_dates(self) -> Self:
        """Validate market identity and optional listing date order."""

        if self.asset_id.market is not self.market:
            raise ValueError("asset_id market does not match market")
        if (
            self.listed_date is not None
            and self.delisted_date is not None
            and self.delisted_date < self.listed_date
        ):
            raise ValueError("delisted_date cannot precede listed_date")
        return self


class EodBarRecord(DomainModel):
    """Normalized end-of-day market bar."""

    asset_id: AssetId
    trade_date: date
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    adj_close: float | None = None
    volume: float | None = None
    turnover: float | None = None
    vwap: float | None = None
    source_id: str = Field(min_length=1)
    ingestion_ts: datetime
    p2_feature_blob_json: JsonObject | None = None


class FundamentalRecord(DomainModel):
    """Normalized issuer fundamental observation."""

    asset_id: AssetId
    fiscal_period_end: date
    report_type: str = Field(min_length=1)
    revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    eps_basic: float | None = None
    total_assets: float | None = None
    total_liabilities: float | None = None
    shareholders_equity: float | None = None
    operating_cash_flow: float | None = None
    free_cash_flow: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    roe: float | None = None
    roa: float | None = None
    debt_to_equity: float | None = None
    current_ratio: float | None = None
    pe_ttm: float | None = None
    pb: float | None = None
    filing_url: str | None = None
    source_id: str = Field(min_length=1)
    ingestion_ts: datetime
    p2_factor_blob_json: JsonObject | None = None


class MacroObservationRecord(DomainModel):
    """Normalized macroeconomic series observation."""

    series_key: str = Field(min_length=1)
    region_code: MarketScope
    observation_date: date
    indicator_name: str = Field(min_length=1)
    value: float | None = None
    unit: str | None = None
    frequency: str | None = None
    realtime_start: date | None = None
    realtime_end: date | None = None
    source_id: str = Field(min_length=1)
    ingestion_ts: datetime
    p2_regime_feature_json: JsonObject | None = None


class CorporateEventRecord(DomainModel):
    """Normalized issuer or market event."""

    event_id: str = Field(min_length=1)
    asset_id: AssetId | None = None
    market: Market
    event_date: datetime
    event_type: str = Field(min_length=1)
    severity: EventSeverity
    title: str = Field(min_length=1)
    summary: str | None = None
    source_document_id: str | None = None
    source_id: str = Field(min_length=1)
    tags_json: JsonObject | None = None
    impact_window_days: int | None = Field(default=None, ge=0)
    has_document: bool = False
    p2_label_json: JsonObject | None = None

    @model_validator(mode="after")
    def validate_asset_market(self) -> Self:
        """Ensure an optional asset belongs to the declared market."""

        if self.asset_id is not None and self.asset_id.market is not self.market:
            raise ValueError("asset_id market does not match event market")
        return self
