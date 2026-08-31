"""Run the opt-in live deterministic Sector cycle and sensitivity smoke."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from src.adapters import AlpacaAdapter, FREDAdapter, ProviderUnavailableError
from src.core import load_settings
from src.models.enums import SectorCapabilityStatus, SectorId
from src.operators import SectorMacroInputError, SectorMacroOperator
from src.repositories import (
    DuckDBDatabase,
    MarketDataRepository,
    SectorOntologyRepository,
)
from src.services import DataNormalizer, NormalizationError

_SECTORS = (
    SectorId.SEMICONDUCTORS_AI_COMPUTE,
    SectorId.MEMORY_STORAGE,
    SectorId.CONSUMER_ELECTRONICS_HARDWARE,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate live deterministic Sector cycle and sensitivity states."
    )
    parser.add_argument("--sector-state-db", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument(
        "--output-root", type=Path, default=Path("data/live_sector_macro")
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Fetch real FRED/Alpaca history and persist Day33 outputs without LLM."""

    args = _parser().parse_args(argv)
    settings = load_settings().providers
    if settings.fred_api_key is None:
        print(json.dumps({"status": "not_configured", "provider": "fred"}))
        return 2
    if settings.alpaca_api_key_id is None or settings.alpaca_api_secret_key is None:
        print(json.dumps({"status": "not_configured", "provider": "alpaca"}))
        return 2
    if not args.sector_state_db.exists():
        print(
            json.dumps(
                {"status": "configuration_error", "reason": "sector state DB missing"}
            )
        )
        return 2

    source_database = DuckDBDatabase(args.sector_state_db)
    source_sectors = SectorOntologyRepository(source_database)
    as_of = args.as_of or _latest_common_as_of(source_sectors)
    if as_of is None:
        print(
            json.dumps(
                {"status": "configuration_error", "reason": "source snapshots missing"}
            )
        )
        return 2
    pairs = []
    for sector_id in _SECTORS:
        universe = source_sectors.get_latest_universe_snapshot(sector_id, as_of=as_of)
        state = source_sectors.get_latest_research_snapshot(sector_id, as_of=as_of)
        if universe is None or state is None or universe.as_of != state.as_of:
            print(
                json.dumps(
                    {
                        "status": "configuration_error",
                        "reason": f"missing aligned state for {sector_id.value}",
                    }
                )
            )
            return 2
        pairs.append((universe, state))

    benchmark_ids = sorted(
        {str(item) for universe, _ in pairs for item in universe.benchmark_ids}
    )
    checked_at = datetime.now(UTC)
    try:
        alpaca = AlpacaAdapter(
            api_key_id=settings.alpaca_api_key_id.get_secret_value(),
            api_secret_key=settings.alpaca_api_secret_key.get_secret_value(),
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
                alpaca.provider_name, raw, received_at=checked_at
            )
            for raw in alpaca.fetch_eod_bars_range(
                benchmark_ids,
                as_of - timedelta(days=1_550),
                as_of,
            )
        ]
        fred = FREDAdapter(
            api_key=settings.fred_api_key.get_secret_value(),
            user_agent=settings.fred_user_agent,
            request_timeout=settings.fred_request_timeout_seconds,
            max_retries=settings.fred_max_retries,
            requests_per_second=settings.fred_requests_per_second,
            backoff_base_seconds=settings.fred_backoff_base_seconds,
            max_backoff_seconds=settings.fred_max_backoff_seconds,
        )
        macro = [
            normalizer.normalize_macro_observation(
                fred.provider_name, raw, received_at=checked_at
            )
            for raw in fred.fetch_macro_series(
                (),
                as_of - timedelta(days=1_825),
                as_of,
                as_of,
            )
        ]
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

    run_dir = args.output_root / checked_at.strftime("%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, exist_ok=False)
    database_path = run_dir / "sector_macro.duckdb"
    database = DuckDBDatabase(database_path)
    database.bootstrap()
    market_repository = MarketDataRepository(database)
    sector_repository = SectorOntologyRepository(database)
    for bar in bars:
        market_repository.upsert_eod_bar(bar)
    market_repository.upsert_macro_observations(macro)
    cutoff = datetime.combine(as_of, time.max, tzinfo=UTC)
    macro_history = market_repository.list_macro_observations(
        FREDAdapter.DEFAULT_SERIES,
        end_date=as_of,
        as_of=cutoff,
    )
    outputs = []
    try:
        for universe, state in pairs:
            sector_repository.save_universe_snapshot(universe)
            sector_repository.save_research_snapshot(state)
            assert universe.benchmark_ids
            benchmark_id = universe.benchmark_ids[0]
            benchmark_bars = market_repository.list_eod_bars(
                benchmark_id,
                end_date=as_of,
                limit=1_200,
            )
            output = SectorMacroOperator().compute(
                universe=universe,
                sector_state=state,
                benchmark_bars=benchmark_bars,
                macro_observations=macro_history,
            )
            sector_repository.save_macro_snapshot(output)
            outputs.append(output)
    except (SectorMacroInputError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "state_error",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
        )
        return 1

    print(
        json.dumps(
            {
                "status": "ok",
                "as_of": as_of.isoformat(),
                "database_path": str(database_path),
                "bar_count": len(bars),
                "macro_observation_count": len(macro_history),
                "llm_calls": 0,
                "snapshots": [
                    {
                        "snapshot_id": item.snapshot_id,
                        "sector_id": item.sector_id.value,
                        "status": item.status.value,
                        "cycle": {
                            name: getattr(item.cycle_state, name).direction.value
                            for name in (
                                "rates",
                                "inflation",
                                "labor",
                                "growth",
                                "financial_stress",
                            )
                        },
                        "sensitivity_available": sum(
                            estimate.status is SectorCapabilityStatus.AVAILABLE
                            for estimate in item.macro_sensitivity.estimates
                        ),
                        "sensitivity_total": len(item.macro_sensitivity.estimates),
                    }
                    for item in outputs
                ],
            },
            sort_keys=True,
        )
    )
    return 0


def _latest_common_as_of(repository: SectorOntologyRepository) -> date | None:
    dates = []
    for sector_id in _SECTORS:
        snapshot = repository.get_latest_research_snapshot(sector_id, as_of=date.max)
        if snapshot is None:
            return None
        dates.append(snapshot.as_of)
    return min(dates) if dates else None


if __name__ == "__main__":
    raise SystemExit(main())
