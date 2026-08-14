"""Run opt-in Alpaca Basic benchmark-context smoke for US:AAPL."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from src.adapters import AlpacaAdapter, ProviderUnavailableError
from src.core import load_settings
from src.operators import MarketContextOperator
from src.services import DataNormalizer, NormalizationError


def main(argv: Sequence[str] | None = None) -> int:
    """Fetch AAPL/SPY/QQQ/XLK bars and compute deterministic context."""

    del argv
    settings = load_settings().providers
    key = settings.alpaca_api_key_id
    secret = settings.alpaca_api_secret_key
    if key is None or secret is None:
        print(
            json.dumps(
                {
                    "status": "not_configured",
                    "message": "Alpaca credentials are required",
                }
            )
        )
        return 2
    assets = ["US:AAPL", "US:SPY", "US:QQQ", "US:XLK"]
    end = datetime.now(UTC).date()
    start = end - timedelta(days=90)
    adapter = AlpacaAdapter(
        api_key_id=key.get_secret_value(),
        api_secret_key=secret.get_secret_value(),
        api_base_url=settings.alpaca_api_base_url,
        feed=settings.alpaca_feed,
    )
    normalizer = DataNormalizer()
    try:
        records = [
            normalizer.normalize_eod_bar(adapter.provider_name, raw)
            for raw in adapter.fetch_eod_bars_range(assets, start, end)
        ]
        grouped = {
            asset: [record for record in records if str(record.asset_id) == asset]
            for asset in assets
        }
        values = MarketContextOperator().compute(
            grouped,
            target_asset="US:AAPL",
            market_benchmark="US:SPY",
            growth_benchmark="US:QQQ",
            sector_benchmark="US:XLK",
        )
        print(
            json.dumps(
                {
                    "status": "ok",
                    "provider": adapter.provider_name,
                    "feed_identity": settings.alpaca_feed,
                    "coverage_scope": (
                        grouped["US:AAPL"][0].coverage_scope
                        if grouped["US:AAPL"]
                        else None
                    ),
                    "bar_counts": {asset: len(grouped[asset]) for asset in assets},
                    "features": values,
                },
                sort_keys=True,
            )
        )
        return 0
    except (ProviderUnavailableError, NormalizationError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "provider_error",
                    "provider": "alpaca_market_data",
                    "message": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
