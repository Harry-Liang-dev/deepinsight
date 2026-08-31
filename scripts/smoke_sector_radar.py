"""Run the opt-in real-data Sector Anomaly Radar and Memory smoke."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from src.core import load_settings
from src.memory import MemoryService
from src.models.enums import SectorId
from src.operators import SectorAnomalyRadar, SectorRadarInputError
from src.repositories import (
    DuckDBDatabase,
    FaissVectorRepository,
    MarketDataRepository,
    MemoryItemRepository,
    SectorOntologyRepository,
)
from src.services import (
    QwenEmbeddingService,
    SectorRadarMemoryService,
    build_sector_ontology_seed_v1,
)

_SECTORS = (
    SectorId.SEMICONDUCTORS_AI_COMPUTE,
    SectorId.MEMORY_STORAGE,
    SectorId.CONSUMER_ELECTRONICS_HARDWARE,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Detect real Sector anomalies and verify hierarchical Memory."
    )
    parser.add_argument("--sector-state-db", type=Path, required=True)
    parser.add_argument("--sector-macro-db", type=Path, required=True)
    parser.add_argument(
        "--output-root", type=Path, default=Path("data/live_sector_radar")
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run Radar over audited live snapshots without using an LLM for detection."""

    args = _parser().parse_args(argv)
    if not args.sector_state_db.exists() or not args.sector_macro_db.exists():
        print(
            json.dumps({"status": "configuration_error", "reason": "source DB missing"})
        )
        return 2
    settings = load_settings()
    if settings.qwen.api_key is None:
        print(json.dumps({"status": "not_configured", "provider": "qwen_embedding"}))
        return 2

    state_database = DuckDBDatabase(args.sector_state_db)
    macro_database = DuckDBDatabase(args.sector_macro_db)
    states = SectorOntologyRepository(state_database)
    macros = SectorOntologyRepository(macro_database)
    market = MarketDataRepository(state_database)
    as_of = _latest_common_as_of(states, macros)
    if as_of is None:
        print(
            json.dumps({"status": "configuration_error", "reason": "snapshot missing"})
        )
        return 2

    run_at = datetime.now(UTC)
    run_dir = args.output_root / run_at.strftime("%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, exist_ok=False)
    database = DuckDBDatabase(run_dir / "sector_radar.duckdb")
    database.bootstrap()
    repository = SectorOntologyRepository(database)
    repository.install_seed(build_sector_ontology_seed_v1())
    embedder = QwenEmbeddingService(
        settings.qwen,
        dimension=settings.qwen.embedding_dimension,
        batch_size=settings.qwen.embedding_batch_size,
    )
    vectors = FaissVectorRepository(
        run_dir / "faiss",
        embedder_model=embedder.model_name,
        embedding_dim=embedder.dimension,
    )
    memory = MemoryService(MemoryItemRepository(database), vectors, embedder)
    memory_projection = SectorRadarMemoryService(repository, memory)

    events = []
    memory_retrieval: dict[str, int] = {}
    try:
        for sector_id in _SECTORS:
            state = states.get_latest_research_snapshot(sector_id, as_of=as_of)
            macro = macros.get_latest_macro_snapshot(sector_id, as_of=as_of)
            universe = states.get_latest_universe_snapshot(sector_id, as_of=as_of)
            if state is None or macro is None or universe is None:
                raise SectorRadarInputError(f"missing snapshot for {sector_id.value}")
            memberships = states.list_sector_memberships(sector_id, as_of=as_of)
            bars_by_asset = {
                str(asset_id): market.list_eod_bars(asset_id, end_date=as_of, limit=100)
                for asset_id in universe.asset_ids
            }
            detected = SectorAnomalyRadar().detect(
                sector_state=state,
                macro_state=macro,
                bars_by_asset=bars_by_asset,
                memberships=memberships,
                nodes=states.list_nodes(as_of=as_of),
                edges=states.list_edges(as_of=as_of),
            )
            for event in detected:
                memory_projection.persist(event)
                events.append(event)
            if detected:
                memory_retrieval[sector_id.value] = len(
                    memory_projection.search_sector(
                        detected[0], query_text=detected[0].summary
                    ).results
                )
    except (SectorRadarInputError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1

    sector_retrieval = {
        sector_id.value: len(
            repository.list_anomalies_for_scope(
                _sector_scope_id(sector_id),
                as_of=datetime.combine(as_of, datetime.max.time(), tzinfo=UTC),
            )
        )
        for sector_id in _SECTORS
    }
    print(
        json.dumps(
            {
                "status": "ok",
                "as_of": as_of.isoformat(),
                "database_path": str(run_dir / "sector_radar.duckdb"),
                "event_count": len(events),
                "event_types": sorted({item.event_type.value for item in events}),
                "source_evidence_count": sum(
                    len(item.source_evidence_ids) for item in events
                ),
                "sector_scope_retrieval": sector_retrieval,
                "memory_scope_retrieval": memory_retrieval,
                "future_leakage_count": sum(
                    item.available_at > item.as_of for item in events
                ),
                "llm_anomaly_calls": 0,
                "embedding_provider": "qwen",
                "events": [
                    {
                        "event_id": item.event_id,
                        "type": item.event_type.value,
                        "sector_id": item.sector_id.value,
                        "severity": item.severity.value,
                        "source_evidence_ids": list(item.source_evidence_ids),
                        "chain_ids": list(item.chain_ids),
                        "affected_asset_ids": [
                            str(value) for value in item.affected_asset_ids
                        ],
                    }
                    for item in events
                ],
            },
            sort_keys=True,
        )
    )
    return 0


def _latest_common_as_of(
    states: SectorOntologyRepository,
    macros: SectorOntologyRepository,
) -> date | None:
    dates: list[date] = []
    for sector_id in _SECTORS:
        state = states.get_latest_research_snapshot(sector_id, as_of=date.max)
        macro = macros.get_latest_macro_snapshot(sector_id, as_of=date.max)
        if state is None or macro is None:
            return None
        dates.extend((state.as_of, macro.as_of))
    return min(dates) if dates else None


def _sector_scope_id(sector_id: SectorId) -> str:
    return {
        SectorId.SEMICONDUCTORS_AI_COMPUTE: "SECTOR:SEMICONDUCTORS_AI",
        SectorId.MEMORY_STORAGE: "SECTOR:MEMORY_STORAGE",
        SectorId.CONSUMER_ELECTRONICS_HARDWARE: "SECTOR:CONSUMER_ELECTRONICS",
    }[sector_id]


if __name__ == "__main__":
    raise SystemExit(main())
