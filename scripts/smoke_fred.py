"""Run an opt-in FRED/ALFRED US Macro Pack live smoke."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from src.adapters import FREDAdapter, ProviderUnavailableError
from src.core import load_settings
from src.services import DataNormalizer, NormalizationError


def main(argv: Sequence[str] | None = None) -> int:
    """Fetch recent approved observations without printing the API key."""

    del argv
    settings = load_settings().providers
    if settings.fred_api_key is None:
        print(
            json.dumps(
                {"status": "not_configured", "message": "FRED_API_KEY is required"}
            )
        )
        return 2
    end = datetime.now(UTC).date()
    start = end - timedelta(days=400)
    adapter = FREDAdapter(
        api_key=settings.fred_api_key.get_secret_value(),
        user_agent=settings.fred_user_agent,
        request_timeout=settings.fred_request_timeout_seconds,
        max_retries=settings.fred_max_retries,
        requests_per_second=settings.fred_requests_per_second,
        backoff_base_seconds=settings.fred_backoff_base_seconds,
        max_backoff_seconds=settings.fred_max_backoff_seconds,
    )
    normalizer = DataNormalizer()
    try:
        records = [
            normalizer.normalize_macro_observation(adapter.provider_name, raw)
            for raw in adapter.fetch_macro_series((), start, end, end)
        ]
        series = sorted({record.series_key for record in records})
        print(
            json.dumps(
                {
                    "status": "ok",
                    "provider": adapter.provider_name,
                    "observation_count": len(records),
                    "series_available": series,
                    "series_missing": sorted(set(adapter.DEFAULT_SERIES) - set(series)),
                    "as_of": end.isoformat(),
                },
                sort_keys=True,
            )
        )
        return 0
    except (ProviderUnavailableError, NormalizationError, ValueError) as exc:
        print(
            json.dumps(
                {"status": "provider_error", "provider": "fred", "message": str(exc)},
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
