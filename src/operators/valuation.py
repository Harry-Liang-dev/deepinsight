"""Deterministic valuation features with strict missing-input semantics."""

from __future__ import annotations

from collections.abc import Sequence

from src.schemas.market_data import EodBarRecord, FundamentalRecord


class ValuationOperator:
    """Compute only valuation metrics supported by canonical inputs."""

    version = "valuation_v1"

    def compute(
        self,
        bars: Sequence[EodBarRecord],
        fundamentals: Sequence[FundamentalRecord],
    ) -> dict[str, float | None]:
        """Return missing values instead of estimates or silent defaults."""

        price = next(
            (
                float(record.close)
                for record in reversed(bars)
                if record.close is not None
            ),
            None,
        )
        shares = _latest_value(fundamentals, "shares_outstanding")
        equity = _latest_value(fundamentals, "shareholders_equity")
        market_cap = None if price is None or shares is None else price * float(shares)
        eps_ttm = _eps_ttm(fundamentals)
        pe = (
            None
            if price is None or eps_ttm is None or eps_ttm == 0.0
            else price / eps_ttm
        )
        pb = (
            None
            if market_cap is None or equity is None or equity == 0.0
            else market_cap / float(equity)
        )
        return {
            "market_cap": market_cap,
            "eps_ttm": eps_ttm,
            "book_value_per_share": (
                None
                if equity is None or shares is None or shares == 0.0
                else equity / shares
            ),
            "pe_ttm": pe,
            "pb": pb,
            "earnings_yield": None if pe is None or pe == 0.0 else 1.0 / pe,
        }


def _eps_ttm(records: Sequence[FundamentalRecord]) -> float | None:
    eps_records = [record for record in records if record.eps_basic is not None]
    if not eps_records:
        return None
    latest = eps_records[-1]
    if latest.report_type in {"annual", "10-K"}:
        assert latest.eps_basic is not None
        return float(latest.eps_basic)
    quarters = [
        record
        for record in eps_records
        if record.report_type in {"quarterly", "10-Q"} and record.eps_basic is not None
    ]
    if len(quarters) < 4:
        return None
    selected = quarters[-4:]
    if (selected[-1].fiscal_period_end - selected[0].fiscal_period_end).days > 400:
        return None
    total = 0.0
    for record in selected:
        assert record.eps_basic is not None
        total += float(record.eps_basic)
    return total


def _latest_value(
    records: Sequence[FundamentalRecord], field_name: str
) -> float | None:
    for record in reversed(records):
        value = getattr(record, field_name)
        if value is not None:
            return float(value)
    return None
