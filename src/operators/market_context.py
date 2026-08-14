"""Deterministic benchmark and sector-relative market context."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from src.schemas.market_data import EodBarRecord


class MarketContextOperator:
    """Compute low-frequency relative performance from canonical daily bars."""

    version = "market_context_v1"

    def compute(
        self,
        bars_by_asset: Mapping[str, Sequence[EodBarRecord]],
        *,
        target_asset: str,
        market_benchmark: str,
        growth_benchmark: str,
        sector_benchmark: str,
    ) -> dict[str, float | str | None]:
        """Return explicit missing values when any 20-session input is absent."""

        asset = _series(bars_by_asset.get(target_asset, ()))
        market = _series(bars_by_asset.get(market_benchmark, ()))
        growth = _series(bars_by_asset.get(growth_benchmark, ()))
        sector = _series(bars_by_asset.get(sector_benchmark, ()))
        asset_return = _return_20d(asset)
        market_return = _return_20d(market)
        growth_return = _return_20d(growth)
        sector_return = _return_20d(sector)
        return {
            "asset_return_20d": asset_return,
            "market_return_20d": market_return,
            "growth_return_20d": growth_return,
            "sector_return_20d": sector_return,
            "excess_return_vs_market": _difference(asset_return, market_return),
            "excess_return_vs_growth": _difference(asset_return, growth_return),
            "excess_return_vs_sector": _difference(asset_return, sector_return),
            "relative_strength_market": _relative(asset_return, market_return),
            "relative_strength_growth": _relative(asset_return, growth_return),
            "relative_strength_sector": _relative(asset_return, sector_return),
            "benchmark_trend": _trend(market),
            "market_volatility": _annualized_volatility(market),
            "sector_volatility": _annualized_volatility(sector),
        }


def _series(records: Sequence[EodBarRecord]) -> list[float]:
    return [float(record.close) for record in records if record.close is not None]


def _return_20d(values: Sequence[float]) -> float | None:
    if len(values) < 21 or values[-21] == 0:
        return None
    return values[-1] / values[-21] - 1.0


def _difference(left: float | None, right: float | None) -> float | None:
    return None if left is None or right is None else left - right


def _relative(left: float | None, right: float | None) -> float | None:
    if left is None or right is None or 1.0 + right == 0:
        return None
    return (1.0 + left) / (1.0 + right) - 1.0


def _trend(values: Sequence[float]) -> str | None:
    result = _return_20d(values)
    if result is None:
        return None
    return "up" if result > 0 else "down_or_flat"


def _annualized_volatility(values: Sequence[float]) -> float | None:
    if len(values) < 21:
        return None
    sample = values[-21:]
    returns = [sample[index] / sample[index - 1] - 1.0 for index in range(1, 21)]
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(252.0)
