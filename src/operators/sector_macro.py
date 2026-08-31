"""Deterministic Sector cycle directions and empirical macro sensitivities."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from typing import cast

import pandas as pd  # type: ignore[import-untyped]

from src.models.enums import MacroCycleDirection, SectorCapabilityStatus
from src.schemas.market_data import EodBarRecord, MacroObservationRecord
from src.schemas.sectors import (
    MacroCycleDimensionState,
    MacroSensitivity,
    MacroSensitivityEstimate,
    MacroSeriesCycleSignal,
    SectorCycleState,
    SectorMacroSnapshot,
    SectorResearchSnapshot,
    SectorUniverseSnapshot,
)

_VERSION = "sector_macro_features_v1"
_WINDOW_MONTHS = 36
_MIN_OBSERVATIONS = 24
_DIMENSIONS = {
    "rates": ("FEDFUNDS", "DGS2", "DGS10", "T10Y2Y"),
    "inflation": ("CPIAUCSL", "PCEPILFE"),
    "labor": ("UNRATE", "PAYEMS"),
    "growth": ("GDP", "INDPRO"),
    "financial_stress": ("VIXCLS", "BAMLH0A0HYM2"),
}
_YOY_PERIODS = {
    "CPIAUCSL": 12,
    "PCEPILFE": 12,
    "PAYEMS": 12,
    "GDP": 4,
    "INDPRO": 12,
}


class SectorMacroInputError(ValueError):
    """Raised when Day33 inputs violate identity or point-in-time safety."""


class SectorMacroOperator:
    """Connect FRED history to Sector state without training a Regime model."""

    version = _VERSION

    def compute(
        self,
        *,
        universe: SectorUniverseSnapshot,
        sector_state: SectorResearchSnapshot,
        benchmark_bars: Sequence[EodBarRecord],
        macro_observations: Sequence[MacroObservationRecord],
    ) -> SectorMacroSnapshot:
        """Compute deterministic cycle directions and rolling sensitivities."""

        _validate_inputs(
            universe=universe,
            sector_state=sector_state,
            benchmark_bars=benchmark_bars,
            macro_observations=macro_observations,
        )
        by_series = {
            series_id: tuple(
                item for item in macro_observations if item.series_key == series_id
            )
            for series_id in {
                item for values in _DIMENSIONS.values() for item in values
            }
        }
        signals = {
            series_id: _cycle_signal(series_id, records)
            for series_id, records in by_series.items()
        }
        source_ids = tuple(
            sorted(
                {
                    *(item.source_id for item in macro_observations),
                    *(item.source_id for item in benchmark_bars),
                }
            )
        )
        dimensions = {
            name: _dimension_state(
                tuple(
                    signal
                    for series_id in series_ids
                    if (signal := signals.get(series_id)) is not None
                ),
                expected_count=len(series_ids),
            )
            for name, series_ids in _DIMENSIONS.items()
        }
        cycle_status = _aggregate_status(
            tuple(item.status for item in dimensions.values())
        )
        cycle_state = SectorCycleState(
            sector_id=universe.sector_id,
            as_of=universe.as_of,
            rates=dimensions["rates"],
            inflation=dimensions["inflation"],
            labor=dimensions["labor"],
            growth=dimensions["growth"],
            financial_stress=dimensions["financial_stress"],
            sector_momentum=sector_state.market_state.return_20d,
            source_ids=source_ids,
            feature_version=self.version,
            status=cycle_status,
        )
        benchmark_id = universe.benchmark_ids[0] if universe.benchmark_ids else None
        estimates = tuple(
            _sensitivity_estimate(
                series_id,
                records,
                benchmark_bars,
                as_of=universe.as_of,
            )
            for series_id, records in sorted(by_series.items())
        )
        sensitivity_status = _aggregate_status(tuple(item.status for item in estimates))
        sensitivity = MacroSensitivity(
            sector_id=universe.sector_id,
            as_of=universe.as_of,
            benchmark_id=benchmark_id,
            estimates=estimates,
            source_ids=source_ids,
            feature_version=self.version,
            status=sensitivity_status,
        )
        status = _aggregate_status((cycle_status, sensitivity_status))
        content = {
            "sector_id": universe.sector_id.value,
            "as_of": universe.as_of.isoformat(),
            "cycle_state": cycle_state.model_dump(mode="json"),
            "macro_sensitivity": sensitivity.model_dump(mode="json"),
            "source_sector_snapshot_id": sector_state.snapshot_id,
            "feature_version": self.version,
            "status": status.value,
        }
        return SectorMacroSnapshot(
            snapshot_id=_snapshot_id(content),
            sector_id=universe.sector_id,
            as_of=universe.as_of,
            cycle_state=cycle_state,
            macro_sensitivity=sensitivity,
            source_sector_snapshot_id=sector_state.snapshot_id,
            feature_version=self.version,
            status=status,
        )


def _cycle_signal(
    series_id: str,
    records: Sequence[MacroObservationRecord],
) -> MacroSeriesCycleSignal | None:
    monthly = _macro_monthly_values(series_id, records)
    if monthly.empty:
        return None
    transformed, transformation = _transformed_macro_series(series_id, monthly)
    transformed = transformed.dropna()
    if transformed.empty:
        return None
    latest_month = cast(pd.Period, transformed.index[-1])
    latest_value = float(transformed.iloc[-1])
    change_3m = _change_from_period(transformed, latest_month - 3, latest_value)
    change_12m = _change_from_period(transformed, latest_month - 12, latest_value)
    latest_record = max(records, key=lambda item: item.observation_date)
    return MacroSeriesCycleSignal(
        series_id=series_id,
        transformation=transformation,
        latest_observation_date=latest_record.observation_date,
        latest_value=latest_value,
        change_3m=change_3m,
        change_12m=change_12m,
        direction=_direction(change_3m),
        source_id=latest_record.source_id,
    )


def _dimension_state(
    signals: tuple[MacroSeriesCycleSignal, ...],
    *,
    expected_count: int,
) -> MacroCycleDimensionState:
    directions = [
        item.direction
        for item in signals
        if item.direction is not MacroCycleDirection.UNKNOWN
    ]
    if not directions:
        direction = MacroCycleDirection.UNKNOWN
    else:
        counts = Counter(directions)
        top_count = max(counts.values())
        leaders = [key for key, value in counts.items() if value == top_count]
        direction = leaders[0] if len(leaders) == 1 else MacroCycleDirection.MIXED
    if not signals:
        status = SectorCapabilityStatus.MISSING
    elif len(signals) < expected_count or direction in {
        MacroCycleDirection.UNKNOWN,
        MacroCycleDirection.MIXED,
    }:
        status = SectorCapabilityStatus.PARTIAL
    else:
        status = SectorCapabilityStatus.AVAILABLE
    return MacroCycleDimensionState(
        direction=direction,
        signals=signals,
        coverage_count=len(signals),
        expected_count=expected_count,
        status=status,
    )


def _sensitivity_estimate(
    series_id: str,
    records: Sequence[MacroObservationRecord],
    benchmark_bars: Sequence[EodBarRecord],
    *,
    as_of: date,
) -> MacroSensitivityEstimate:
    macro = _macro_monthly_values(series_id, records)
    transformed, transformation = _transformed_macro_series(series_id, macro)
    macro_changes = transformed.diff().dropna()
    sector_returns = _monthly_returns(benchmark_bars)
    cutoff = pd.Period(as_of, freq="M")
    start = cutoff - (_WINDOW_MONTHS - 1)
    joined = pd.concat(
        (
            sector_returns.rename("sector_return"),
            macro_changes.rename("macro_change"),
        ),
        axis=1,
        join="inner",
    ).dropna()
    joined = joined[(joined.index >= start) & (joined.index <= cutoff)]
    count = len(joined)
    beta: float | None = None
    correlation: float | None = None
    if count >= _MIN_OBSERVATIONS:
        variance = float(joined["macro_change"].var(ddof=1))
        if math.isfinite(variance) and variance > 0.0:
            covariance = float(joined["macro_change"].cov(joined["sector_return"]))
            raw_correlation = float(
                joined["macro_change"].corr(joined["sector_return"])
            )
            beta = covariance / variance
            correlation = raw_correlation if math.isfinite(raw_correlation) else None
    if count == 0:
        status = SectorCapabilityStatus.MISSING
    elif beta is None or correlation is None:
        status = SectorCapabilityStatus.PARTIAL
    else:
        status = SectorCapabilityStatus.AVAILABLE
    source_id = (
        max(records, key=lambda item: item.observation_date).source_id
        if records
        else "fred"
    )
    return MacroSensitivityEstimate(
        series_id=series_id,
        transformation=transformation,
        beta=beta,
        correlation=correlation,
        observation_count=count,
        source_id=source_id,
        status=status,
    )


def _macro_monthly_values(
    series_id: str,
    records: Sequence[MacroObservationRecord],
) -> pd.Series:
    values = [
        (pd.Period(item.observation_date, freq="M"), float(item.value))
        for item in sorted(records, key=lambda item: item.observation_date)
        if item.value is not None and math.isfinite(float(item.value))
    ]
    if not values:
        return pd.Series(dtype="float64")
    frame = pd.DataFrame(values, columns=["month", "value"])
    return frame.groupby("month", sort=True)["value"].last()


def _transformed_macro_series(
    series_id: str,
    monthly: pd.Series,
) -> tuple[pd.Series, str]:
    periods = _YOY_PERIODS.get(series_id)
    if periods is None:
        return monthly, "monthly_level_change"
    return (
        monthly.pct_change(periods=periods, fill_method=None) * 100.0,
        "yoy_growth_change",
    )


def _monthly_returns(records: Sequence[EodBarRecord]) -> pd.Series:
    values = [
        (
            pd.Period(item.trade_date, freq="M"),
            item.adj_close if item.adj_close is not None else item.close,
        )
        for item in sorted(records, key=lambda item: item.trade_date)
        if item.close is not None or item.adj_close is not None
    ]
    if not values:
        return pd.Series(dtype="float64")
    frame = pd.DataFrame(values, columns=["month", "close"])
    monthly_close = frame.groupby("month", sort=True)["close"].last()
    return monthly_close.pct_change(fill_method=None).dropna()


def _change_from_period(
    values: pd.Series,
    target: pd.Period,
    latest_value: float,
) -> float | None:
    eligible = values[values.index <= target]
    if eligible.empty:
        return None
    change = latest_value - float(eligible.iloc[-1])
    return change if math.isfinite(change) else None


def _direction(change: float | None) -> MacroCycleDirection:
    if change is None:
        return MacroCycleDirection.UNKNOWN
    if math.isclose(change, 0.0, abs_tol=1e-12):
        return MacroCycleDirection.STABLE
    return MacroCycleDirection.RISING if change > 0.0 else MacroCycleDirection.FALLING


def _aggregate_status(
    statuses: tuple[SectorCapabilityStatus, ...],
) -> SectorCapabilityStatus:
    if not statuses or all(item is SectorCapabilityStatus.MISSING for item in statuses):
        return SectorCapabilityStatus.MISSING
    if all(item is SectorCapabilityStatus.AVAILABLE for item in statuses):
        return SectorCapabilityStatus.AVAILABLE
    return SectorCapabilityStatus.PARTIAL


def _validate_inputs(
    *,
    universe: SectorUniverseSnapshot,
    sector_state: SectorResearchSnapshot,
    benchmark_bars: Sequence[EodBarRecord],
    macro_observations: Sequence[MacroObservationRecord],
) -> None:
    if (universe.sector_id, universe.as_of) != (
        sector_state.sector_id,
        sector_state.as_of,
    ):
        raise SectorMacroInputError("Sector universe and state identities differ")
    cutoff = datetime.combine(universe.as_of, time.max, tzinfo=UTC)
    benchmark_ids = {str(item) for item in universe.benchmark_ids}
    for bar_record in benchmark_bars:
        if str(bar_record.asset_id) not in benchmark_ids:
            raise SectorMacroInputError("benchmark bar asset is outside Sector mapping")
        if bar_record.trade_date > universe.as_of:
            raise SectorMacroInputError("future benchmark observation is not allowed")
        _require_known_by(bar_record.ingestion_ts, cutoff, "benchmark")
    for macro_record in macro_observations:
        if macro_record.observation_date > universe.as_of:
            raise SectorMacroInputError("future macro observation is not allowed")
        if (
            macro_record.realtime_start is not None
            and macro_record.realtime_start > universe.as_of
        ):
            raise SectorMacroInputError("future macro vintage is not allowed")
        _require_known_by(macro_record.ingestion_ts, cutoff, "macro")


def _require_known_by(value: datetime, cutoff: datetime, label: str) -> None:
    observed = (
        value.replace(tzinfo=UTC)
        if value.tzinfo is None or value.utcoffset() is None
        else value.astimezone(UTC)
    )
    if observed > cutoff:
        raise SectorMacroInputError(f"future {label} ingestion is not allowed")


def _snapshot_id(content: Mapping[str, object]) -> str:
    payload = json.dumps(content, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"sector_macro_{digest}"
