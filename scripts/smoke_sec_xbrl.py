"""Run an opt-in SEC Company Facts normalization smoke test."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from src.adapters import ProviderUnavailableError, SECEDGARAdapter
from src.core import load_settings
from src.services import DataNormalizer, NormalizationError


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch and normalize bounded official SEC Company Facts without Agents."
        )
    )
    parser.add_argument("--asset-id", default="US:AAPL")
    parser.add_argument("--lookback-days", type=int, default=740)
    parser.add_argument("--start-date", type=_iso_date)
    parser.add_argument("--end-date", type=_iso_date)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the manual live check without printing credential values."""

    args = _parser().parse_args(argv)
    settings = load_settings().providers
    error = _configuration_error(args, settings.sec_user_agent)
    if error is not None:
        print(json.dumps(error, sort_keys=True))
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

    end_date = args.end_date or datetime.now(UTC).date()
    start_date = args.start_date or (end_date - timedelta(days=args.lookback_days))
    adapter = SECEDGARAdapter(
        user_agent=settings.sec_user_agent or "",
        cik_by_asset={args.asset_id: cik},
        request_timeout=settings.sec_request_timeout_seconds,
        max_retries=settings.sec_max_retries,
        requests_per_second=settings.sec_requests_per_second,
        backoff_base_seconds=settings.sec_backoff_base_seconds,
        max_backoff_seconds=settings.sec_max_backoff_seconds,
        max_documents=1,
    )
    normalizer = DataNormalizer()
    checked_at = datetime.now(UTC)
    try:
        records = [
            normalizer.normalize_fundamental(
                adapter.provider_name,
                raw,
                received_at=checked_at,
            )
            for raw in adapter.fetch_fundamentals_range(
                [args.asset_id],
                start_date,
                end_date,
            )
        ]
        if not records:
            raise ProviderUnavailableError(
                "SEC Company Facts smoke returned no mapped fundamentals"
            )
        records.sort(key=lambda item: (item.fiscal_period_end, item.report_type))
        populated_fields = sorted(
            {
                field
                for record in records
                for field in _SMOKE_FIELDS
                if getattr(record, field) is not None
            }
        )
        print(
            json.dumps(
                {
                    "status": "ok",
                    "provider": adapter.provider_name,
                    "asset_id": args.asset_id.upper(),
                    "fundamental_count": len(records),
                    "first_period": records[0].fiscal_period_end.isoformat(),
                    "last_period": records[-1].fiscal_period_end.isoformat(),
                    "source_id": records[-1].source_id,
                    "populated_fields": populated_fields,
                    "checked_at": checked_at.isoformat(),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    except (ProviderUnavailableError, NormalizationError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "provider_error",
                    "provider": "sec_edgar",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "checked_at": checked_at.isoformat(),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1


def _configuration_error(
    args: argparse.Namespace,
    user_agent: str | None,
) -> dict[str, object] | None:
    if user_agent is None or not user_agent.strip():
        return {
            "status": "configuration_error",
            "message": "DEEPINSIGHT_PROVIDER_SEC_USER_AGENT is required",
        }
    if args.lookback_days <= 0:
        return {
            "status": "configuration_error",
            "message": "lookback-days must be positive",
        }
    if (args.start_date is None) is not (args.end_date is None):
        return {
            "status": "configuration_error",
            "message": "start-date and end-date must be supplied together",
        }
    if (
        args.start_date is not None
        and args.end_date is not None
        and args.end_date < args.start_date
    ):
        return {
            "status": "configuration_error",
            "message": "end-date cannot precede start-date",
        }
    return None


_SMOKE_FIELDS = (
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "eps_basic",
    "total_assets",
    "total_liabilities",
    "shareholders_equity",
    "operating_cash_flow",
    "shares_outstanding",
)


if __name__ == "__main__":
    raise SystemExit(main())
