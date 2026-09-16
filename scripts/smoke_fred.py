"""Run an opt-in FRED/ALFRED US Macro Pack live smoke."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from src.adapters import FREDAdapter, ProviderUnavailableError
from src.core import load_settings
from src.services import DataNormalizer, NormalizationError


def _parse_research_as_of(value: str) -> date | datetime:
    if "T" not in value:
        return date.fromisoformat(value)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("research-as-of must be timezone-aware")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the official FRED/ALFRED Macro Pack preflight."
    )
    parser.add_argument("--research-as-of", type=_parse_research_as_of)
    parser.add_argument("--observation-start", type=date.fromisoformat)
    parser.add_argument("--observation-end", type=date.fromisoformat)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Fetch recent approved observations without printing the API key."""

    args = _parser().parse_args(argv)
    settings = load_settings().providers
    if settings.fred_api_key is None:
        print(
            json.dumps(
                {"status": "not_configured", "message": "FRED_API_KEY is required"}
            )
        )
        return 2
    research_as_of = args.research_as_of or datetime.now(UTC)
    global_cutoff_date = (
        research_as_of.astimezone(UTC).date()
        if isinstance(research_as_of, datetime)
        else research_as_of
    )
    end = args.observation_end or global_cutoff_date
    start = args.observation_start or end - timedelta(days=400)
    provider_cutoff = FREDAdapter.provider_realtime_cutoff(research_as_of)
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
            normalizer.normalize_macro_observation(
                adapter.provider_name,
                raw,
                received_at=datetime.now(UTC),
            )
            for raw in adapter.fetch_macro_series(
                (),
                start,
                end,
                research_as_of,
            )
        ]
        series = sorted({record.series_key for record in records})
        latest_observation_by_series = {
            series_id: max(
                record.observation_date
                for record in records
                if record.series_key == series_id
            ).isoformat()
            for series_id in series
        }
        realtime_pairs = sorted(
            {
                (
                    record.realtime_start.isoformat(),
                    record.realtime_end.isoformat(),
                )
                for record in records
                if record.realtime_start is not None and record.realtime_end is not None
            }
        )
        future_leakage_count = sum(
            1
            for record in records
            if record.realtime_start is None
            or record.realtime_end is None
            or record.realtime_start > provider_cutoff
            or record.realtime_end > provider_cutoff
        )
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "provider": adapter.provider_name,
                    "global_research_as_of": research_as_of.isoformat(),
                    "fred_provider_cutoff_date": provider_cutoff.isoformat(),
                    "provider_timezone": adapter.PROVIDER_TIMEZONE,
                    "realtime_semantics": adapter.REALTIME_SEMANTICS_VERSION,
                    "realtime_precision": "date",
                    "observation_start": start.isoformat(),
                    "observation_end": end.isoformat(),
                    "observation_count": len(records),
                    "series_count": len(series),
                    "series_available": series,
                    "series_missing": sorted(set(adapter.DEFAULT_SERIES) - set(series)),
                    "latest_observation_by_series": latest_observation_by_series,
                    "latest_realtime_metadata": realtime_pairs,
                    "future_leakage_count": future_leakage_count,
                    "http_error": None,
                },
                sort_keys=True,
            )
        )
        return 0 if future_leakage_count == 0 else 1
    except (ProviderUnavailableError, NormalizationError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "provider_error",
                    "provider": "fred",
                    "global_research_as_of": research_as_of.isoformat(),
                    "fred_provider_cutoff_date": provider_cutoff.isoformat(),
                    "message": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
