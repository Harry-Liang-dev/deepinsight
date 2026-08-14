"""Point-in-time deterministic fundamental feature computation."""

from __future__ import annotations

from typing import cast

import pandas as pd  # type: ignore[import-untyped]

from src.models.types import JsonObject

_OUTPUT_KEYS = (
    "revenue_yoy",
    "net_income_yoy",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "roe",
    "roa",
    "debt_to_equity",
    "current_ratio",
)


class FundamentalFeatureOperator:
    """Derive growth and accounting ratios from normalized SEC facts."""

    version = "fundamental_features_v2"

    def compute(self, fundamentals: pd.DataFrame) -> JsonObject:
        """Compute ratios only when their canonical inputs are available.

        Comparable growth uses the nearest same-form fiscal period within 45
        days of one calendar year earlier. This accommodates 52/53-week fiscal
        calendars without mixing annual and quarterly observations.
        """

        required = {"fiscal_period_end", "report_type", "revenue", "net_income"}
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

        ordered = fundamentals.copy()
        ordered["fiscal_period_end"] = pd.to_datetime(
            ordered["fiscal_period_end"], errors="coerce"
        )
        numeric_names = set(_OUTPUT_KEYS) | {
            "revenue",
            "gross_profit",
            "operating_income",
            "net_income",
            "total_assets",
            "shareholders_equity",
            "total_debt",
            "current_assets",
            "current_liabilities",
        }
        for name in numeric_names & set(ordered.columns):
            ordered[name] = pd.to_numeric(ordered[name], errors="coerce")
        ordered = ordered.dropna(subset=["fiscal_period_end", "report_type"])
        ordered = ordered.sort_values("fiscal_period_end", kind="stable")
        operating_rows = ordered[ordered[["revenue", "net_income"]].notna().any(axis=1)]
        if operating_rows.empty:
            return {
                **{key: None for key in _OUTPUT_KEYS},
                "missing_data": ["complete_fundamental_period"],
            }

        latest = operating_rows.iloc[-1]
        prior = _comparable_period(operating_rows, latest)
        annual_rows = operating_rows[
            operating_rows["report_type"].isin(("annual", "10-K"))
        ]
        annual = None if annual_rows.empty else annual_rows.iloc[-1]
        features: dict[str, float | None] = {
            "revenue_yoy": _growth(
                latest.get("revenue"), None if prior is None else prior.get("revenue")
            ),
            "net_income_yoy": _growth(
                latest.get("net_income"),
                None if prior is None else prior.get("net_income"),
            ),
            "gross_margin": _ratio_or_existing(
                latest, "gross_profit", "revenue", "gross_margin"
            ),
            "operating_margin": _ratio_or_existing(
                latest, "operating_income", "revenue", "operating_margin"
            ),
            "net_margin": _ratio_or_existing(
                latest, "net_income", "revenue", "net_margin"
            ),
            "roe": _annual_ratio_or_existing(
                annual, latest, "net_income", "shareholders_equity", "roe"
            ),
            "roa": _annual_ratio_or_existing(
                annual, latest, "net_income", "total_assets", "roa"
            ),
            "debt_to_equity": _latest_ratio_or_existing(
                ordered, "total_debt", "shareholders_equity", "debt_to_equity"
            ),
            "current_ratio": _latest_ratio_or_existing(
                ordered, "current_assets", "current_liabilities", "current_ratio"
            ),
        }
        return cast(
            JsonObject,
            {
                **features,
                "missing_data": [
                    key for key, value in features.items() if value is None
                ],
            },
        )


def _comparable_period(records: pd.DataFrame, latest: pd.Series) -> pd.Series | None:
    target = latest["fiscal_period_end"] - pd.DateOffset(years=1)
    candidates = records[
        (records["report_type"] == latest["report_type"])
        & (records["fiscal_period_end"] < latest["fiscal_period_end"])
    ].copy()
    if candidates.empty:
        return None
    candidates["distance"] = (candidates["fiscal_period_end"] - target).abs()
    candidates = candidates[candidates["distance"] <= pd.Timedelta(days=45)]
    return None if candidates.empty else candidates.sort_values("distance").iloc[0]


def _ratio_or_existing(
    row: pd.Series, numerator: str, denominator: str, existing: str
) -> float | None:
    ratio = _ratio(row.get(numerator), row.get(denominator))
    return ratio if ratio is not None else _finite_or_none(row.get(existing))


def _annual_ratio_or_existing(
    row: pd.Series | None,
    latest: pd.Series,
    numerator: str,
    denominator: str,
    existing: str,
) -> float | None:
    if row is not None:
        return _ratio_or_existing(row, numerator, denominator, existing)
    # A Provider-supplied normalized ratio remains usable, but an interim
    # income statement is never silently annualized by this operator.
    return _finite_or_none(latest.get(existing))


def _latest_ratio_or_existing(
    records: pd.DataFrame, numerator: str, denominator: str, existing: str
) -> float | None:
    for _, row in records.iloc[::-1].iterrows():
        result = _ratio_or_existing(row, numerator, denominator, existing)
        if result is not None:
            return result
    return None


def _ratio(numerator: object, denominator: object) -> float | None:
    top = _finite_or_none(numerator)
    bottom = _finite_or_none(denominator)
    if top is None or bottom is None or bottom == 0.0:
        return None
    return top / bottom


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
