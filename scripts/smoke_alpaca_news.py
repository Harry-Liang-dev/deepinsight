"""Run an opt-in attributed Alpaca News live smoke for US:AAPL."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from src.adapters import AlpacaAdapter, ProviderUnavailableError
from src.core import load_settings
from src.services import DataNormalizer, NormalizationError


def main(argv: Sequence[str] | None = None) -> int:
    """Fetch recent news and output only safe attribution metadata."""

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
    end = datetime.now(UTC).date()
    start = end - timedelta(days=14)
    adapter = AlpacaAdapter(
        api_key_id=key.get_secret_value(),
        api_secret_key=secret.get_secret_value(),
        api_base_url=settings.alpaca_api_base_url,
        feed=settings.alpaca_feed,
        news_page_limit=settings.alpaca_news_page_limit,
        include_news_content=False,
    )
    normalizer = DataNormalizer()
    try:
        records = [
            normalizer.normalize_news_evidence(adapter.provider_name, raw)
            for raw in adapter.fetch_documents(["US:AAPL"], start, end)
        ]
        print(
            json.dumps(
                {
                    "status": "ok",
                    "provider": adapter.provider_name,
                    "news_count": len(records),
                    "first_date": min(
                        (record.created_at.date().isoformat() for record in records),
                        default=None,
                    ),
                    "last_date": max(
                        (record.created_at.date().isoformat() for record in records),
                        default=None,
                    ),
                    "source_locators_present": all(
                        bool(record.source_locator) for record in records
                    ),
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
