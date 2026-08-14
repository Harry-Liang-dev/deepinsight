"""Deterministic price and volume research features."""

from __future__ import annotations

import math
from typing import cast

import pandas as pd  # type: ignore[import-untyped]

from src.models.types import JsonObject

_OUTPUT_KEYS = (
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
    "trend_label",
)


class TechnicalFeatureOperator:
    """Compute a bounded, deterministic OHLCV research feature set."""

    version = "technical_features_v2"

    def compute(self, bars: pd.DataFrame) -> JsonObject:
        """Compute point-in-time features without LLM inference.

        ``high``, ``low`` and ``volume`` are optional inputs. Their dependent
        indicators remain missing when the canonical observations are absent.
        """

        required = {"trade_date", "close"}
        missing_columns = sorted(required - set(bars.columns))
        if missing_columns:
            raise ValueError(
                f"technical bars are missing columns: {', '.join(missing_columns)}"
            )
        if bars.empty:
            return {**{key: None for key in _OUTPUT_KEYS}, "missing_data": ["bars"]}

        columns = [
            name
            for name in ("trade_date", "close", "high", "low", "volume")
            if name in bars.columns
        ]
        ordered = bars.loc[:, columns].copy()
        ordered["trade_date"] = pd.to_datetime(ordered["trade_date"], errors="coerce")
        for name in columns:
            if name != "trade_date":
                ordered[name] = pd.to_numeric(ordered[name], errors="coerce")
        ordered = ordered.dropna(subset=["trade_date"]).sort_values(
            "trade_date", kind="stable"
        )
        if ordered.empty:
            return {
                **{key: None for key in _OUTPUT_KEYS},
                "missing_data": ["valid_trade_dates"],
            }

        close = ordered["close"]
        returns = close.pct_change(fill_method=None)
        sma_20 = close.rolling(20, min_periods=20).mean()
        sma_60 = close.rolling(60, min_periods=60).mean()
        latest_close = _last(close)
        latest_sma20 = _last(sma_20)
        latest_sma60 = _last(sma_60)
        features: dict[str, float | str | None] = {
            "close": latest_close,
            "return_1d": _period_return(close, 1),
            "return_5d": _period_return(close, 5),
            "return_20d": _period_return(close, 20),
            "return_60d": _period_return(close, 60),
            "sma_20": latest_sma20,
            "sma_60": latest_sma60,
            "distance_to_sma20": _distance(latest_close, latest_sma20),
            "distance_to_sma60": _distance(latest_close, latest_sma60),
            "realized_vol_20d": _annualized_volatility(returns, 20),
            "realized_vol_60d": _annualized_volatility(returns, 60),
            "max_drawdown_60d": _max_drawdown(close, 60),
            "rsi_14": _rsi(close, 14),
            "atr_14": _atr(ordered, 14),
            "macd": (
                _last(close.ewm(span=12, adjust=False).mean())
                if close.notna().sum() >= 26
                else None
            ),
            "volume_ratio_20d": _volume_ratio(ordered, 20),
            "trend_label": None,
        }
        if features["macd"] is not None:
            slow = _last(close.ewm(span=26, adjust=False).mean())
            features["macd"] = None if slow is None else float(features["macd"]) - slow
        if latest_sma20 is not None and latest_sma60 is not None:
            features["trend_label"] = (
                "up" if latest_sma20 > latest_sma60 else "down_or_flat"
            )
        return cast(
            JsonObject,
            {
                **features,
                "missing_data": [
                    key for key, value in features.items() if value is None
                ],
            },
        )


def _last(series: pd.Series) -> float | None:
    return _finite_or_none(series.iloc[-1]) if not series.empty else None


def _period_return(close: pd.Series, sessions: int) -> float | None:
    if len(close) <= sessions:
        return None
    current = _finite_or_none(close.iloc[-1])
    prior = _finite_or_none(close.iloc[-sessions - 1])
    if current is None or prior is None or prior == 0.0:
        return None
    return current / prior - 1.0


def _distance(value: float | None, average: float | None) -> float | None:
    if value is None or average is None or average == 0.0:
        return None
    return value / average - 1.0


def _annualized_volatility(returns: pd.Series, sessions: int) -> float | None:
    sample = returns.iloc[-sessions:].dropna()
    if len(sample) < sessions:
        return None
    value = float(sample.std(ddof=1)) * math.sqrt(252.0)
    return value if math.isfinite(value) else None


def _max_drawdown(close: pd.Series, sessions: int) -> float | None:
    if len(close) < sessions:
        return None
    sample = close.iloc[-sessions:].dropna()
    if len(sample) < sessions:
        return None
    drawdown = sample / sample.cummax() - 1.0
    return _finite_or_none(drawdown.min())


def _rsi(close: pd.Series, sessions: int) -> float | None:
    if len(close) <= sessions:
        return None
    delta = close.diff().iloc[-sessions:]
    if delta.isna().any():
        return None
    gain = float(delta.clip(lower=0).mean())
    loss = float(-delta.clip(upper=0).mean())
    if loss == 0.0:
        return 100.0 if gain > 0.0 else 50.0
    return 100.0 - 100.0 / (1.0 + gain / loss)


def _atr(frame: pd.DataFrame, sessions: int) -> float | None:
    if not {"high", "low"}.issubset(frame.columns) or len(frame) <= sessions:
        return None
    previous_close = frame["close"].shift(1)
    ranges = pd.concat(
        (
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ),
        axis=1,
    ).max(axis=1)
    sample = ranges.iloc[-sessions:]
    return None if sample.isna().any() else _finite_or_none(sample.mean())


def _volume_ratio(frame: pd.DataFrame, sessions: int) -> float | None:
    if "volume" not in frame.columns or len(frame) < sessions:
        return None
    sample = frame["volume"].iloc[-sessions:]
    current = _finite_or_none(sample.iloc[-1])
    average = _finite_or_none(sample.mean())
    if current is None or average is None or average == 0.0:
        return None
    return current / average


def _finite_or_none(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    numeric = float(cast(float, value))
    return numeric if math.isfinite(numeric) else None
