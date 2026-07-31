"""Deterministic Phase One fundamental feature computation."""

from __future__ import annotations

from typing import cast

import pandas as pd  # type: ignore[import-untyped]

from src.models.types import JsonObject

_LATEST_FIELDS = (
    "gross_margin",
    "operating_margin",
    "net_margin",
    "roe",
    "roa",
    "debt_to_equity",
    "current_ratio",
    "pe_ttm",
    "pb",
)
_OUTPUT_KEYS = ("revenue_yoy", "net_income_yoy", *_LATEST_FIELDS)


class FundamentalFeatureOperator:
    """Compute deterministic growth, quality, leverage, and valuation inputs."""

    def compute(self, fundamentals: pd.DataFrame) -> JsonObject:
        """Compute the minimum MVP fundamental feature set.

        Growth compares the latest observation with the observation having the
        same ``report_type`` and fiscal date one calendar year earlier.

        Args:
            fundamentals: Frame of normalized fundamental observations.

        Returns:
            JSON-compatible features plus explicit missing-data labels.

        Raises:
            ValueError: If required identity or calculation columns are absent.
        """

        required = {
            "fiscal_period_end",
            "report_type",
            "revenue",
            "net_income",
            *_LATEST_FIELDS,
        }
        missing_columns = sorted(required - set(fundamentals.columns))
        if missing_columns:
            raise ValueError(
                "fundamentals are missing columns: " + ", ".join(missing_columns)
            )
        if fundamentals.empty:
            return {
                **{key: None for key in _OUTPUT_KEYS},
                "missing_data": ["fundamentals"],
            }

        ordered = fundamentals.loc[:, sorted(required)].copy()
        ordered["fiscal_period_end"] = pd.to_datetime(
            ordered["fiscal_period_end"],
            errors="coerce",
        )
        numeric_columns = {"revenue", "net_income", *_LATEST_FIELDS}
        for column in numeric_columns:
            ordered[column] = pd.to_numeric(ordered[column], errors="coerce")
        ordered = ordered.dropna(subset=["fiscal_period_end", "report_type"])
        ordered = ordered.sort_values("fiscal_period_end", kind="stable")
        if ordered.empty:
            return {
                **{key: None for key in _OUTPUT_KEYS},
                "missing_data": ["valid_fundamental_periods"],
            }

        latest = ordered.iloc[-1]
        prior_period = latest["fiscal_period_end"] - pd.DateOffset(years=1)
        comparable = ordered[
            (ordered["report_type"] == latest["report_type"])
            & (ordered["fiscal_period_end"] == prior_period)
        ]
        prior = None if comparable.empty else comparable.iloc[-1]

        features: dict[str, float | None] = {
            "revenue_yoy": _growth(
                latest["revenue"],
                None if prior is None else prior["revenue"],
            ),
            "net_income_yoy": _growth(
                latest["net_income"],
                None if prior is None else prior["net_income"],
            ),
        }
        features.update(
            {field: _finite_or_none(latest[field]) for field in _LATEST_FIELDS}
        )
        missing_data = [key for key, value in features.items() if value is None]
        return cast(
            JsonObject,
            {
                **features,
                "missing_data": missing_data,
            },
        )


def _growth(current: object, prior: object) -> float | None:
    current_value = _finite_or_none(current)
    prior_value = _finite_or_none(prior)
    if current_value is None or prior_value is None or prior_value == 0.0:
        return None
    return current_value / prior_value - 1.0


def _finite_or_none(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    numeric = float(cast(float, value))
    return numeric if pd.notna(numeric) else None
