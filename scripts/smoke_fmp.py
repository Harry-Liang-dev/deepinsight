"""Run an opt-in FMP standardized-fundamentals smoke test."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from src.adapters import FinancialModelingPrepAdapter, ProviderUnavailableError
from src.core import load_settings
from src.services import DataNormalizer, NormalizationError

_METRICS = (
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


def main(argv: Sequence[str] | None = None) -> int:
    """Fetch one live AAPL standardized record without printing credentials."""

    parser = argparse.ArgumentParser(description="Smoke-test FMP Stable fundamentals")
    parser.add_argument("--asset-id", default="US:AAPL")
    parser.add_argument("--end-date", type=date.fromisoformat)
    args = parser.parse_args(argv)
    settings = load_settings().providers
    if not settings.fmp_enabled:
        print(json.dumps({"status": "not_configured", "reason": "FMP_ENABLED=false"}))
        return 2
    secret = settings.fmp_api_key
    if secret is None or not secret.get_secret_value().strip():
        print(json.dumps({"status": "not_configured", "reason": "FMP_API_KEY missing"}))
        return 2
    end = args.end_date or datetime.now(UTC).date()
    adapter = FinancialModelingPrepAdapter(
        api_key=secret.get_secret_value(),
        base_url=settings.fmp_base_url,
        user_agent=settings.fmp_user_agent,
        request_timeout=settings.fmp_request_timeout_seconds,
        max_retries=settings.fmp_max_retries,
        requests_per_second=settings.fmp_requests_per_second,
    )
    checked_at = datetime.now(UTC)
    try:
        raw = list(
            adapter.fetch_fundamentals_range(
                [args.asset_id], end - timedelta(days=740), end
            )
        )
        if not raw:
            raise ProviderUnavailableError("FMP returned no in-window record")
        record = DataNormalizer().normalize_fundamental(
            adapter.provider_name, raw[0], received_at=checked_at
        )
    except (ProviderUnavailableError, NormalizationError, ValueError) as exc:
        message = str(exc)
        availability = (
            "ENDPOINT_NOT_AVAILABLE_FREE" if "HTTP status 402" in message else "ERROR"
        )
        print(
            json.dumps(
                {
                    "status": "provider_error",
                    "provider": adapter.provider_name,
                    "availability": availability,
                    "error_type": type(exc).__name__,
                    "message": message,
                },
                sort_keys=True,
            )
        )
        return 1
    available = {
        name: getattr(record, name)
        for name in _METRICS
        if getattr(record, name) is not None
    }
    print(
        json.dumps(
            {
                "status": "ok",
                "provider": adapter.provider_name,
                "asset_id": str(record.asset_id),
                "reporting_period": record.fiscal_period_end.isoformat(),
                "provider_timestamp": (
                    record.accepted_at.isoformat()
                    if record.accepted_at is not None
                    else checked_at.isoformat()
                ),
                "available_metrics": available,
                "missing_metrics": sorted(set(_METRICS) - set(available)),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
