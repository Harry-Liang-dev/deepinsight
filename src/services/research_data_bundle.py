"""Build point-in-time structured research bundles from normalized records."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime, time
from typing import Final

import pandas as pd  # type: ignore[import-untyped]

from src.models.identifiers import AssetId
from src.operators import (
    FundamentalFeatureOperator,
    MarketContextOperator,
    TechnicalFeatureOperator,
    ValuationOperator,
)
from src.repositories import (
    DocumentRepository,
    InstrumentRepository,
    MarketDataRepository,
)
from src.schemas.documents import TextDocumentRecord
from src.schemas.market_data import (
    EodBarRecord,
    FundamentalRecord,
    InstrumentRecord,
    MacroObservationRecord,
    NewsEvidenceRecord,
    SentimentEvidenceRecord,
    SentimentSnapshotRecord,
)
from src.schemas.research_data import (
    DataAvailabilityStatus,
    DataCapability,
    DataFreshness,
    DataQuality,
    DataQualityStatus,
    DataSourceReference,
    FreshnessStatus,
    MetricCrossCheck,
    MissingData,
    MissingDataReason,
    ResearchDataBundle,
    ResearchDataBundleRequest,
    ResearchDataSection,
    ResearchEvidenceItem,
)
from src.schemas.temporal import TemporalAccessMode
from src.temporal_mapping import temporal_metadata_for

_FUNDAMENTAL_UNITS: Final[dict[str, tuple[str, str | None]]] = {
    "revenue": ("USD", "USD"),
    "gross_profit": ("USD", "USD"),
    "operating_income": ("USD", "USD"),
    "net_income": ("USD", "USD"),
    "eps_basic": ("USD/share", "USD"),
    "total_assets": ("USD", "USD"),
    "current_assets": ("USD", "USD"),
    "total_liabilities": ("USD", "USD"),
    "current_liabilities": ("USD", "USD"),
    "total_debt": ("USD", "USD"),
    "shareholders_equity": ("USD", "USD"),
    "operating_cash_flow": ("USD", "USD"),
    "shares_outstanding": ("shares", None),
    "revenue_yoy": ("ratio", None),
    "net_income_yoy": ("ratio", None),
    "gross_margin": ("ratio", None),
    "operating_margin": ("ratio", None),
    "net_margin": ("ratio", None),
    "roe": ("ratio", None),
    "roa": ("ratio", None),
    "debt_to_equity": ("ratio", None),
    "current_ratio": ("ratio", None),
    "eps_ttm": ("USD/share", "USD"),
    "book_value_per_share": ("USD/share", "USD"),
    "market_cap": ("USD", "USD"),
    "pe_ttm": ("ratio", None),
    "pb": ("ratio", None),
    "earnings_yield": ("ratio", None),
}

_STANDARDIZED_FUNDAMENTAL_FIELDS: Final[tuple[str, ...]] = (
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
)
_FMP_PROVIDER: Final[str] = "financial_modeling_prep"

_OHLCV_FIELDS: Final[tuple[str, ...]] = (
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
    "turnover",
    "vwap",
)
_OHLCV_METADATA_FIELDS: Final[tuple[str, ...]] = ("feed_identity", "coverage_scope")
_REQUIRED_OHLCV_FIELDS: Final[frozenset[str]] = frozenset(
    {"open", "high", "low", "close", "volume"}
)
_TECHNICAL_FIELDS: Final[tuple[str, ...]] = (
    "close",
    "return_1d",
    "return_5d",
    "return_20d",
    "return_60d",
    "sma_20",
    "sma_60",
    "distance_to_sma20",
    "distance_to_sma60",
    "realized_vol_20d",
    "realized_vol_60d",
    "max_drawdown_60d",
    "rsi_14",
    "atr_14",
    "macd",
    "volume_ratio_20d",
    "relative_strength_vs_spy",
    "relative_strength_vs_qqq",
    "relative_strength_vs_xlk",
    "trend_label",
)
_ALPACA_BARS_URL: Final[str] = "https://data.alpaca.markets/v2/stocks/bars"
_TECHNICAL_TRANSFORMATION_VERSION: Final[str] = "1.0"
_FRED_SERIES: Final[tuple[str, ...]] = (
    "FEDFUNDS",
    "DGS2",
    "DGS10",
    "T10Y2Y",
    "CPIAUCSL",
    "PCEPILFE",
    "UNRATE",
    "PAYEMS",
    "GDP",
    "INDPRO",
    "VIXCLS",
    "BAMLH0A0HYM2",
)
_MACRO_SNAPSHOT_FIELDS: Final[dict[str, str]] = {
    "FEDFUNDS": "fed_funds",
    "DGS2": "yield_2y",
    "DGS10": "yield_10y",
    "T10Y2Y": "yield_spread_10y2y",
    "CPIAUCSL": "cpi",
    "PCEPILFE": "core_pce",
    "UNRATE": "unemployment",
    "PAYEMS": "payrolls",
    "GDP": "gdp",
    "INDPRO": "industrial_production",
    "VIXCLS": "vix",
    "BAMLH0A0HYM2": "high_yield_spread",
}
_MARKET_BENCHMARK: Final[AssetId] = AssetId("US:SPY")
_GROWTH_BENCHMARK: Final[AssetId] = AssetId("US:QQQ")
_SECTOR_BENCHMARK: Final[AssetId] = AssetId("US:XLK")


class ResearchDataBundleService:
    """Project normalized Repository data into one provider-independent bundle."""

    def __init__(
        self,
        *,
        instruments: InstrumentRepository,
        market_data: MarketDataRepository,
        fundamental_max_age_days: int = 150,
        eod_max_age_days: int = 4,
        eod_history_limit: int = 400,
        technical_features: TechnicalFeatureOperator | None = None,
        fundamental_features: FundamentalFeatureOperator | None = None,
        documents: DocumentRepository | None = None,
        market_context: MarketContextOperator | None = None,
        valuation: ValuationOperator | None = None,
        temporal_access_mode: TemporalAccessMode = TemporalAccessMode.HISTORICAL_REPLAY,
    ) -> None:
        """Bind read-only normalized stores and a deterministic freshness SLA."""

        if fundamental_max_age_days <= 0:
            raise ValueError("fundamental maximum age must be positive")
        if eod_max_age_days <= 0:
            raise ValueError("EOD maximum age must be positive")
        if eod_history_limit < 60:
            raise ValueError("EOD history limit must be at least 60")
        self._instruments = instruments
        self._market_data = market_data
        self._fundamental_max_age_days = fundamental_max_age_days
        self._eod_max_age_days = eod_max_age_days
        self._eod_history_limit = eod_history_limit
        self._technical_features = technical_features or TechnicalFeatureOperator()
        self._fundamental_features = (
            fundamental_features or FundamentalFeatureOperator()
        )
        self._documents = documents
        self._market_context = market_context or MarketContextOperator()
        self._valuation = valuation or ValuationOperator()
        self._temporal_access_mode = temporal_access_mode

    def build(self, request: ResearchDataBundleRequest) -> ResearchDataBundle:
        """Build a serializable bundle without exposing persistence objects."""

        instrument = self._instruments.get(request.asset_id)
        asset_identity = self._asset_identity_section(request, instrument)
        requested = set(request.requested_capabilities)
        market_data_requested = bool(
            requested & {DataCapability.OHLCV, DataCapability.TECHNICAL_FEATURES}
        )
        bars = (
            self._market_data.list_eod_bars(
                request.asset_id,
                start_date=request.window_start,
                end_date=request.window_end,
                ingested_as_of=(
                    request.as_of
                    if self._temporal_access_mode
                    is TemporalAccessMode.HISTORICAL_REPLAY
                    else None
                ),
                limit=self._eod_history_limit,
            )
            if market_data_requested
            else []
        )
        ohlcv = (
            self._ohlcv_section(request, bars, instrument)
            if DataCapability.OHLCV in requested
            else self._unavailable_section(
                request,
                DataCapability.OHLCV,
                requested=False,
            )
        )
        technical_features = (
            self._technical_section(request, bars, instrument)
            if DataCapability.TECHNICAL_FEATURES in requested
            else self._unavailable_section(
                request,
                DataCapability.TECHNICAL_FEATURES,
                requested=False,
            )
        )
        fundamentals = (
            self._fundamental_section(request)
            if DataCapability.FUNDAMENTALS in requested
            else self._unavailable_section(
                request,
                DataCapability.FUNDAMENTALS,
                requested=False,
            )
        )
        section_builders: dict[DataCapability, Callable[[], ResearchDataSection]] = {
            DataCapability.VALUATION: lambda: self._valuation_section(request, bars),
            DataCapability.MARKET_CONTEXT: lambda: self._relative_context_section(
                request,
                capability=DataCapability.MARKET_CONTEXT,
            ),
            DataCapability.INDUSTRY_SECTOR_CONTEXT: lambda: (
                self._relative_context_section(
                    request,
                    capability=DataCapability.INDUSTRY_SECTOR_CONTEXT,
                )
            ),
            DataCapability.MACRO_INDICATORS: lambda: self._macro_section(request),
            DataCapability.NEWS_EVIDENCE: lambda: self._news_section(request),
            DataCapability.SENTIMENT_EVIDENCE: lambda: self._sentiment_section(request),
            DataCapability.CORPORATE_EVENTS: lambda: self._event_section(request),
            DataCapability.FILINGS: lambda: self._filings_section(request),
        }
        extras = {
            capability: (
                builder()
                if capability in requested
                else self._unavailable_section(
                    request,
                    capability,
                    requested=False,
                )
            )
            for capability, builder in section_builders.items()
        }
        fingerprint = _bundle_fingerprint(
            request,
            {
                DataCapability.ASSET_IDENTITY: asset_identity,
                DataCapability.OHLCV: ohlcv,
                DataCapability.TECHNICAL_FEATURES: technical_features,
                DataCapability.FUNDAMENTALS: fundamentals,
                **extras,
            },
        )
        return ResearchDataBundle(
            bundle_id=f"rdb_{fingerprint[:24]}",
            input_fingerprint=fingerprint,
            asset_id=request.asset_id,
            as_of=request.as_of,
            window_start=request.window_start,
            window_end=request.window_end,
            dataset_version=request.dataset_version,
            snapshot_id=request.snapshot_id,
            asset_identity=asset_identity,
            market_context=extras[DataCapability.MARKET_CONTEXT],
            ohlcv=ohlcv,
            technical_features=technical_features,
            fundamentals=fundamentals,
            valuation=extras[DataCapability.VALUATION],
            corporate_events=extras[DataCapability.CORPORATE_EVENTS],
            filings=extras[DataCapability.FILINGS],
            macro_indicators=extras[DataCapability.MACRO_INDICATORS],
            industry_sector_context=extras[DataCapability.INDUSTRY_SECTOR_CONTEXT],
            news_evidence=extras[DataCapability.NEWS_EVIDENCE],
            sentiment_evidence=extras[DataCapability.SENTIMENT_EVIDENCE],
        )

    def _asset_identity_section(
        self,
        request: ResearchDataBundleRequest,
        instrument: InstrumentRecord | None,
    ) -> ResearchDataSection:
        if instrument is None:
            return self._unavailable_section(
                request,
                DataCapability.ASSET_IDENTITY,
                provider="instrument_registry",
            )
        fields: tuple[tuple[str, str | bool | None], ...] = (
            ("asset_id", str(instrument.asset_id)),
            ("market", instrument.market.value),
            ("ticker", instrument.ticker),
            ("exchange_code", instrument.exchange_code),
            ("company_name", instrument.company_name),
            ("currency", instrument.currency),
        )
        evidence = tuple(
            _identity_evidence(instrument, name, value, request.as_of)
            for name, value in fields
            if value is not None
        )
        missing = tuple(
            _missing_field(
                request,
                DataCapability.ASSET_IDENTITY,
                f"asset_identity.{name}",
                provider=instrument.source_primary,
                required=name in {"asset_id", "market", "ticker", "exchange_code"},
            )
            for name, value in fields
            if value is None
        )
        status = (
            DataAvailabilityStatus.PRESENT
            if not missing
            else DataAvailabilityStatus.PARTIAL
        )
        return ResearchDataSection(
            capability=DataCapability.ASSET_IDENTITY,
            status=status,
            as_of=request.as_of,
            freshness=DataFreshness(
                status=FreshnessStatus.NOT_APPLICABLE,
                evaluated_at=request.as_of,
                policy_name="static_instrument_identity",
                policy_version="1.0",
                reason="instrument identity has no periodic freshness SLA",
            ),
            quality=_evaluated_quality(
                evidence,
                requested=len(fields),
                status=(
                    DataQualityStatus.PASS if not missing else DataQualityStatus.WARNING
                ),
            ),
            requested_field_count=len(fields),
            available_field_count=len({item.field_path for item in evidence}),
            items=evidence,
            missing_data=missing,
        )

    def _ohlcv_section(
        self,
        request: ResearchDataBundleRequest,
        bars: list[EodBarRecord],
        instrument: InstrumentRecord | None,
    ) -> ResearchDataSection:
        """Build attributable point-in-time daily-bar Evidence."""

        provider = _market_data_provider(request)
        if not bars:
            missing = tuple(
                _missing_field(
                    request,
                    DataCapability.OHLCV,
                    f"ohlcv.{field_name}",
                    provider=provider,
                    required=field_name in _REQUIRED_OHLCV_FIELDS,
                )
                for field_name in (*_OHLCV_FIELDS, *_OHLCV_METADATA_FIELDS)
            )
            return self._unavailable_section(
                request,
                DataCapability.OHLCV,
                provider=provider,
                requested_fields=len(_OHLCV_FIELDS) + len(_OHLCV_METADATA_FIELDS),
                missing=missing,
            )

        currency = None if instrument is None else instrument.currency
        evidence = tuple(
            sorted(
                [
                    _bar_evidence(
                        bar,
                        field_name,
                        currency,
                        temporal_access_mode=self._temporal_access_mode,
                    )
                    for bar in bars
                    for field_name in _OHLCV_FIELDS
                    if getattr(bar, field_name) is not None
                ]
                + [
                    _bar_metadata_evidence(
                        bars[-1],
                        field_name,
                        temporal_access_mode=self._temporal_access_mode,
                    )
                    for field_name in _OHLCV_METADATA_FIELDS
                    if getattr(bars[-1], field_name) is not None
                ],
                key=lambda item: (item.effective_at, item.field_path),
            )
        )
        field_counts = {
            field_name: sum(
                item.field_path == f"ohlcv.{field_name}" for item in evidence
            )
            for field_name in _OHLCV_FIELDS
        }
        metadata_available = {
            field_name
            for field_name in _OHLCV_METADATA_FIELDS
            if any(item.field_path == f"ohlcv.{field_name}" for item in evidence)
        }
        missing = tuple(
            _partial_bar_field(
                request,
                field_name,
                provider_names=tuple(sorted({bar.source_id for bar in bars})),
                available_count=field_counts[field_name],
                observation_count=len(bars),
                required=field_name in _REQUIRED_OHLCV_FIELDS,
            )
            for field_name in _OHLCV_FIELDS
            if field_counts[field_name] < len(bars)
        ) + tuple(
            _missing_field(
                request,
                DataCapability.OHLCV,
                f"ohlcv.{field_name}",
                provider=provider,
                required=True,
            )
            for field_name in _OHLCV_METADATA_FIELDS
            if field_name not in metadata_available
        )
        latest_date = max(bar.trade_date for bar in bars)
        age_days = max((request.as_of.date() - latest_date).days, 0)
        freshness_status = (
            FreshnessStatus.FRESH
            if age_days <= self._eod_max_age_days
            else FreshnessStatus.STALE
        )
        if freshness_status is FreshnessStatus.STALE:
            section_status = DataAvailabilityStatus.STALE
        elif missing:
            section_status = DataAvailabilityStatus.PARTIAL
        else:
            section_status = DataAvailabilityStatus.PRESENT
        quality_status = (
            DataQualityStatus.PASS
            if section_status is DataAvailabilityStatus.PRESENT
            else DataQualityStatus.WARNING
        )
        return ResearchDataSection(
            capability=DataCapability.OHLCV,
            status=section_status,
            as_of=request.as_of,
            freshness=_market_freshness(
                request,
                latest_date,
                age_days,
                self._eod_max_age_days,
            ),
            quality=_market_quality(
                evidence,
                requested_cells=(
                    len(bars) * len(_OHLCV_FIELDS) + len(_OHLCV_METADATA_FIELDS)
                ),
                window_start=request.window_start,
                window_end=request.window_end,
                observation_dates=[bar.trade_date for bar in bars],
                status=quality_status,
            ),
            requested_field_count=len(_OHLCV_FIELDS) + len(_OHLCV_METADATA_FIELDS),
            available_field_count=len({item.field_path for item in evidence}),
            items=evidence,
            missing_data=missing,
        )

    def _technical_section(
        self,
        request: ResearchDataBundleRequest,
        bars: list[EodBarRecord],
        instrument: InstrumentRecord | None,
    ) -> ResearchDataSection:
        """Build deterministic features with lineage to canonical close Evidence."""

        provider = _market_data_provider(request)
        if not bars:
            missing = tuple(
                _missing_technical_feature(request, name, provider, 0)
                for name in _TECHNICAL_FIELDS
            )
            return self._unavailable_section(
                request,
                DataCapability.TECHNICAL_FEATURES,
                provider=provider,
                requested_fields=len(_TECHNICAL_FIELDS),
                missing=missing,
            )

        currency = None if instrument is None else instrument.currency
        evidence_by_field_date = {
            (field_name, bar.trade_date): _bar_evidence(
                bar,
                field_name,
                currency,
                temporal_access_mode=self._temporal_access_mode,
            )
            for bar in bars
            for field_name in ("close", "high", "low", "volume")
            if getattr(bar, field_name) is not None
        }
        frame = pd.DataFrame(
            {
                "trade_date": bar.trade_date,
                "close": bar.close,
                "high": bar.high,
                "low": bar.low,
                "volume": bar.volume,
            }
            for bar in bars
        )
        values = dict(self._technical_features.compute(frame))
        benchmark_assets = {
            "relative_strength_vs_spy": _MARKET_BENCHMARK,
            "relative_strength_vs_qqq": _GROWTH_BENCHMARK,
            "relative_strength_vs_xlk": _SECTOR_BENCHMARK,
        }
        relative_parents: dict[str, tuple[ResearchEvidenceItem, ...]] = {}
        target_parents = tuple(
            evidence_by_field_date[("close", bar.trade_date)]
            for bar in bars[-21:]
            if ("close", bar.trade_date) in evidence_by_field_date
        )
        for field_name, benchmark_asset in benchmark_assets.items():
            benchmark_bars = self._market_data.list_eod_bars(
                benchmark_asset,
                start_date=request.window_start,
                end_date=request.window_end,
                ingested_as_of=(
                    request.as_of
                    if self._temporal_access_mode
                    is TemporalAccessMode.HISTORICAL_REPLAY
                    else None
                ),
                limit=self._eod_history_limit,
            )
            context = self._market_context.compute(
                {
                    str(request.asset_id): bars,
                    str(benchmark_asset): benchmark_bars,
                },
                target_asset=str(request.asset_id),
                market_benchmark=(
                    str(benchmark_asset)
                    if benchmark_asset == _MARKET_BENCHMARK
                    else "missing:market"
                ),
                growth_benchmark=(
                    str(benchmark_asset)
                    if benchmark_asset == _GROWTH_BENCHMARK
                    else "missing:growth"
                ),
                sector_benchmark=(
                    str(benchmark_asset)
                    if benchmark_asset == _SECTOR_BENCHMARK
                    else "missing:sector"
                ),
            )
            context_name = {
                "relative_strength_vs_spy": "relative_strength_market",
                "relative_strength_vs_qqq": "relative_strength_growth",
                "relative_strength_vs_xlk": "relative_strength_sector",
            }[field_name]
            values[field_name] = context.get(context_name)
            benchmark_parents = tuple(
                _bar_evidence(
                    bar,
                    "close",
                    currency,
                    temporal_access_mode=self._temporal_access_mode,
                )
                for bar in benchmark_bars[-21:]
                if bar.close is not None
            )
            relative_parents[field_name] = (*target_parents, *benchmark_parents)
        technical_items: dict[str, ResearchEvidenceItem] = {}
        all_evidence = {
            item.evidence_id: item for item in evidence_by_field_date.values()
        }
        all_evidence.update(
            {
                item.evidence_id: item
                for parents in relative_parents.values()
                for item in parents
            }
        )
        for field_name in _TECHNICAL_FIELDS:
            value = values.get(field_name)
            if not isinstance(value, str | int | float | bool):
                continue
            if field_name in relative_parents:
                parent_ids = tuple(
                    item.evidence_id for item in relative_parents[field_name]
                )
            else:
                parent_ids = _technical_parent_ids(
                    field_name,
                    bars,
                    evidence_by_field_date,
                    technical_items,
                )
            parents = tuple(all_evidence[parent_id] for parent_id in parent_ids)
            item = _technical_evidence(
                request.asset_id,
                bars[-1].trade_date,
                field_name,
                value,
                currency,
                parents,
            )
            technical_items[field_name] = item
            all_evidence[item.evidence_id] = item

        evidence = tuple(
            technical_items[name]
            for name in _TECHNICAL_FIELDS
            if name in technical_items
        )
        provider_names = tuple(sorted({bar.source_id for bar in bars}))
        missing = tuple(
            _missing_technical_feature(
                request,
                field_name,
                provider_names[0] if len(provider_names) == 1 else provider,
                len(bars),
            )
            for field_name in _TECHNICAL_FIELDS
            if field_name not in technical_items
        )
        latest_date = max(bar.trade_date for bar in bars)
        age_days = max((request.as_of.date() - latest_date).days, 0)
        is_stale = age_days > self._eod_max_age_days
        if not evidence:
            section_status = DataAvailabilityStatus.MISSING
            quality_status = DataQualityStatus.FAIL
        elif is_stale:
            section_status = DataAvailabilityStatus.STALE
            quality_status = DataQualityStatus.WARNING
        elif missing:
            section_status = DataAvailabilityStatus.PARTIAL
            quality_status = DataQualityStatus.WARNING
        else:
            section_status = DataAvailabilityStatus.PRESENT
            quality_status = DataQualityStatus.PASS
        return ResearchDataSection(
            capability=DataCapability.TECHNICAL_FEATURES,
            status=section_status,
            as_of=request.as_of,
            freshness=_market_freshness(
                request,
                latest_date,
                age_days,
                self._eod_max_age_days,
            ),
            quality=_market_quality(
                evidence,
                requested_cells=len(_TECHNICAL_FIELDS),
                window_start=request.window_start,
                window_end=request.window_end,
                observation_dates=[bar.trade_date for bar in bars],
                status=quality_status,
            ),
            requested_field_count=len(_TECHNICAL_FIELDS),
            available_field_count=len({item.field_path for item in evidence}),
            items=evidence,
            missing_data=missing,
        )

    def _fundamental_section(
        self,
        request: ResearchDataBundleRequest,
    ) -> ResearchDataSection:
        # Fiscal comparisons need historical periods outside the report/news
        # window; point-in-time availability, not window membership, is the gate.
        records = self._point_in_time_fundamentals(request)
        raw_evidence = tuple(
            sorted(
                (
                    _fundamental_evidence(
                        record,
                        field_name,
                        unit,
                        currency,
                        temporal_access_mode=self._temporal_access_mode,
                    )
                    for record in records
                    for field_name, (unit, currency) in _FUNDAMENTAL_UNITS.items()
                    if getattr(record, field_name) is not None
                ),
                key=lambda item: (item.effective_at, item.field_path, item.evidence_id),
            )
        )
        sec_records = [
            record for record in records if record.source_id != _FMP_PROVIDER
        ]
        frame = pd.DataFrame(record.model_dump(mode="python") for record in sec_records)
        derived: list[ResearchEvidenceItem] = []
        if sec_records:
            values = self._fundamental_features.compute(frame)
            parents_by_field: dict[str, tuple[str, ...]] = {
                "revenue_yoy": ("revenue",),
                "net_income_yoy": ("net_income",),
                "gross_margin": ("gross_profit", "revenue"),
                "operating_margin": ("operating_income", "revenue"),
                "net_margin": ("net_income", "revenue"),
                "roe": ("net_income", "shareholders_equity"),
                "roa": ("net_income", "total_assets"),
                "debt_to_equity": ("total_debt", "shareholders_equity"),
                "current_ratio": ("current_assets", "current_liabilities"),
            }
            for name, parent_fields in parents_by_field.items():
                value = values.get(name)
                if not isinstance(value, int | float):
                    continue
                parents = tuple(
                    item
                    for item in raw_evidence
                    if item.field_path.rsplit(".", maxsplit=1)[-1] in parent_fields
                )
                if not all(
                    any(
                        parent.field_path.endswith(f".{field_name}")
                        for parent in parents
                    )
                    for field_name in parent_fields
                ):
                    continue
                derived.append(
                    _derived_evidence(
                        request,
                        capability=DataCapability.FUNDAMENTALS,
                        field_name=name,
                        value=value,
                        parents=parents,
                        transformation="fundamental_features",
                        version=self._fundamental_features.version,
                        unit="ratio",
                    )
                )
        chosen_standardized = _choose_standardized_fundamentals(
            raw_evidence,
            tuple(derived),
        )
        evidence = (
            *tuple(
                item
                for item in raw_evidence
                if item.field_path.rsplit(".", maxsplit=1)[-1]
                not in _STANDARDIZED_FUNDAMENTAL_FIELDS
            ),
            *chosen_standardized,
        )
        requested_fields = tuple(_FUNDAMENTAL_UNITS)
        available_fields = {item.field_path for item in evidence}
        missing = tuple(
            _missing_field(
                request,
                DataCapability.FUNDAMENTALS,
                f"fundamentals.{field_name}",
                provider="financial_modeling_prep+sec_edgar",
                required=True,
            )
            for field_name in requested_fields
            if f"fundamentals.{field_name}" not in available_fields
        )
        if not evidence:
            return self._unavailable_section(
                request,
                DataCapability.FUNDAMENTALS,
                provider="financial_modeling_prep+sec_edgar",
                requested_fields=len(requested_fields),
                missing=missing,
            )

        latest_date = max(record.fiscal_period_end for record in records)
        age_days = max((request.as_of.date() - latest_date).days, 0)
        freshness_status = (
            FreshnessStatus.FRESH
            if age_days <= self._fundamental_max_age_days
            else FreshnessStatus.STALE
        )
        if freshness_status is FreshnessStatus.STALE:
            section_status = DataAvailabilityStatus.STALE
        elif missing:
            section_status = DataAvailabilityStatus.PARTIAL
        else:
            section_status = DataAvailabilityStatus.PRESENT
        quality_status = (
            DataQualityStatus.CONFLICT
            if any(item.quality is DataQualityStatus.CONFLICT for item in evidence)
            else (
                DataQualityStatus.PASS
                if section_status is DataAvailabilityStatus.PRESENT
                else DataQualityStatus.WARNING
            )
        )
        return ResearchDataSection(
            capability=DataCapability.FUNDAMENTALS,
            status=section_status,
            as_of=request.as_of,
            freshness=DataFreshness(
                status=freshness_status,
                evaluated_at=request.as_of,
                policy_name="us_quarterly_fundamentals",
                policy_version="1.0",
                latest_effective_at=datetime.combine(
                    latest_date,
                    time.min,
                    tzinfo=UTC,
                ),
                age_days=age_days,
                maximum_age_days=self._fundamental_max_age_days,
            ),
            quality=_evaluated_quality(
                evidence,
                requested=len(requested_fields),
                status=quality_status,
            ),
            requested_field_count=len(requested_fields),
            available_field_count=len(available_fields),
            items=evidence,
            missing_data=missing,
        )

    def _valuation_section(
        self,
        request: ResearchDataBundleRequest,
        bars: list[EodBarRecord],
    ) -> ResearchDataSection:
        records = self._point_in_time_fundamentals(request)
        values = self._valuation.compute(
            bars, [record for record in records if record.source_id != _FMP_PROVIDER]
        )
        close_parent = next(
            (
                _bar_evidence(
                    record,
                    "close",
                    "USD",
                    temporal_access_mode=self._temporal_access_mode,
                )
                for record in reversed(bars)
                if record.close is not None
            ),
            None,
        )
        fundamental_parents: dict[str, ResearchEvidenceItem] = {}
        for record in reversed(records):
            for name, (unit, currency) in _FUNDAMENTAL_UNITS.items():
                if name in fundamental_parents or getattr(record, name) is None:
                    continue
                fundamental_parents[name] = _fundamental_evidence(
                    record,
                    name,
                    unit,
                    currency,
                    temporal_access_mode=self._temporal_access_mode,
                )
        evidence: list[ResearchEvidenceItem] = []
        fmp_record = max(
            (record for record in records if record.source_id == _FMP_PROVIDER),
            key=lambda record: (record.fiscal_period_end, record.ingestion_ts),
            default=None,
        )
        valuation_names = (
            "market_cap",
            "eps_ttm",
            "book_value_per_share",
            "pe_ttm",
            "pb",
            "earnings_yield",
        )
        if fmp_record is not None:
            for name in valuation_names:
                if getattr(fmp_record, name) is None:
                    continue
                item = _fundamental_evidence(
                    fmp_record,
                    name,
                    _FUNDAMENTAL_UNITS[name][0],
                    _FUNDAMENTAL_UNITS[name][1],
                    temporal_access_mode=self._temporal_access_mode,
                )
                evidence.append(_repath_evidence(item, f"valuation.{name}"))
        direct_names = {
            item.field_path.rsplit(".", maxsplit=1)[-1] for item in evidence
        }
        for name, value in values.items():
            if name in direct_names or value is None or close_parent is None:
                continue
            parent_names = {
                "market_cap": ("shares_outstanding",),
                "eps_ttm": ("eps_basic",),
                "book_value_per_share": (
                    "shares_outstanding",
                    "shareholders_equity",
                ),
                "pe_ttm": ("eps_basic",),
                "pb": ("shares_outstanding", "shareholders_equity"),
                "earnings_yield": ("eps_basic",),
            }[name]
            parents = [close_parent]
            parents.extend(
                fundamental_parents[parent]
                for parent in parent_names
                if parent in fundamental_parents
            )
            if len(parents) != len(parent_names) + 1:
                continue
            evidence.append(
                _derived_evidence(
                    request,
                    capability=DataCapability.VALUATION,
                    field_name=name,
                    value=value,
                    parents=tuple(parents),
                    transformation="valuation",
                    version=self._valuation.version,
                    unit=(
                        "USD"
                        if name == "market_cap"
                        else (
                            "USD/share"
                            if name in {"eps_ttm", "book_value_per_share"}
                            else "ratio"
                        )
                    ),
                )
            )
        return self._simple_section(
            request,
            DataCapability.VALUATION,
            tuple(evidence),
            requested_fields=valuation_names,
            provider="financial_modeling_prep+sec_edgar+alpaca_market_data",
            maximum_age_days=self._fundamental_max_age_days,
        )

    def _relative_context_section(
        self,
        request: ResearchDataBundleRequest,
        *,
        capability: DataCapability,
    ) -> ResearchDataSection:
        asset_ids = (
            request.asset_id,
            _MARKET_BENCHMARK,
            _GROWTH_BENCHMARK,
            _SECTOR_BENCHMARK,
        )
        bars_by_asset = {
            str(asset_id): self._market_data.list_eod_bars(
                asset_id,
                start_date=request.window_start,
                end_date=request.window_end,
                ingested_as_of=(
                    request.as_of
                    if self._temporal_access_mode
                    is TemporalAccessMode.HISTORICAL_REPLAY
                    else None
                ),
                limit=self._eod_history_limit,
            )
            for asset_id in asset_ids
        }
        values = self._market_context.compute(
            bars_by_asset,
            target_asset=str(request.asset_id),
            market_benchmark=str(_MARKET_BENCHMARK),
            growth_benchmark=str(_GROWTH_BENCHMARK),
            sector_benchmark=str(_SECTOR_BENCHMARK),
        )
        fields = (
            {
                "asset_return_20d",
                "market_return_20d",
                "growth_return_20d",
                "excess_return_vs_market",
                "excess_return_vs_growth",
                "relative_strength_market",
                "relative_strength_growth",
                "benchmark_trend",
                "market_volatility",
            }
            if capability is DataCapability.MARKET_CONTEXT
            else {
                "sector_return_20d",
                "excess_return_vs_sector",
                "relative_strength_sector",
                "sector_volatility",
            }
        )
        parents = tuple(
            _bar_evidence(
                record,
                "close",
                "USD",
                temporal_access_mode=self._temporal_access_mode,
            )
            for records in bars_by_asset.values()
            for record in records
            if record.close is not None
        )
        evidence = tuple(
            _derived_evidence(
                request,
                capability=capability,
                field_name=name,
                value=value,
                parents=parents,
                transformation="benchmark_context",
                version=self._market_context.version,
                unit=None if isinstance(value, str) else "ratio",
            )
            for name, value in values.items()
            if name in fields and value is not None and parents
        )
        return self._simple_section(
            request,
            capability,
            evidence,
            requested_fields=tuple(sorted(fields)),
            provider="alpaca_market_data",
            maximum_age_days=self._eod_max_age_days,
        )

    def _macro_section(self, request: ResearchDataBundleRequest) -> ResearchDataSection:
        records = self._market_data.list_macro_observations(
            _FRED_SERIES,
            end_date=request.window_end,
            as_of=request.as_of,
            access_mode=self._temporal_access_mode,
        )
        latest_by_series = {
            series_key: max(
                (record for record in records if record.series_key == series_key),
                key=lambda record: (record.observation_date, record.ingestion_ts),
                default=None,
            )
            for series_key in _FRED_SERIES
        }
        raw_evidence = tuple(
            _record_evidence(
                subject_id="US",
                field_path=f"macro_indicators.{record.series_key}",
                effective_at=datetime.combine(
                    record.observation_date, time.min, tzinfo=UTC
                ),
                observed_at=_record_observed_at(
                    record,
                    record.ingestion_ts,
                    self._temporal_access_mode,
                ),
                value=record.value,
                unit=record.unit,
                provider=record.source_id,
                record_type="MacroObservationRecord",
                record_key=(
                    f"{record.series_key}|{record.observation_date.isoformat()}|"
                    f"{record.realtime_start}"
                ),
                locator=record.source_locator or f"fred:series:{record.series_key}",
            )
            for record in latest_by_series.values()
            if record is not None and record.value is not None
        )
        by_series = {
            item.field_path.rsplit(".", maxsplit=1)[-1]: item for item in raw_evidence
        }
        snapshot = tuple(
            _derived_evidence(
                request,
                capability=DataCapability.MACRO_INDICATORS,
                field_name=field_name,
                value=by_series[series_key].value,
                parents=(by_series[series_key],),
                transformation="macro_snapshot",
                version="macro_snapshot_v1",
                unit=by_series[series_key].unit,
            )
            for series_key, field_name in _MACRO_SNAPSHOT_FIELDS.items()
            if series_key in by_series
        )
        return self._simple_section(
            request,
            DataCapability.MACRO_INDICATORS,
            (*raw_evidence, *snapshot),
            requested_fields=tuple(_MACRO_SNAPSHOT_FIELDS.values()),
            provider="fred",
            maximum_age_days=100,
        )

    def _news_section(self, request: ResearchDataBundleRequest) -> ResearchDataSection:
        records = self._market_data.list_news_evidence(
            request.asset_id,
            start_at=datetime.combine(request.window_start, time.min, tzinfo=UTC),
            as_of=request.as_of,
            access_mode=self._temporal_access_mode,
        )
        evidence = tuple(
            _record_evidence(
                subject_id=str(request.asset_id),
                field_path=f"news_evidence.{field_name}",
                effective_at=_as_utc(record.created_at),
                observed_at=_record_observed_at(
                    record,
                    record.ingestion_ts,
                    self._temporal_access_mode,
                ),
                value=value,
                unit=None,
                provider=record.provider,
                record_type="NewsEvidenceRecord",
                record_key=record.news_id,
                locator=record.source_locator,
                source_url=record.source_url,
                authorization_class="authenticated_api",
                retention_class="attributed_news_evidence",
            )
            for record in records
            for field_name, value in (
                ("headline", record.headline),
                ("summary", record.summary),
                ("author", record.author),
                ("original_source", record.original_source),
            )
            if value is not None
        )
        return self._simple_section(
            request,
            DataCapability.NEWS_EVIDENCE,
            evidence,
            requested_fields=("headline", "summary", "original_source"),
            provider="alpaca_market_data",
            maximum_age_days=7,
        )

    def _sentiment_section(
        self, request: ResearchDataBundleRequest
    ) -> ResearchDataSection:
        start_at = datetime.combine(request.window_start, time.min, tzinfo=UTC)
        snapshots = self._market_data.list_sentiment_snapshots(
            request.asset_id,
            start_at=start_at,
            as_of=request.as_of,
            access_mode=self._temporal_access_mode,
        )
        messages = self._market_data.list_sentiment_evidence(
            request.asset_id,
            start_at=start_at,
            as_of=request.as_of,
            access_mode=self._temporal_access_mode,
        )
        evidence: list[ResearchEvidenceItem] = []
        for record in snapshots:
            for field_name in (
                "score",
                "label",
                "bullish_pct",
                "bearish_pct",
                "message_volume_score",
                "message_volume_label",
            ):
                value = getattr(record, field_name)
                if value is None:
                    continue
                evidence.append(
                    _record_evidence(
                        subject_id=str(request.asset_id),
                        field_path=f"sentiment_evidence.community_{field_name}",
                        effective_at=_as_utc(record.source_timestamp),
                        observed_at=_record_observed_at(
                            record,
                            record.ingestion_ts,
                            self._temporal_access_mode,
                        ),
                        value=value,
                        unit="score" if isinstance(value, int | float) else None,
                        provider=record.provider,
                        record_type="SentimentSnapshotRecord",
                        record_key=(
                            f"{record.asset_id}|{record.source_timestamp.isoformat()}"
                        ),
                        locator=record.source_locator,
                        authorization_class="mcp_public_data",
                        retention_class="community_sentiment_only",
                    )
                )
        for message in messages:
            evidence.append(
                _record_evidence(
                    subject_id=str(request.asset_id),
                    field_path="sentiment_evidence.community_message",
                    effective_at=_as_utc(message.created_at),
                    observed_at=_record_observed_at(
                        message,
                        message.ingestion_ts,
                        self._temporal_access_mode,
                    ),
                    value=message.text,
                    unit=None,
                    provider=message.source,
                    record_type="SentimentEvidenceRecord",
                    record_key=message.message_id,
                    locator=message.source_locator,
                    authorization_class="mcp_public_data",
                    retention_class="community_sentiment_only",
                )
            )
        if snapshots:
            ordered_snapshots = sorted(
                snapshots, key=lambda item: item.source_timestamp
            )
            snapshot_items = tuple(
                item
                for item in evidence
                if item.source.normalized_record_type == "SentimentSnapshotRecord"
            )
            message_items = tuple(
                item
                for item in evidence
                if item.source.normalized_record_type == "SentimentEvidenceRecord"
            )
            latest = ordered_snapshots[-1]
            first = ordered_snapshots[0]
            derived_values: dict[str, float | str | None] = {
                "sentiment_change": _difference_optional(latest.score, first.score),
                "attention_change": _difference_optional(
                    latest.message_volume_score, first.message_volume_score
                ),
                "dispersion": (
                    None
                    if latest.bullish_pct is None or latest.bearish_pct is None
                    else 1.0
                    - abs(float(latest.bullish_pct) - float(latest.bearish_pct)) / 100.0
                ),
                "dominant_topics": _dominant_community_topics(
                    tuple(message.text for message in messages)
                ),
            }
            for name, value in derived_values.items():
                parents = message_items if name == "dominant_topics" else snapshot_items
                if value is None or not parents:
                    continue
                evidence.append(
                    _derived_evidence(
                        request,
                        capability=DataCapability.SENTIMENT_EVIDENCE,
                        field_name=name,
                        value=value,
                        parents=parents,
                        transformation="sentiment_presentation",
                        version="sentiment_presentation_v1",
                        unit="ratio" if isinstance(value, float) else None,
                    )
                )
        return self._simple_section(
            request,
            DataCapability.SENTIMENT_EVIDENCE,
            tuple(evidence),
            requested_fields=(
                "community_score",
                "community_label",
                "community_message_volume_score",
            ),
            provider="stocktwits_mcp",
            maximum_age_days=2,
        )

    def _filings_section(
        self, request: ResearchDataBundleRequest
    ) -> ResearchDataSection:
        if self._documents is None:
            return self._unavailable_section(
                request,
                DataCapability.FILINGS,
                provider="document_repository_not_injected",
            )
        documents = [
            document
            for document in self._documents.list_documents(
                request.asset_id, end_date=request.window_end
            )
            if document.doc_type.value == "filing"
            and document.publish_ts is not None
            and _as_utc(document.publish_ts) <= request.as_of
        ]
        evidence = tuple(
            _record_evidence(
                subject_id=str(request.asset_id),
                field_path="filings.title",
                effective_at=_as_utc(document.publish_ts),
                observed_at=_record_observed_at(
                    document,
                    document.created_at,
                    self._temporal_access_mode,
                ),
                value=document.title,
                unit=None,
                provider=document.source_id,
                record_type="TextDocumentRecord",
                record_key=document.document_id,
                locator=(
                    str(document.metadata_json.get("provider_locator"))
                    if document.metadata_json
                    and document.metadata_json.get("provider_locator")
                    else document.source_url or document.document_id
                ),
                source_url=document.source_url,
            )
            for document in documents
            if document.publish_ts is not None
        )
        return self._simple_section(
            request,
            DataCapability.FILINGS,
            evidence,
            requested_fields=("title",),
            provider="sec_edgar",
            maximum_age_days=500,
        )

    def _event_section(self, request: ResearchDataBundleRequest) -> ResearchDataSection:
        records = self._market_data.list_corporate_events(
            request.asset_id,
            start_at=datetime.combine(request.window_start, time.min, tzinfo=UTC),
            as_of=request.as_of,
        )
        evidence = tuple(
            _record_evidence(
                subject_id=str(request.asset_id),
                field_path="corporate_events.title",
                effective_at=_as_utc(record.event_date),
                observed_at=_as_utc(record.event_date),
                value=record.title,
                unit=None,
                provider=record.source_id,
                record_type="CorporateEventRecord",
                record_key=record.event_id,
                locator=record.source_document_id or record.event_id,
            )
            for record in records
        )
        return self._simple_section(
            request,
            DataCapability.CORPORATE_EVENTS,
            evidence,
            requested_fields=("title",),
            provider="sec_edgar+alpaca_market_data",
            maximum_age_days=30,
        )

    def _point_in_time_fundamentals(
        self, request: ResearchDataBundleRequest
    ) -> list[FundamentalRecord]:
        return [
            record
            for record in self._market_data.list_fundamentals(
                request.asset_id, end_date=request.window_end
            )
            if (
                self._temporal_access_mode is TemporalAccessMode.LIVE_ACQUISITION
                or _as_utc(record.ingestion_ts) <= request.as_of
            )
            and (
                record.accepted_at is None
                or _as_utc(record.accepted_at) <= request.as_of
            )
            and (
                record.accepted_at is not None
                or record.filing_date is None
                or record.filing_date <= request.as_of.date()
            )
        ]

    def _simple_section(
        self,
        request: ResearchDataBundleRequest,
        capability: DataCapability,
        evidence: tuple[ResearchEvidenceItem, ...],
        *,
        requested_fields: tuple[str, ...],
        provider: str,
        maximum_age_days: int,
    ) -> ResearchDataSection:
        available = {item.field_path.rsplit(".", maxsplit=1)[-1] for item in evidence}
        requested_count = len(set(requested_fields) | available)
        missing_names = tuple(
            name for name in requested_fields if name not in available
        )
        missing = tuple(
            _missing_field(
                request,
                capability,
                f"{capability.value}.{name}",
                provider=provider,
                required=True,
            )
            for name in missing_names
        )
        if not evidence:
            return self._unavailable_section(
                request,
                capability,
                provider=provider,
                requested_fields=len(requested_fields),
                missing=missing,
            )
        latest = max(item.effective_at for item in evidence)
        age = max((request.as_of.date() - latest.date()).days, 0)
        stale = age > maximum_age_days
        status = (
            DataAvailabilityStatus.STALE
            if stale
            else (
                DataAvailabilityStatus.PARTIAL
                if missing
                else DataAvailabilityStatus.PRESENT
            )
        )
        return ResearchDataSection(
            capability=capability,
            status=status,
            as_of=request.as_of,
            freshness=DataFreshness(
                status=FreshnessStatus.STALE if stale else FreshnessStatus.FRESH,
                evaluated_at=request.as_of,
                policy_name=f"{capability.value}_freshness",
                policy_version="1.0",
                latest_effective_at=latest,
                age_days=age,
                maximum_age_days=maximum_age_days,
                reason="latest evidence exceeds freshness SLA" if stale else None,
            ),
            quality=_evaluated_quality(
                evidence,
                requested=requested_count,
                status=(
                    DataQualityStatus.WARNING
                    if stale or missing
                    else DataQualityStatus.PASS
                ),
            ),
            requested_field_count=requested_count,
            available_field_count=len({item.field_path for item in evidence}),
            items=evidence,
            missing_data=missing,
        )

    @staticmethod
    def _unavailable_section(
        request: ResearchDataBundleRequest,
        capability: DataCapability,
        *,
        provider: str = "not_configured",
        requested_fields: int = 1,
        missing: tuple[MissingData, ...] | None = None,
        requested: bool = True,
    ) -> ResearchDataSection:
        if requested:
            missing_items = missing or (
                _missing_field(
                    request,
                    capability,
                    f"{capability.value}.*",
                    provider=provider,
                    required=False,
                ),
            )
            status = DataAvailabilityStatus.MISSING
            freshness_status = FreshnessStatus.UNKNOWN
            freshness_reason = "no attributable observation is available"
            quality_reason = "quality cannot be evaluated without observations"
        else:
            missing_items = (
                MissingData(
                    capability=capability,
                    field_path=f"{capability.value}.*",
                    status=DataAvailabilityStatus.NOT_APPLICABLE,
                    reason_code=MissingDataReason.NOT_APPLICABLE,
                    reason="capability was not requested for this bundle",
                    required=False,
                    as_of=request.as_of,
                    expected_start=request.window_start,
                    expected_end=request.window_end,
                    impact="capability is intentionally absent from this bundle",
                    retryable=False,
                ),
            )
            status = DataAvailabilityStatus.NOT_APPLICABLE
            freshness_status = FreshnessStatus.NOT_APPLICABLE
            freshness_reason = "capability was not requested"
            quality_reason = "quality is not applicable to an unrequested capability"
        return ResearchDataSection(
            capability=capability,
            status=status,
            as_of=request.as_of,
            freshness=DataFreshness(
                status=freshness_status,
                evaluated_at=request.as_of,
                policy_name=f"{capability.value}_freshness",
                policy_version="1.0",
                reason=freshness_reason,
            ),
            quality=DataQuality(
                status=DataQualityStatus.UNKNOWN,
                observation_count=0,
                source_count=0,
                reason=quality_reason,
            ),
            requested_field_count=requested_fields,
            available_field_count=0,
            missing_data=missing_items,
        )


def _identity_evidence(
    instrument: InstrumentRecord,
    field_name: str,
    value: str | bool,
    as_of: datetime,
) -> ResearchEvidenceItem:
    record_key = str(instrument.asset_id)
    source = DataSourceReference(
        provider_name=instrument.source_primary,
        normalized_record_type="InstrumentRecord",
        normalized_record_key=record_key,
        provider_locator=f"instrument:{record_key}",
    )
    return _evidence_item(
        subject_id=record_key,
        field_path=f"asset_identity.{field_name}",
        effective_at=as_of,
        observed_at=as_of,
        value=value,
        unit=None,
        currency=None,
        source=source,
    )


def _fundamental_evidence(
    record: FundamentalRecord,
    field_name: str,
    unit: str,
    currency: str | None,
    *,
    temporal_access_mode: TemporalAccessMode = TemporalAccessMode.HISTORICAL_REPLAY,
) -> ResearchEvidenceItem:
    value = getattr(record, field_name)
    assert isinstance(value, int | float) and not isinstance(value, bool)
    record_key = (
        f"{record.asset_id}|{record.fiscal_period_end.isoformat()}|"
        f"{record.report_type}"
    )
    provider_locator = (
        record.source_locator or record.filing_url or f"fundamental:{record_key}"
    )
    source = DataSourceReference(
        provider_name=record.source_id,
        normalized_record_type="FundamentalRecord",
        normalized_record_key=record_key,
        provider_locator=provider_locator,
        source_url=(
            record.filing_url
            if record.filing_url and record.filing_url.startswith("https://")
            else None
        ),
        authorization_class=(
            "authenticated_api" if record.source_id == _FMP_PROVIDER else "public"
        ),
    )
    return _evidence_item(
        subject_id=str(record.asset_id),
        field_path=f"fundamentals.{field_name}",
        effective_at=datetime.combine(record.fiscal_period_end, time.min, tzinfo=UTC),
        observed_at=_record_observed_at(
            record,
            record.accepted_at or record.ingestion_ts,
            temporal_access_mode,
        ),
        value=float(value),
        unit=unit,
        currency=currency,
        source=source,
    )


def _choose_standardized_fundamentals(
    raw_evidence: tuple[ResearchEvidenceItem, ...],
    derived_evidence: tuple[ResearchEvidenceItem, ...],
) -> tuple[ResearchEvidenceItem, ...]:
    """Prefer FMP metrics and retain one transparent SEC cross-check."""

    chosen: list[ResearchEvidenceItem] = []
    for field_name in _STANDARDIZED_FUNDAMENTAL_FIELDS:
        field_path = f"fundamentals.{field_name}"
        fmp = max(
            (
                item
                for item in raw_evidence
                if item.field_path == field_path
                and item.source.provider_name == _FMP_PROVIDER
            ),
            key=lambda item: (item.effective_at, item.observed_at),
            default=None,
        )
        secondary = max(
            (
                item
                for item in (*raw_evidence, *derived_evidence)
                if item.field_path == field_path
                and item.source.provider_name != _FMP_PROVIDER
            ),
            key=lambda item: (item.effective_at, item.observed_at),
            default=None,
        )
        if fmp is None:
            if secondary is not None:
                chosen.append(secondary)
            continue
        if secondary is None:
            chosen.append(fmp)
            continue
        primary_value = float(fmp.value)
        secondary_value = float(secondary.value)
        difference = abs(primary_value - secondary_value)
        tolerance = max(0.02, abs(primary_value) * 0.10)
        conflict = difference > tolerance
        chosen.append(
            fmp.model_copy(
                update={
                    "quality": (
                        DataQualityStatus.CONFLICT
                        if conflict
                        else DataQualityStatus.PASS
                    ),
                    "cross_check": MetricCrossCheck(
                        primary_provider=_FMP_PROVIDER,
                        secondary_provider=secondary.source.provider_name,
                        primary_value=primary_value,
                        secondary_value=secondary_value,
                        absolute_difference=difference,
                        tolerance=tolerance,
                        conflict=conflict,
                    ),
                }
            )
        )
    return tuple(chosen)


def _bar_evidence(
    record: EodBarRecord,
    field_name: str,
    currency: str | None,
    *,
    temporal_access_mode: TemporalAccessMode = TemporalAccessMode.HISTORICAL_REPLAY,
) -> ResearchEvidenceItem:
    """Convert one non-null canonical bar field into attributable Evidence."""

    value = getattr(record, field_name)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"bar field {field_name} is not numeric")
    record_key = f"{record.asset_id}|{record.trade_date.isoformat()}"
    source = DataSourceReference(
        provider_name=record.source_id,
        normalized_record_type="EodBarRecord",
        normalized_record_key=record_key,
        provider_locator=f"eod_bar:{record_key}",
        source_url=(
            _ALPACA_BARS_URL if record.source_id == "alpaca_market_data" else None
        ),
        authorization_class=(
            "authenticated_api"
            if record.source_id == "alpaca_market_data"
            else "public"
        ),
        retention_class="normalized_market_data",
    )
    unit: str | None
    field_currency: str | None
    if field_name == "volume":
        unit = "shares"
        field_currency = None
    elif field_name == "turnover":
        unit = currency
        field_currency = currency
    else:
        unit = currency
        field_currency = currency
    return _evidence_item(
        subject_id=str(record.asset_id),
        field_path=f"ohlcv.{field_name}",
        effective_at=datetime.combine(record.trade_date, time.min, tzinfo=UTC),
        observed_at=_record_observed_at(
            record,
            record.ingestion_ts,
            temporal_access_mode,
        ),
        value=float(value),
        unit=unit,
        currency=field_currency,
        source=source,
    )


def _bar_metadata_evidence(
    record: EodBarRecord,
    field_name: str,
    *,
    temporal_access_mode: TemporalAccessMode = TemporalAccessMode.HISTORICAL_REPLAY,
) -> ResearchEvidenceItem:
    value = getattr(record, field_name)
    if not isinstance(value, str):
        raise ValueError(f"bar metadata field {field_name} is not text")
    record_key = f"{record.asset_id}|{record.trade_date.isoformat()}"
    return _record_evidence(
        subject_id=str(record.asset_id),
        field_path=f"ohlcv.{field_name}",
        effective_at=datetime.combine(record.trade_date, time.min, tzinfo=UTC),
        observed_at=_record_observed_at(
            record,
            record.ingestion_ts,
            temporal_access_mode,
        ),
        value=value,
        unit=None,
        provider=record.source_id,
        record_type="EodBarRecord",
        record_key=record_key,
        locator=f"alpaca:bars:{record.asset_id}:{record.trade_date}:{value}",
        source_url=_ALPACA_BARS_URL,
        authorization_class="authenticated_api",
        retention_class="normalized_market_data",
    )


def _technical_evidence(
    asset_id: AssetId,
    effective_date: date,
    field_name: str,
    value: str | int | float | bool,
    currency: str | None,
    parents: tuple[ResearchEvidenceItem, ...],
) -> ResearchEvidenceItem:
    """Create one derived feature whose complete bar lineage is explicit."""

    if not parents:
        raise ValueError("technical feature Evidence requires parent bars")
    providers = {parent.source.provider_name for parent in parents}
    provider_name = next(iter(providers)) if len(providers) == 1 else "multiple_sources"
    source_urls = {parent.source.source_url for parent in parents}
    source_url = next(iter(source_urls)) if len(source_urls) == 1 else None
    record_key = (
        f"{asset_id}|{effective_date.isoformat()}|{field_name}|"
        f"{_TECHNICAL_TRANSFORMATION_VERSION}"
    )
    price_feature = field_name in {"close", "sma_20", "sma_60", "atr_14", "macd"}
    ratio_feature = field_name != "trend_label" and not price_feature
    unit = currency if price_feature else ("ratio" if ratio_feature else None)
    return _evidence_item(
        subject_id=str(asset_id),
        field_path=f"technical_features.{field_name}",
        effective_at=datetime.combine(effective_date, time.min, tzinfo=UTC),
        observed_at=max(parent.observed_at for parent in parents),
        value=value,
        unit=unit,
        currency=currency if price_feature else None,
        source=DataSourceReference(
            provider_name=provider_name,
            normalized_record_type="TechnicalFeature",
            normalized_record_key=record_key,
            provider_locator=f"technical_feature:{record_key}",
            source_url=source_url,
            authorization_class="derived_from_normalized_market_data",
            retention_class="derived_normalized_facts",
        ),
        transformation_name=f"technical_feature.{field_name}",
        transformation_version=_TECHNICAL_TRANSFORMATION_VERSION,
        parent_evidence_ids=tuple(parent.evidence_id for parent in parents),
    )


def _technical_parent_ids(
    field_name: str,
    bars: list[EodBarRecord],
    evidence_by_field_date: dict[tuple[str, date], ResearchEvidenceItem],
    derived: dict[str, ResearchEvidenceItem],
) -> tuple[str, ...]:
    """Return the exact canonical inputs used by the deterministic operator."""

    dependencies: tuple[tuple[str, date], ...]
    if field_name == "close":
        dependencies = (("close", bars[-1].trade_date),)
    elif field_name == "sma_20":
        dependencies = tuple(("close", bar.trade_date) for bar in bars[-20:])
    elif field_name == "sma_60":
        dependencies = tuple(("close", bar.trade_date) for bar in bars[-60:])
    elif field_name.startswith("return_"):
        sessions = int(field_name.removeprefix("return_").removesuffix("d"))
        dependencies = (
            ("close", bars[-sessions - 1].trade_date),
            ("close", bars[-1].trade_date),
        )
    elif field_name in {"distance_to_sma20", "distance_to_sma60"}:
        average = "sma_20" if field_name.endswith("20") else "sma_60"
        return (derived["close"].evidence_id, derived[average].evidence_id)
    elif field_name.startswith("realized_vol_"):
        sessions = int(field_name.removeprefix("realized_vol_").removesuffix("d"))
        dependencies = tuple(("close", bar.trade_date) for bar in bars[-sessions - 1 :])
    elif field_name == "max_drawdown_60d":
        dependencies = tuple(("close", bar.trade_date) for bar in bars[-60:])
    elif field_name == "rsi_14":
        dependencies = tuple(("close", bar.trade_date) for bar in bars[-15:])
    elif field_name == "atr_14":
        dependencies = tuple(
            (name, bar.trade_date)
            for bar in bars[-15:]
            for name in ("high", "low", "close")
        )
    elif field_name == "macd":
        dependencies = tuple(("close", bar.trade_date) for bar in bars[-26:])
    elif field_name == "volume_ratio_20d":
        dependencies = tuple(("volume", bar.trade_date) for bar in bars[-20:])
    elif field_name == "trend_label":
        return (
            derived["sma_20"].evidence_id,
            derived["sma_60"].evidence_id,
        )
    else:
        raise ValueError(f"unsupported technical feature {field_name}")
    try:
        return tuple(
            evidence_by_field_date[value].evidence_id for value in dependencies
        )
    except KeyError as exc:
        raise ValueError(
            f"technical feature {field_name} has incomplete close lineage"
        ) from exc


def _difference_optional(current: float | None, prior: float | None) -> float | None:
    return None if current is None or prior is None else float(current) - float(prior)


def _dominant_community_topics(messages: tuple[str, ...]) -> str | None:
    tokens = Counter(
        token.upper()
        for message in messages
        for token in re.findall(r"(?<!\w)[$#][A-Za-z][A-Za-z0-9._-]{1,20}", message)
    )
    if not tokens:
        return None
    return ", ".join(token for token, _ in tokens.most_common(5))


def _evidence_item(
    *,
    subject_id: str,
    field_path: str,
    effective_at: datetime,
    observed_at: datetime,
    value: str | int | float | bool,
    unit: str | None,
    currency: str | None,
    source: DataSourceReference,
    transformation_name: str | None = None,
    transformation_version: str | None = None,
    parent_evidence_ids: tuple[str, ...] = (),
    quality: DataQualityStatus = DataQualityStatus.PASS,
    cross_check: MetricCrossCheck | None = None,
) -> ResearchEvidenceItem:
    content: dict[str, object] = {
        "subject_id": subject_id,
        "field_path": field_path,
        "effective_at": effective_at.isoformat(),
        "observed_at": observed_at.isoformat(),
        "value": value,
        "unit": unit,
        "currency": currency,
        "source": source.model_dump(mode="json", exclude_none=True),
    }
    if transformation_name is not None:
        content.update(
            {
                "transformation_name": transformation_name,
                "transformation_version": transformation_version,
                "parent_evidence_ids": parent_evidence_ids,
            }
        )
    content_hash = _sha256(content)
    return ResearchEvidenceItem(
        evidence_id=f"ev_{content_hash[:24]}",
        subject_id=subject_id,
        field_path=field_path,
        effective_at=effective_at,
        observed_at=observed_at,
        value=value,
        unit=unit,
        currency=currency,
        source=source,
        transformation_name=transformation_name,
        transformation_version=transformation_version,
        parent_evidence_ids=parent_evidence_ids,
        quality=quality,
        cross_check=cross_check,
        content_hash=content_hash,
    )


def _repath_evidence(
    item: ResearchEvidenceItem, field_path: str
) -> ResearchEvidenceItem:
    """Project Evidence to another capability with a matching canonical ID."""

    return _evidence_item(
        subject_id=item.subject_id,
        field_path=field_path,
        effective_at=item.effective_at,
        observed_at=item.observed_at,
        value=item.value,
        unit=item.unit,
        currency=item.currency,
        source=item.source,
        transformation_name=item.transformation_name,
        transformation_version=item.transformation_version,
        parent_evidence_ids=item.parent_evidence_ids,
        quality=item.quality,
        cross_check=item.cross_check,
    )


def _record_evidence(
    *,
    subject_id: str,
    field_path: str,
    effective_at: datetime,
    observed_at: datetime,
    value: str | int | float | bool | None,
    unit: str | None,
    provider: str,
    record_type: str,
    record_key: str,
    locator: str,
    source_url: str | None = None,
    authorization_class: str = "public",
    retention_class: str = "normalized_facts",
) -> ResearchEvidenceItem:
    if value is None:
        raise ValueError("canonical evidence cannot contain None")
    return _evidence_item(
        subject_id=subject_id,
        field_path=field_path,
        effective_at=effective_at,
        observed_at=observed_at,
        value=value,
        unit=unit,
        currency=None,
        source=DataSourceReference(
            provider_name=provider,
            normalized_record_type=record_type,
            normalized_record_key=record_key,
            provider_locator=locator,
            source_url=source_url,
            authorization_class=authorization_class,
            retention_class=retention_class,
        ),
    )


def _derived_evidence(
    request: ResearchDataBundleRequest,
    *,
    capability: DataCapability,
    field_name: str,
    value: str | int | float | bool,
    parents: tuple[ResearchEvidenceItem, ...],
    transformation: str,
    version: str,
    unit: str | None,
) -> ResearchEvidenceItem:
    if not parents:
        raise ValueError("derived Evidence requires canonical parents")
    provider_names = {parent.source.provider_name for parent in parents}
    provider = (
        next(iter(provider_names)) if len(provider_names) == 1 else "multiple_sources"
    )
    record_key = (
        f"{request.asset_id}|{request.as_of.isoformat()}|{field_name}|{version}"
    )
    return _evidence_item(
        subject_id=str(request.asset_id),
        field_path=f"{capability.value}.{field_name}",
        effective_at=max(parent.effective_at for parent in parents),
        observed_at=max(parent.observed_at for parent in parents),
        value=value,
        unit=unit,
        currency="USD" if unit == "USD" else None,
        source=DataSourceReference(
            provider_name=provider,
            normalized_record_type="DerivedResearchFeature",
            normalized_record_key=record_key,
            provider_locator=f"derived:{record_key}",
            authorization_class="derived_from_normalized_data",
            retention_class="derived_normalized_facts",
        ),
        transformation_name=f"{transformation}.{field_name}",
        transformation_version=version,
        parent_evidence_ids=tuple(parent.evidence_id for parent in parents),
    )


def _partial_bar_field(
    request: ResearchDataBundleRequest,
    field_name: str,
    *,
    provider_names: tuple[str, ...],
    available_count: int,
    observation_count: int,
    required: bool,
) -> MissingData:
    return MissingData(
        capability=DataCapability.OHLCV,
        field_path=f"ohlcv.{field_name}",
        status=DataAvailabilityStatus.PARTIAL,
        reason_code=MissingDataReason.NO_OBSERVATION,
        reason=(
            f"{field_name} is present for {available_count} of "
            f"{observation_count} normalized bars"
        ),
        required=required,
        as_of=request.as_of,
        expected_start=request.window_start,
        expected_end=request.window_end,
        providers_checked=provider_names,
        impact=f"ohlcv.{field_name} has incomplete observation coverage",
        retryable=True,
    )


def _missing_technical_feature(
    request: ResearchDataBundleRequest,
    field_name: str,
    provider: str,
    valid_close_count: int,
) -> MissingData:
    minimum_history = {
        "close": 1,
        "return_1d": 2,
        "return_5d": 6,
        "return_20d": 21,
        "return_60d": 61,
        "sma_20": 20,
        "sma_60": 60,
        "distance_to_sma20": 20,
        "distance_to_sma60": 60,
        "realized_vol_20d": 21,
        "realized_vol_60d": 61,
        "max_drawdown_60d": 60,
        "rsi_14": 15,
        "atr_14": 15,
        "macd": 26,
        "volume_ratio_20d": 20,
        "relative_strength_vs_spy": 21,
        "relative_strength_vs_qqq": 21,
        "relative_strength_vs_xlk": 21,
        "trend_label": 60,
    }[field_name]
    insufficient = valid_close_count < minimum_history
    return MissingData(
        capability=DataCapability.TECHNICAL_FEATURES,
        field_path=f"technical_features.{field_name}",
        status=DataAvailabilityStatus.MISSING,
        reason_code=(
            MissingDataReason.INSUFFICIENT_HISTORY
            if insufficient
            else MissingDataReason.INVALID_RECORD
        ),
        reason=(
            f"{field_name} requires {minimum_history} valid close observations; "
            f"{valid_close_count} are available"
            if insufficient
            else f"{field_name} could not be computed from the normalized window"
        ),
        required=True,
        as_of=request.as_of,
        expected_start=request.window_start,
        expected_end=request.window_end,
        providers_checked=(provider,),
        impact=f"technical_features.{field_name} cannot be used as research evidence",
        retryable=True,
    )


def _missing_field(
    request: ResearchDataBundleRequest,
    capability: DataCapability,
    field_path: str,
    *,
    provider: str,
    required: bool,
) -> MissingData:
    return MissingData(
        capability=capability,
        field_path=field_path,
        status=DataAvailabilityStatus.MISSING,
        reason_code=MissingDataReason.NO_OBSERVATION,
        reason="no attributable normalized observation is available",
        required=required,
        as_of=request.as_of,
        expected_start=request.window_start,
        expected_end=request.window_end,
        providers_checked=(provider,),
        impact=f"{field_path} cannot be used as research evidence",
        retryable=provider != "not_configured",
    )


def _evaluated_quality(
    evidence: tuple[ResearchEvidenceItem, ...],
    *,
    requested: int,
    status: DataQualityStatus,
) -> DataQuality:
    available = len({item.field_path for item in evidence})
    source_count = len(
        {(item.source.provider_name, item.source.provider_locator) for item in evidence}
    )
    return DataQuality(
        status=status,
        observation_count=len(evidence),
        source_count=source_count,
        completeness_ratio=min(available / requested, 1.0),
        validity_ratio=1.0,
        lineage_coverage_ratio=1.0,
        temporal_coverage_ratio=1.0,
    )


def _market_freshness(
    request: ResearchDataBundleRequest,
    latest_date: date,
    age_days: int,
    maximum_age_days: int,
) -> DataFreshness:
    status = (
        FreshnessStatus.FRESH if age_days <= maximum_age_days else FreshnessStatus.STALE
    )
    return DataFreshness(
        status=status,
        evaluated_at=request.as_of,
        policy_name="eod_market_close",
        policy_version="1.0",
        latest_effective_at=datetime.combine(latest_date, time.min, tzinfo=UTC),
        age_days=age_days,
        maximum_age_days=maximum_age_days,
        reason=(
            None
            if status is FreshnessStatus.FRESH
            else "latest normalized market close exceeds the freshness SLA"
        ),
    )


def _market_quality(
    evidence: tuple[ResearchEvidenceItem, ...],
    *,
    requested_cells: int,
    window_start: date,
    window_end: date,
    observation_dates: list[date],
    status: DataQualityStatus,
) -> DataQuality:
    if requested_cells <= 0:
        raise ValueError("market quality requires requested cells")
    window_days = (window_end - window_start).days + 1
    if observation_dates:
        covered_start = max(min(observation_dates), window_start)
        covered_end = min(max(observation_dates), window_end)
        covered_days = max((covered_end - covered_start).days + 1, 0)
    else:
        covered_days = 0
    return DataQuality(
        status=status,
        observation_count=len(evidence),
        source_count=len(
            {
                (item.source.provider_name, item.source.provider_locator)
                for item in evidence
            }
        ),
        completeness_ratio=min(len(evidence) / requested_cells, 1.0),
        validity_ratio=1.0 if evidence else 0.0,
        lineage_coverage_ratio=1.0 if evidence else 0.0,
        temporal_coverage_ratio=min(covered_days / window_days, 1.0),
        reason=("no valid derived value is available" if not evidence else None),
    )


def _market_data_provider(request: ResearchDataBundleRequest) -> str:
    if request.asset_id.market.value == "US":
        return "alpaca_market_data"
    return "normalized_market_data"


def _bundle_fingerprint(
    request: ResearchDataBundleRequest,
    sections: dict[DataCapability, ResearchDataSection],
) -> str:
    return _sha256(
        {
            "request": request.model_dump(mode="json", exclude_none=True),
            "sections": {
                key.value: value.model_dump(mode="json", exclude_none=True)
                for key, value in sorted(sections.items(), key=lambda item: item[0])
            },
        }
    )


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        local_timezone = datetime.now().astimezone().tzinfo or UTC
        return value.replace(tzinfo=local_timezone).astimezone(UTC)
    return value.astimezone(UTC)


def _record_observed_at(
    record: object,
    historical_observed_at: datetime,
    mode: TemporalAccessMode,
) -> datetime:
    """Select source availability for live data without changing replay truth."""

    if mode is TemporalAccessMode.HISTORICAL_REPLAY:
        return _as_utc(historical_observed_at)
    if isinstance(record, EodBarRecord):
        available_at = temporal_metadata_for(record).available_at
    elif isinstance(record, FundamentalRecord):
        available_at = (
            _as_utc(record.accepted_at)
            if record.accepted_at is not None
            else (
                datetime.combine(record.filing_date, time.min, tzinfo=UTC)
                if record.filing_date is not None
                else None
            )
        )
    elif isinstance(record, MacroObservationRecord):
        available_at = (
            None
            if record.realtime_start is None
            else datetime.combine(record.realtime_start, time.min, tzinfo=UTC)
        )
    elif isinstance(record, NewsEvidenceRecord):
        available_at = _as_utc(record.created_at)
    elif isinstance(record, SentimentSnapshotRecord):
        available_at = _as_utc(record.source_timestamp)
    elif isinstance(record, SentimentEvidenceRecord):
        available_at = _as_utc(record.created_at)
    elif isinstance(record, TextDocumentRecord):
        available_at = None if record.publish_ts is None else _as_utc(record.publish_ts)
    else:
        available_at = temporal_metadata_for(record).available_at
    if available_at is None:
        raise ValueError(f"{type(record).__name__} has no provider availability")
    return available_at
