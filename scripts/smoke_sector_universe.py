"""Run an opt-in real Alpaca validation of the Day31 US Sector Universe."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from src.adapters import AlpacaAdapter, ProviderUnavailableError
from src.core import load_settings
from src.models.enums import SectorId
from src.models.identifiers import AssetId
from src.repositories import DuckDBDatabase, SectorOntologyRepository
from src.services import (
    CURRENT_US_RESEARCH_UNIVERSE_VERSION,
    SectorOntologyService,
    SectorUniverseService,
    build_current_us_research_memberships_v1,
    build_us_sector_benchmark_candidates_v1,
    resolve_validated_benchmark_mappings,
)

_ASSET_IDS = tuple(
    AssetId(value) for value in ("US:AAPL", "US:NVDA", "US:AMD", "US:TSM", "US:MU")
)
_SECTORS = (
    SectorId.SEMICONDUCTORS_AI_COMPUTE,
    SectorId.MEMORY_STORAGE,
    SectorId.CONSUMER_ELECTRONICS_HARDWARE,
)


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def _parser() -> argparse.ArgumentParser:
    today = datetime.now(UTC).date()
    end_date = today - timedelta(days=1)
    parser = argparse.ArgumentParser(
        description="Validate the scoped US Sector Universe with real Alpaca bars."
    )
    parser.add_argument("--as-of", type=_iso_date, default=today)
    parser.add_argument(
        "--start-date", type=_iso_date, default=end_date - timedelta(days=30)
    )
    parser.add_argument("--end-date", type=_iso_date, default=end_date)
    parser.add_argument(
        "--output-root", type=Path, default=Path("data/live_sector_universe")
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the manual live check without exposing credentials."""

    args = _parser().parse_args(argv)
    settings = load_settings().providers
    key_id = settings.alpaca_api_key_id
    secret_key = settings.alpaca_api_secret_key
    if key_id is None or secret_key is None:
        print(
            json.dumps(
                {"status": "not_configured", "provider": "alpaca_market_data"},
                sort_keys=True,
            )
        )
        return 2
    if args.end_date < args.start_date:
        print(
            json.dumps(
                {"status": "configuration_error", "message": "invalid date range"},
                sort_keys=True,
            )
        )
        return 2

    candidates = build_us_sector_benchmark_candidates_v1()
    candidate_ids = {
        str(item): item for candidate in candidates for item in candidate.candidate_ids
    }
    requested_by_id = {str(item): item for item in _ASSET_IDS}
    requested_by_id.update(candidate_ids)
    requested_ids = [requested_by_id[key] for key in sorted(requested_by_id)]
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
        records = list(
            adapter.fetch_eod_bars_range(
                [str(item) for item in requested_ids],
                args.start_date,
                args.end_date,
            )
        )
        validated_ids = {
            str(AssetId(str(record["asset_id"])))
            for record in records
            if isinstance(record.get("asset_id"), str)
        }
        missing_assets = sorted(
            str(item) for item in _ASSET_IDS if str(item) not in validated_ids
        )
        if missing_assets:
            raise ProviderUnavailableError(
                "Alpaca returned no bars for required universe assets: "
                + ", ".join(missing_assets)
            )

        run_stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_dir = args.output_root / run_stamp
        run_dir.mkdir(parents=True, exist_ok=False)
        database_path = run_dir / "sector_universe.duckdb"
        database = DuckDBDatabase(database_path)
        database.bootstrap()
        repository = SectorOntologyRepository(database)
        SectorOntologyService(repository).install_v1_seed()
        for membership in build_current_us_research_memberships_v1():
            repository.add_membership(membership)
        mappings = resolve_validated_benchmark_mappings(
            candidates,
            validated_asset_ids=validated_ids,
            valid_from=args.as_of,
        )
        for mapping in mappings:
            repository.add_benchmark_mapping(mapping)
        snapshots = [
            SectorUniverseService(repository).create_snapshot(
                sector_id=sector_id,
                as_of=args.as_of,
                membership_version=CURRENT_US_RESEARCH_UNIVERSE_VERSION,
                source="phase4_day31_current_research_universe_v1",
            )
            for sector_id in _SECTORS
        ]
        result = {
            "status": "ok",
            "provider": "alpaca_market_data",
            "source_identity": (
                f"feed={settings.alpaca_feed};"
                f"adjustment={settings.alpaca_adjustment}"
            ),
            "as_of": args.as_of.isoformat(),
            "data_window": {
                "start": args.start_date.isoformat(),
                "end": args.end_date.isoformat(),
            },
            "database_path": str(database_path),
            "required_assets_validated": len(_ASSET_IDS),
            "benchmark_candidates": len(candidate_ids),
            "benchmarks_validated": len(set(candidate_ids) & validated_ids),
            "sectors": [snapshot.model_dump(mode="json") for snapshot in snapshots],
            "classification_source": "phase4_day31_curated_research_universe",
            "classification_scope": "non_exhaustive_current_research_universe",
        }
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ProviderUnavailableError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "provider_error",
                    "provider": "alpaca_market_data",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
