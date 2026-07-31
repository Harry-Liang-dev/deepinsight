"""Deterministic Phase One technical feature computation."""

from __future__ import annotations

from typing import cast

import pandas as pd  # type: ignore[import-untyped]

from src.models.types import JsonObject

_OUTPUT_KEYS = ("close", "sma_20", "sma_60", "ret_20d", "trend_label")


class TechnicalFeatureOperator:
    """Compute the exact MVP moving-average and return feature set."""

    def compute(self, bars: pd.DataFrame) -> JsonObject:
        """Compute technical features without LLM inference.

        Args:
            bars: Frame containing at least ``trade_date`` and ``close``.

        Returns:
            JSON-compatible features plus explicit missing-data labels.

        Raises:
            ValueError: If required columns are absent.
        """

        required = {"trade_date", "close"}
        missing_columns = sorted(required - set(bars.columns))
        if missing_columns:
            raise ValueError(
                f"technical bars are missing columns: {', '.join(missing_columns)}"
            )
        if bars.empty:
            return {
                **{key: None for key in _OUTPUT_KEYS},
                "missing_data": ["bars"],
            }

        ordered = bars.loc[:, ["trade_date", "close"]].copy()
        ordered["trade_date"] = pd.to_datetime(
            ordered["trade_date"],
            errors="coerce",
        )
        ordered["close"] = pd.to_numeric(ordered["close"], errors="coerce")
        ordered = ordered.dropna(subset=["trade_date"]).sort_values(
            "trade_date",
            kind="stable",
        )
        if ordered.empty:
            return {
                **{key: None for key in _OUTPUT_KEYS},
                "missing_data": ["valid_trade_dates"],
            }

        close = ordered["close"]
        ordered["sma_20"] = close.rolling(20, min_periods=20).mean()
        ordered["sma_60"] = close.rolling(60, min_periods=60).mean()
        ordered["ret_20d"] = close.pct_change(20, fill_method=None)
        latest = ordered.iloc[-1]

        close_value = _finite_or_none(latest["close"])
        sma_20 = _finite_or_none(latest["sma_20"])
        sma_60 = _finite_or_none(latest["sma_60"])
        ret_20d = _finite_or_none(latest["ret_20d"])
        trend_label: str | None = None
        if sma_20 is not None and sma_60 is not None:
            trend_label = "up" if sma_20 > sma_60 else "down_or_flat"

        feature_values: dict[str, float | str | None] = {
            "close": close_value,
            "sma_20": sma_20,
            "sma_60": sma_60,
            "ret_20d": ret_20d,
            "trend_label": trend_label,
        }
        missing_data = [key for key, value in feature_values.items() if value is None]
        return cast(
            JsonObject,
            {
                **feature_values,
                "missing_data": missing_data,
            },
        )


def _finite_or_none(value: object) -> float | None:
    if pd.isna(value):
        return None
    numeric = float(cast(float, value))
    return numeric if pd.notna(numeric) else None
