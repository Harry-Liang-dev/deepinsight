"""Deterministic, point-in-time Sector market and fundamental aggregation."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from typing import cast

import pandas as pd  # type: ignore[import-untyped]

from src.models.enums import SectorCapabilityStatus
from src.operators.technical_features import TechnicalFeatureOperator
from src.schemas.market_data import EodBarRecord, FundamentalRecord
from src.schemas.sectors import (
    CoveredSectorMetric,
    SectorBreadthState,
    SectorFundamentalState,
    SectorMarketState,
    SectorResearchCoverage,
    SectorResearchSnapshot,
    SectorUniverseSnapshot,
    SectorValuationState,
)

_FEATURE_VERSION = "sector_research_features_v1"
_MARKET_BENCHMARK_ID = "US:SPY"
_MIN_SECTOR_SAMPLE = 2


class SectorStateInputError(ValueError):
    """Raised when Sector inputs violate point-in-time or identity rules."""


class SectorStateOperator:
    """Compute SectorResearchSnapshot v1 without LLM inference."""

    version = _FEATURE_VERSION

    def __init__(
        self,
        technical_operator: TechnicalFeatureOperator | None = None,
    ) -> None:
        """Optionally inject the existing deterministic technical operator."""

        self._technical = technical_operator or TechnicalFeatureOperator()

    def compute(
        self,
        *,
        universe: SectorUniverseSnapshot,
        bars_by_asset: Mapping[str, Sequence[EodBarRecord]],
        fundamentals_by_asset: Mapping[str, Sequence[FundamentalRecord]],
        market_benchmark_id: str = _MARKET_BENCHMARK_ID,
    ) -> SectorResearchSnapshot:
        """Compute one immutable state using observations available by ``as_of``."""

        _validate_point_in_time(
            as_of=universe.as_of,
            bars_by_asset=bars_by_asset,
            fundamentals_by_asset=fundamentals_by_asset,
        )
        universe_ids = tuple(str(item) for item in universe.asset_ids)
        universe_count = len(universe_ids)
        constituent_features = {
            asset_id: _technical_features(
                self._technical, bars_by_asset.get(asset_id, ())
            )
            for asset_id in universe_ids
        }
        benchmark_id = (
            str(universe.benchmark_ids[0]) if universe.benchmark_ids else None
        )
        market_features = _technical_features(
            self._technical,
            bars_by_asset.get(market_benchmark_id, ()),
        )
        benchmark_features = (
            {}
            if benchmark_id is None
            else _technical_features(
                self._technical,
                bars_by_asset.get(benchmark_id, ()),
            )
        )
        market_state = _market_state(
            constituent_features,
            universe_count=universe_count,
            market_features=market_features,
            benchmark_features=benchmark_features,
        )
        breadth_state = _breadth_state(
            constituent_features,
            universe_count=universe_count,
            benchmark_features=benchmark_features,
        )
        selected_fundamentals = {
            asset_id: _latest_fundamental(fundamentals_by_asset.get(asset_id, ()))
            for asset_id in universe_ids
        }
        fundamental_state = _fundamental_state(
            selected_fundamentals,
            universe_count=universe_count,
        )
        valuation_state = _valuation_state(
            selected_fundamentals,
            universe_count=universe_count,
        )
        market_coverage = sum(
            _numeric(features.get("return_1d")) is not None
            for features in constituent_features.values()
        )
        fundamental_coverage = sum(
            record is not None for record in selected_fundamentals.values()
        )
        coverage = SectorResearchCoverage(
            universe_count=universe_count,
            market_coverage_count=market_coverage,
            fundamental_coverage_count=fundamental_coverage,
            benchmark_coverage_count=int(
                _numeric(benchmark_features.get("return_20d")) is not None
            ),
        )
        relevant_ids = {*universe_ids, market_benchmark_id}
        if benchmark_id is not None:
            relevant_ids.add(benchmark_id)
        source_ids = _source_ids(
            universe=universe,
            bars_by_asset=bars_by_asset,
            fundamentals_by_asset=fundamentals_by_asset,
            relevant_ids=relevant_ids,
        )
        status = _snapshot_status(
            universe_count=universe_count,
            market_coverage=market_coverage,
            fundamental_coverage=fundamental_coverage,
        )
        content = {
            "sector_id": universe.sector_id.value,
            "as_of": universe.as_of.isoformat(),
            "market_state": market_state.model_dump(mode="json"),
            "breadth_state": breadth_state.model_dump(mode="json"),
            "fundamental_state": fundamental_state.model_dump(mode="json"),
            "valuation_state": valuation_state.model_dump(mode="json"),
            "coverage": coverage.model_dump(mode="json"),
            "source_ids": list(source_ids),
            "feature_version": self.version,
            "status": status.value,
        }
        return SectorResearchSnapshot(
            snapshot_id=_research_snapshot_id(content),
            sector_id=universe.sector_id,
            as_of=universe.as_of,
            market_state=market_state,
            breadth_state=breadth_state,
            fundamental_state=fundamental_state,
            valuation_state=valuation_state,
            coverage=coverage,
            source_ids=source_ids,
            feature_version=self.version,
            status=status,
        )


def _market_state(
    features: Mapping[str, Mapping[str, object]],
    *,
    universe_count: int,
    market_features: Mapping[str, object],
    benchmark_features: Mapping[str, object],
) -> SectorMarketState:
    metrics = {
        key: _median_metric(
            [_numeric(item.get(key)) for item in features.values()],
            universe_count=universe_count,
        )
        for key in (
            "return_1d",
            "return_5d",
            "return_20d",
            "return_60d",
            "realized_vol_20d",
            "realized_vol_60d",
            "max_drawdown_60d",
        )
    }
    return_20d = metrics["return_20d"]
    return SectorMarketState(
        return_1d=metrics["return_1d"],
        return_5d=metrics["return_5d"],
        return_20d=return_20d,
        return_60d=metrics["return_60d"],
        excess_return_vs_market=_excess_metric(
            return_20d,
            _numeric(market_features.get("return_20d")),
        ),
        excess_return_vs_sector_benchmark=_excess_metric(
            return_20d,
            _numeric(benchmark_features.get("return_20d")),
        ),
        realized_vol_20d=metrics["realized_vol_20d"],
        realized_vol_60d=metrics["realized_vol_60d"],
        max_drawdown_60d=metrics["max_drawdown_60d"],
    )


def _breadth_state(
    features: Mapping[str, Mapping[str, object]],
    *,
    universe_count: int,
    benchmark_features: Mapping[str, object],
) -> SectorBreadthState:
    return_1d = [_numeric(item.get("return_1d")) for item in features.values()]
    return_5d = [_numeric(item.get("return_5d")) for item in features.values()]
    return_20d = [_numeric(item.get("return_20d")) for item in features.values()]
    above_20 = [
        close > average
        for item in features.values()
        if (close := _numeric(item.get("close"))) is not None
        and (average := _numeric(item.get("sma_20"))) is not None
    ]
    above_60 = [
        close > average
        for item in features.values()
        if (close := _numeric(item.get("close"))) is not None
        and (average := _numeric(item.get("sma_60"))) is not None
    ]
    positive_5d = [value > 0.0 for value in return_5d if value is not None]
    positive_20d = [value > 0.0 for value in return_20d if value is not None]
    valid_1d = [value for value in return_1d if value is not None]
    advances = sum(value > 0.0 for value in valid_1d)
    declines = sum(value < 0.0 for value in valid_1d)
    advance_decline = None if declines == 0 else float(advances) / float(declines)
    benchmark_return = _numeric(benchmark_features.get("return_20d"))
    valid_20d = [value for value in return_20d if value is not None]
    leader_values = (
        []
        if benchmark_return is None
        else [value > benchmark_return for value in valid_20d]
    )
    laggard_values = (
        []
        if benchmark_return is None
        else [value < benchmark_return for value in valid_20d]
    )
    return SectorBreadthState(
        pct_above_sma20=_ratio_metric(above_20, universe_count),
        pct_above_sma60=_ratio_metric(above_60, universe_count),
        pct_positive_5d=_ratio_metric(positive_5d, universe_count),
        pct_positive_20d=_ratio_metric(positive_20d, universe_count),
        advance_decline_ratio=_explicit_metric(
            advance_decline,
            coverage_count=len(valid_1d),
            universe_count=universe_count,
        ),
        median_return_5d=_median_metric(return_5d, universe_count=universe_count),
        median_return_20d=_median_metric(return_20d, universe_count=universe_count),
        return_dispersion_20d=_dispersion_metric(
            return_20d,
            universe_count=universe_count,
        ),
        leader_count=_count_metric(leader_values, universe_count),
        laggard_count=_count_metric(laggard_values, universe_count),
    )


def _fundamental_state(
    records: Mapping[str, FundamentalRecord | None],
    *,
    universe_count: int,
) -> SectorFundamentalState:
    return SectorFundamentalState(
        median_revenue_yoy=_record_median(records, "revenue_yoy", universe_count),
        median_net_income_yoy=_record_median(records, "net_income_yoy", universe_count),
        median_gross_margin=_record_median(records, "gross_margin", universe_count),
        median_roe=_record_median(records, "roe", universe_count),
        median_roa=_record_median(records, "roa", universe_count),
        positive_revenue_growth_ratio=_record_positive_ratio(
            records, "revenue_yoy", universe_count
        ),
        positive_net_income_growth_ratio=_record_positive_ratio(
            records, "net_income_yoy", universe_count
        ),
    )


def _valuation_state(
    records: Mapping[str, FundamentalRecord | None],
    *,
    universe_count: int,
) -> SectorValuationState:
    return SectorValuationState(
        median_pe=_record_median(records, "pe_ttm", universe_count),
        median_pb=_record_median(records, "pb", universe_count),
    )


def _technical_features(
    operator: TechnicalFeatureOperator,
    records: Sequence[EodBarRecord],
) -> Mapping[str, object]:
    if not records:
        return operator.compute(pd.DataFrame(columns=["trade_date", "close"]))
    ordered = sorted(records, key=lambda item: item.trade_date)
    return operator.compute(
        pd.DataFrame(
            [
                {
                    "trade_date": item.trade_date,
                    "close": (
                        item.adj_close if item.adj_close is not None else item.close
                    ),
                    "high": item.high,
                    "low": item.low,
                    "volume": item.volume,
                }
                for item in ordered
            ]
        )
    )


def _latest_fundamental(
    records: Sequence[FundamentalRecord],
) -> FundamentalRecord | None:
    if not records:
        return None
    standardized = [
        item for item in records if item.source_id == "financial_modeling_prep"
    ]
    candidates = standardized or list(records)
    return max(
        candidates,
        key=lambda item: (
            item.fiscal_period_end,
            item.accepted_at or datetime.min.replace(tzinfo=UTC),
            item.report_type,
        ),
    )


def _record_median(
    records: Mapping[str, FundamentalRecord | None],
    field_name: str,
    universe_count: int,
) -> CoveredSectorMetric:
    return _median_metric(
        [
            _numeric(getattr(record, field_name)) if record is not None else None
            for record in records.values()
        ],
        universe_count=universe_count,
    )


def _record_positive_ratio(
    records: Mapping[str, FundamentalRecord | None],
    field_name: str,
    universe_count: int,
) -> CoveredSectorMetric:
    values = [
        value > 0.0
        for record in records.values()
        if record is not None
        and (value := _numeric(getattr(record, field_name))) is not None
    ]
    return _ratio_metric(values, universe_count)


def _median_metric(
    values: Sequence[float | None],
    *,
    universe_count: int,
) -> CoveredSectorMetric:
    available = [value for value in values if value is not None]
    value = (
        float(statistics.median(available))
        if len(available) >= _MIN_SECTOR_SAMPLE
        else None
    )
    return _explicit_metric(
        value,
        coverage_count=len(available),
        universe_count=universe_count,
    )


def _ratio_metric(values: Sequence[bool], universe_count: int) -> CoveredSectorMetric:
    value = sum(values) / len(values) if len(values) >= _MIN_SECTOR_SAMPLE else None
    return _explicit_metric(
        None if value is None else float(value),
        coverage_count=len(values),
        universe_count=universe_count,
    )


def _dispersion_metric(
    values: Sequence[float | None],
    *,
    universe_count: int,
) -> CoveredSectorMetric:
    available = [value for value in values if value is not None]
    value = (
        float(statistics.stdev(available))
        if len(available) >= _MIN_SECTOR_SAMPLE
        else None
    )
    return _explicit_metric(
        value,
        coverage_count=len(available),
        universe_count=universe_count,
    )


def _count_metric(values: Sequence[bool], universe_count: int) -> CoveredSectorMetric:
    value = float(sum(values)) if len(values) >= _MIN_SECTOR_SAMPLE else None
    return _explicit_metric(
        value,
        coverage_count=len(values),
        universe_count=universe_count,
    )


def _excess_metric(
    sector_metric: CoveredSectorMetric,
    benchmark_return: float | None,
) -> CoveredSectorMetric:
    value = (
        None
        if sector_metric.value is None or benchmark_return is None
        else sector_metric.value - benchmark_return
    )
    return _explicit_metric(
        value,
        coverage_count=sector_metric.coverage_count,
        universe_count=sector_metric.universe_count,
    )


def _explicit_metric(
    value: float | None,
    *,
    coverage_count: int,
    universe_count: int,
) -> CoveredSectorMetric:
    if coverage_count == 0:
        status = SectorCapabilityStatus.MISSING
    elif value is None or coverage_count < universe_count:
        status = SectorCapabilityStatus.PARTIAL
    else:
        status = SectorCapabilityStatus.AVAILABLE
    return CoveredSectorMetric(
        value=value,
        coverage_count=coverage_count,
        universe_count=universe_count,
        status=status,
    )


def _snapshot_status(
    *, universe_count: int, market_coverage: int, fundamental_coverage: int
) -> SectorCapabilityStatus:
    if universe_count == 0 or (market_coverage == 0 and fundamental_coverage == 0):
        return SectorCapabilityStatus.MISSING
    if (
        universe_count < _MIN_SECTOR_SAMPLE
        or market_coverage < universe_count
        or fundamental_coverage < universe_count
    ):
        return SectorCapabilityStatus.PARTIAL
    return SectorCapabilityStatus.AVAILABLE


def _validate_point_in_time(
    *,
    as_of: date,
    bars_by_asset: Mapping[str, Sequence[EodBarRecord]],
    fundamentals_by_asset: Mapping[str, Sequence[FundamentalRecord]],
) -> None:
    cutoff = datetime.combine(as_of, time.max, tzinfo=UTC)
    for bar_records in bars_by_asset.values():
        for bar_record in bar_records:
            if bar_record.trade_date > as_of:
                raise SectorStateInputError("future EOD observation is not allowed")
            _require_observed_by(bar_record.ingestion_ts, cutoff, "EOD")
    for fundamental_records in fundamentals_by_asset.values():
        for fundamental_record in fundamental_records:
            if fundamental_record.fiscal_period_end > as_of:
                raise SectorStateInputError("future fundamental period is not allowed")
            _require_observed_by(fundamental_record.ingestion_ts, cutoff, "fundamental")
            if fundamental_record.accepted_at is not None:
                _require_observed_by(
                    fundamental_record.accepted_at, cutoff, "accepted filing"
                )


def _require_observed_by(value: datetime, cutoff: datetime, label: str) -> None:
    # DuckDB's existing TIMESTAMP columns persist normalized UTC as naive
    # values. Canonical Repository reads therefore restore that documented
    # UTC meaning here before enforcing the point-in-time cutoff.
    observed = (
        value.replace(tzinfo=UTC)
        if value.tzinfo is None or value.utcoffset() is None
        else value.astimezone(UTC)
    )
    if observed > cutoff:
        raise SectorStateInputError(f"future {label} observation is not allowed")


def _source_ids(
    *,
    universe: SectorUniverseSnapshot,
    bars_by_asset: Mapping[str, Sequence[EodBarRecord]],
    fundamentals_by_asset: Mapping[str, Sequence[FundamentalRecord]],
    relevant_ids: set[str],
) -> tuple[str, ...]:
    values = {f"sector_membership:{universe.membership_version}"}
    for asset_id in sorted(relevant_ids):
        values.update(item.source_id for item in bars_by_asset.get(asset_id, ()))
        values.update(
            item.source_id for item in fundamentals_by_asset.get(asset_id, ())
        )
    return tuple(sorted(values))


def _research_snapshot_id(content: Mapping[str, object]) -> str:
    payload = json.dumps(content, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"sector_research_{digest}"


def _numeric(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    numeric = float(cast(float, value))
    return numeric if math.isfinite(numeric) else None
