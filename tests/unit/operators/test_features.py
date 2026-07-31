"""Tests for deterministic Phase One numeric operators."""

from __future__ import annotations

import pandas as pd  # type: ignore[import-untyped]
import pytest

from src.operators import FundamentalFeatureOperator, TechnicalFeatureOperator

FUNDAMENTAL_COLUMNS = [
    "fiscal_period_end",
    "report_type",
    "revenue",
    "net_income",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "roe",
    "roa",
    "debt_to_equity",
    "current_ratio",
    "pe_ttm",
    "pb",
]


def test_technical_features_are_sorted_and_deterministic() -> None:
    """Sixty observations should produce all specified technical features."""

    bars = pd.DataFrame(
        {
            "trade_date": pd.date_range("2026-01-01", periods=60)[::-1],
            "close": list(range(60, 0, -1)),
        }
    )

    result = TechnicalFeatureOperator().compute(bars)

    assert result["close"] == 60.0
    assert result["sma_20"] == pytest.approx(50.5)
    assert result["sma_60"] == pytest.approx(30.5)
    assert result["ret_20d"] == pytest.approx(0.5)
    assert result["trend_label"] == "up"
    assert result["missing_data"] == []


def test_technical_features_expose_empty_missing_and_short_history() -> None:
    """Empty, missing, and short inputs must not fabricate trend values."""

    operator = TechnicalFeatureOperator()
    empty = operator.compute(pd.DataFrame(columns=["trade_date", "close"]))
    short = operator.compute(
        pd.DataFrame(
            {
                "trade_date": pd.date_range("2026-01-01", periods=10),
                "close": [float(index) for index in range(10)],
            }
        )
    )

    assert empty["missing_data"] == ["bars"]
    assert empty["trend_label"] is None
    assert short["sma_20"] is None
    assert short["sma_60"] is None
    assert short["ret_20d"] is None
    assert short["trend_label"] is None
    with pytest.raises(ValueError, match="missing columns"):
        operator.compute(pd.DataFrame({"close": [1.0]}))


def test_fundamental_features_compute_growth_and_latest_values() -> None:
    """Comparable periods should produce deterministic growth and snapshots."""

    fundamentals = pd.DataFrame(
        [
            {
                "fiscal_period_end": "2025-06-30",
                "report_type": "interim",
                "revenue": 100.0,
                "net_income": 20.0,
                "gross_margin": 0.40,
                "operating_margin": 0.20,
                "net_margin": 0.20,
                "roe": 0.12,
                "roa": 0.08,
                "debt_to_equity": 0.30,
                "current_ratio": 1.5,
                "pe_ttm": 20.0,
                "pb": 3.0,
            },
            {
                "fiscal_period_end": "2026-06-30",
                "report_type": "interim",
                "revenue": 110.0,
                "net_income": 22.0,
                "gross_margin": 0.42,
                "operating_margin": 0.21,
                "net_margin": 0.20,
                "roe": 0.13,
                "roa": 0.09,
                "debt_to_equity": 0.28,
                "current_ratio": 1.6,
                "pe_ttm": 21.0,
                "pb": 3.1,
            },
        ]
    )

    result = FundamentalFeatureOperator().compute(fundamentals.iloc[::-1])

    assert result["revenue_yoy"] == pytest.approx(0.1)
    assert result["net_income_yoy"] == pytest.approx(0.1)
    assert result["gross_margin"] == pytest.approx(0.42)
    assert result["pe_ttm"] == pytest.approx(21.0)
    assert result["missing_data"] == []


def test_fundamental_features_expose_missing_history_values_and_zero_base() -> None:
    """Insufficient history and a zero denominator should return explicit nulls."""

    row = {
        "fiscal_period_end": "2026-06-30",
        "report_type": "interim",
        "revenue": 110.0,
        "net_income": 22.0,
        "gross_margin": None,
        "operating_margin": 0.21,
        "net_margin": 0.20,
        "roe": 0.13,
        "roa": 0.09,
        "debt_to_equity": 0.28,
        "current_ratio": 1.6,
        "pe_ttm": 21.0,
        "pb": 3.1,
    }
    operator = FundamentalFeatureOperator()
    short = operator.compute(pd.DataFrame([row]))
    zero_base = operator.compute(
        pd.DataFrame(
            [
                {
                    **row,
                    "fiscal_period_end": "2025-06-30",
                    "revenue": 0.0,
                    "net_income": 0.0,
                },
                row,
            ]
        )
    )
    empty = operator.compute(pd.DataFrame(columns=FUNDAMENTAL_COLUMNS))

    assert short["revenue_yoy"] is None
    assert short["gross_margin"] is None
    missing_data = short["missing_data"]
    assert isinstance(missing_data, list)
    assert set(item for item in missing_data if isinstance(item, str)) >= {
        "revenue_yoy",
        "gross_margin",
    }
    assert zero_base["revenue_yoy"] is None
    assert zero_base["net_income_yoy"] is None
    assert empty["missing_data"] == ["fundamentals"]
    with pytest.raises(ValueError, match="missing columns"):
        operator.compute(pd.DataFrame({"revenue": [1.0]}))
