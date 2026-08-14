"""Run an opt-in SEC EDGAR Provider-only live smoke test."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta

from src.adapters import ProviderUnavailableError, SECEDGARAdapter
from src.core import load_settings


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Fetch one bounded official SEC filing without running Agents.")
    )
    parser.add_argument("--asset-id", default="US:AAPL")
    parser.add_argument("--lookback-days", type=int, default=370)
    parser.add_argument("--start-date", type=_iso_date)
    parser.add_argument("--end-date", type=_iso_date)
    return parser


def _safe_result(
    *,
    asset_id: str,
    instruments: Sequence[Mapping[str, object]],
    documents: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    document = documents[0]
    raw_text = document.get("raw_text")
    metadata = document.get("metadata")
    return {
        "status": "ok",
        "provider": "sec_edgar",
        "asset_id": asset_id,
        "instrument_count": len(instruments),
        "document_count": len(documents),
        "document_id": document.get("document_id"),
        "publish_ts": document.get("publish_ts"),
        "source_url": document.get("source_url"),
        "provider_locator": (
            metadata.get("provider_locator") if isinstance(metadata, dict) else None
        ),
        "raw_text_chars": len(raw_text) if isinstance(raw_text, str) else 0,
        "raw_text_sha256": (
            hashlib.sha256(raw_text.encode()).hexdigest()
            if isinstance(raw_text, str)
            else None
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the manual live check and return a process exit code."""

    args = _parser().parse_args(argv)
    settings = load_settings().providers
    user_agent = settings.sec_user_agent
    if user_agent is None or not user_agent.strip():
        print(
            json.dumps(
                {
                    "status": "configuration_error",
                    "message": (
                        "DEEPINSIGHT_PROVIDER_SEC_USER_AGENT is required; "
                        "use 'Application monitored-contact@example.com'"
                    ),
                },
                sort_keys=True,
            )
        )
        return 2
    if args.lookback_days <= 0:
        print(
            json.dumps(
                {
                    "status": "configuration_error",
                    "message": "lookback-days must be positive",
                },
                sort_keys=True,
            )
        )
        return 2
    if (args.start_date is None) is not (args.end_date is None):
        print(
            json.dumps(
                {
                    "status": "configuration_error",
                    "message": "start-date and end-date must be supplied together",
                },
                sort_keys=True,
            )
        )
        return 2
    if (
        args.start_date is not None
        and args.end_date is not None
        and args.end_date < args.start_date
    ):
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
    cik = settings.sec_cik_map.get(args.asset_id.upper())
    if cik is None or not cik.strip():
        print(
            json.dumps(
                {
                    "status": "configuration_error",
                    "message": (
                        "DEEPINSIGHT_PROVIDER_SEC_CIK_MAP must map "
                        f"{args.asset_id.upper()} to its SEC CIK"
                    ),
                },
                sort_keys=True,
            )
        )
        return 2

    adapter = SECEDGARAdapter(
        user_agent=user_agent,
        cik_by_asset={args.asset_id: cik},
        request_timeout=settings.sec_request_timeout_seconds,
        max_retries=settings.sec_max_retries,
        requests_per_second=settings.sec_requests_per_second,
        backoff_base_seconds=settings.sec_backoff_base_seconds,
        max_backoff_seconds=settings.sec_max_backoff_seconds,
        max_documents=1,
    )
    end_date = args.end_date or datetime.now(UTC).date()
    start_date = args.start_date or (end_date - timedelta(days=args.lookback_days))
    try:
        instruments = list(adapter.fetch_instruments())
        documents = list(
            adapter.fetch_documents(
                [args.asset_id],
                start_date,
                end_date,
            )
        )
        if not instruments or not documents:
            raise ProviderUnavailableError("SEC smoke returned no instrument or filing")
        print(
            json.dumps(
                _safe_result(
                    asset_id=args.asset_id,
                    instruments=instruments,
                    documents=documents,
                ),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    except (ProviderUnavailableError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "provider_error",
                    "provider": "sec_edgar",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "checked_at": date.today().isoformat(),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
