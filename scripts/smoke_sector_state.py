"""Run an opt-in live deterministic SectorResearchSnapshot smoke."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.adapters import (
    AlpacaAdapter,
    FinancialModelingPrepAdapter,
    ProviderUnavailableError,
)
from src.core import load_settings
from src.models.enums import SectorId
from src.models.identifiers import AssetId
from src.operators import SectorStateInputError, SectorStateOperator
from src.repositories import (
    DuckDBDatabase,
    MarketDataRepository,
    SectorOntologyRepository,
)
from src.schemas.market_data import FundamentalRecord
from src.schemas.temporal import TemporalAccessMode
from src.services import (
    CURRENT_US_RESEARCH_UNIVERSE_VERSION,
    DataNormalizer,
    NormalizationError,
    SectorOntologyService,
    SectorUniverseService,
    build_current_us_research_memberships_v1,
    build_us_sector_benchmark_candidates_v1,
    resolve_validated_benchmark_mappings,
)
from src.services.research_clock import ResearchAsOfMode, parse_research_clock

_ASSETS = ("US:AAPL", "US:NVDA", "US:AMD", "US:TSM", "US:MU")
_PRICE_IDS = (*_ASSETS, "US:SPY", "US:SOXX", "US:XLK")
_SECTORS = (
    SectorId.SEMICONDUCTORS_AI_COMPUTE,
    SectorId.MEMORY_STORAGE,
    SectorId.CONSUMER_ELECTRONICS_HARDWARE,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate three deterministic live Sector research snapshots."
    )
    parser.add_argument(
        "--as-of",
        type=parse_research_clock,
        default=parse_research_clock(datetime.now(UTC).isoformat()),
    )
    parser.add_argument(
        "--output-root", type=Path, default=Path("data/live_sector_state")
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Fetch real canonical inputs and persist three deterministic snapshots."""

    args = _parser().parse_args(argv)
    clock = args.as_of
    as_of = clock.snapshot_date
    market_session_date = clock.market_session_date
    settings = load_settings().providers
    key_id = settings.alpaca_api_key_id
    secret_key = settings.alpaca_api_secret_key
    fmp_key = settings.fmp_api_key
    missing = []
    if key_id is None or secret_key is None:
        missing.append("Alpaca")
    if not settings.fmp_enabled or fmp_key is None:
        missing.append("FMP")
    if missing:
        print(
            json.dumps(
                {"status": "not_configured", "providers": sorted(missing)},
                sort_keys=True,
            )
        )
        return 2
    assert key_id is not None and secret_key is not None and fmp_key is not None

    checked_at = datetime.now(UTC)
    start_date = market_session_date - timedelta(days=130)
    try:
        alpaca = AlpacaAdapter(
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
        normalizer = DataNormalizer()
        bars = [
            normalizer.normalize_eod_bar(
                alpaca.provider_name,
                raw,
                received_at=checked_at,
            )
            for raw in alpaca.fetch_eod_bars_range(
                list(_PRICE_IDS), start_date, market_session_date
            )
        ]
        validated_ids = {str(item.asset_id) for item in bars}
        required_missing = sorted(set(_PRICE_IDS) - validated_ids)
        if required_missing:
            raise ProviderUnavailableError(
                "Alpaca returned no bars for: " + ", ".join(required_missing)
            )
        fmp = FinancialModelingPrepAdapter(
            api_key=fmp_key.get_secret_value(),
            base_url=settings.fmp_base_url,
            user_agent=settings.fmp_user_agent,
            request_timeout=settings.fmp_request_timeout_seconds,
            max_retries=settings.fmp_max_retries,
            requests_per_second=settings.fmp_requests_per_second,
        )
        fundamentals: list[FundamentalRecord] = []
        fundamental_errors: dict[str, str] = {}
        for asset_id in _ASSETS:
            try:
                raw_records = fmp.fetch_fundamentals_range(
                    [asset_id],
                    as_of - timedelta(days=740),
                    as_of,
                )
                fundamentals.extend(
                    normalizer.normalize_fundamental(
                        fmp.provider_name,
                        raw,
                        received_at=checked_at,
                    )
                    for raw in raw_records
                )
            except (ProviderUnavailableError, NormalizationError, ValueError) as exc:
                fundamental_errors[asset_id] = type(exc).__name__
    except (ProviderUnavailableError, NormalizationError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "provider_error",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1

    run_stamp = checked_at.strftime("%Y%m%dT%H%M%SZ")
    latest_completed_market_session = max(item.trade_date for item in bars)
    run_dir = args.output_root / run_stamp
    run_dir.mkdir(parents=True, exist_ok=False)
    database_path = run_dir / "sector_state.duckdb"
    database = DuckDBDatabase(database_path)
    database.bootstrap()
    sector_repository = SectorOntologyRepository(database)
    market_repository = MarketDataRepository(database)
    SectorOntologyService(sector_repository).install_v1_seed()
    for membership in build_current_us_research_memberships_v1():
        sector_repository.add_membership(membership)
    for bar in bars:
        market_repository.upsert_eod_bar(bar)
    for fundamental in fundamentals:
        market_repository.upsert_fundamental(fundamental)
    mappings = resolve_validated_benchmark_mappings(
        build_us_sector_benchmark_candidates_v1(),
        validated_asset_ids=validated_ids,
        valid_from=as_of,
    )
    for mapping in mappings:
        sector_repository.add_benchmark_mapping(mapping)

    operator = SectorStateOperator()
    snapshots = []
    try:
        for sector_id in _SECTORS:
            universe = SectorUniverseService(sector_repository).create_snapshot(
                sector_id=sector_id,
                as_of=as_of,
                membership_version=CURRENT_US_RESEARCH_UNIVERSE_VERSION,
                source="phase4_day32_live_sector_state",
            )
            bars_by_asset = {
                asset_id: market_repository.list_eod_bars(
                    AssetId(asset_id),
                    end_date=market_session_date,
                    limit=120,
                )
                for asset_id in {
                    *(str(item) for item in universe.asset_ids),
                    *(str(item) for item in universe.benchmark_ids),
                    "US:SPY",
                }
            }
            fundamentals_by_asset = {
                str(asset_id): market_repository.list_fundamentals(
                    asset_id,
                    end_date=as_of,
                )
                for asset_id in universe.asset_ids
            }
            snapshot = operator.compute(
                universe=universe,
                bars_by_asset=bars_by_asset,
                fundamentals_by_asset=fundamentals_by_asset,
                research_as_of=clock.research_as_of,
                temporal_access_mode=(
                    TemporalAccessMode.LIVE_ACQUISITION
                    if clock.mode is ResearchAsOfMode.INSTANT
                    else TemporalAccessMode.HISTORICAL_REPLAY
                ),
            )
            sector_repository.save_research_snapshot(snapshot)
            snapshots.append(snapshot)
    except (SectorStateInputError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "state_error",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "status": "ok",
                "as_of": clock.research_as_of.isoformat(),
                "as_of_mode": clock.mode.value,
                "snapshot_date": as_of.isoformat(),
                "market_session_date": latest_completed_market_session.isoformat(),
                "market_query_end": market_session_date.isoformat(),
                "database_path": str(database_path),
                "providers": ["alpaca_market_data", "financial_modeling_prep"],
                "bar_count": len(bars),
                "fundamental_count": len(fundamentals),
                "fundamental_errors": fundamental_errors,
                "snapshots": [
                    {
                        "snapshot_id": item.snapshot_id,
                        "sector_id": item.sector_id.value,
                        "status": item.status.value,
                        "coverage": item.coverage.model_dump(mode="json"),
                        "market_state": item.market_state.model_dump(mode="json"),
                        "breadth_state": item.breadth_state.model_dump(mode="json"),
                        "fundamental_state": item.fundamental_state.model_dump(
                            mode="json"
                        ),
                        "valuation_state": item.valuation_state.model_dump(mode="json"),
                    }
                    for item in snapshots
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
