"""Run an opt-in Alpaca US:AAPL Provider-only live smoke test."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from src.adapters import AlpacaAdapter, ProviderUnavailableError
from src.core import load_settings
from src.schemas import EodBarRecord
from src.services import DataNormalizer

_ASSET_ID = "US:AAPL"


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def _parser() -> argparse.ArgumentParser:
    today = datetime.now(UTC).date()
    end_date = today - timedelta(days=1)
    parser = argparse.ArgumentParser(
        description="Fetch official Alpaca US:AAPL daily bars without running Agents."
    )
    parser.add_argument(
        "--start-date",
        type=_iso_date,
        default=end_date - timedelta(days=90),
    )
    parser.add_argument(
        "--end-date",
        type=_iso_date,
        default=end_date,
    )
    return parser


def _safe_result(
    records: Sequence[EodBarRecord],
) -> dict[str, object]:
    dates = sorted(record.trade_date.isoformat() for record in records)
    return {
        "status": "ok",
        "bar_count": len(records),
        "first_date": dates[0],
        "last_date": dates[-1],
        "source_id": records[0].source_id,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the manual live check and return a process exit code."""

    args = _parser().parse_args(argv)
    settings = load_settings().providers
    key_id = settings.alpaca_api_key_id
    secret_key = settings.alpaca_api_secret_key
    if key_id is None or secret_key is None:
        print(
            json.dumps(
                {
                    "status": "not_configured",
                    "message": ("APCA_API_KEY_ID and APCA_API_SECRET_KEY are required"),
                },
                sort_keys=True,
            )
        )
        return 2
    if args.end_date < args.start_date:
        print(
            json.dumps(
                {
                    "status": "configuration_error",
                    "message": "end-date cannot precede start-date",
                },
                sort_keys=True,
            )
        )
        return 2

    try:
        adapter = AlpacaAdapter(
            api_key_id=key_id.get_secret_value(),
            api_secret_key=secret_key.get_secret_value(),
            api_base_url=settings.alpaca_api_base_url,
            user_agent=settings.alpaca_user_agent,
            request_timeout=settings.alpaca_request_timeout_seconds,
            max_retries=settings.alpaca_max_retries,
            requests_per_minute=settings.alpaca_requests_per_minute,
            backoff_base_seconds=settings.alpaca_backoff_base_seconds,
            max_backoff_seconds=settings.alpaca_max_backoff_seconds,
            feed=settings.alpaca_feed,
            adjustment=settings.alpaca_adjustment,
            page_limit=settings.alpaca_page_limit,
            max_pages=settings.alpaca_max_pages,
        )
        raw_records = list(
            adapter.fetch_eod_bars_range(
                [_ASSET_ID],
                args.start_date,
                args.end_date,
            )
        )
        if not raw_records:
            raise ProviderUnavailableError(
                "Alpaca smoke returned no US:AAPL daily bars"
            )
        normalizer = DataNormalizer()
        records = [
            normalizer.normalize_eod_bar(adapter.provider_name, raw)
            for raw in raw_records
        ]
        print(
            json.dumps(
                _safe_result(records),
                sort_keys=True,
            )
        )
        return 0
    except (ProviderUnavailableError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "provider_error",
                    "source_id": "alpaca_market_data",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
