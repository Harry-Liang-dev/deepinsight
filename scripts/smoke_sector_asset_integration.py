"""Run the Day36 three-asset Sector routing and projection contract smoke."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from scripts.smoke_sector_research import (
    _build_input,
    _FixedSectorGateway,
    _latest_common_as_of,
)
from src.agents import SectorResearchAgent, SectorResearchPromptLoader
from src.models.enums import AgentName, AgentStatus, SectorId
from src.models.identifiers import AssetId
from src.models.types import JsonObject
from src.repositories import (
    DocumentRepository,
    DuckDBDatabase,
    InstrumentRepository,
    MarketDataRepository,
    SectorOntologyRepository,
)
from src.schemas.research_data import (
    DataCapability,
    ResearchDataBundleRequest,
)
from src.schemas.sector_research import SectorResearchInput, SectorResearchOutput
from src.services.research_data_bundle import ResearchDataBundleService
from src.services.sector_context import (
    RepositorySectorContextResolver,
    SectorContextProjector,
)

_ASSETS = (AssetId("US:NVDA"), AssetId("US:MU"), AssetId("US:AAPL"))
_SECTORS = (
    SectorId.SEMICONDUCTORS_AI_COMPUTE,
    SectorId.MEMORY_STORAGE,
    SectorId.CONSUMER_ELECTRONICS_HARDWARE,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sector-state-db",
        type=Path,
        default=Path("data/live_sector_state/20260830T034235Z/sector_state.duckdb"),
    )
    parser.add_argument(
        "--sector-macro-db",
        type=Path,
        default=Path("data/live_sector_macro/20260830T051233Z/sector_macro.duckdb"),
    )
    parser.add_argument(
        "--sector-radar-db",
        type=Path,
        default=Path("data/live_sector_radar/20260830T074510Z/sector_radar.duckdb"),
    )
    parser.add_argument("--prompt-root", type=Path, default=Path("config/prompts"))
    parser.add_argument(
        "--output-root", type=Path, default=Path("data/sector_asset_integration")
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Build real-snapshot Sector contexts and all eight role projections."""

    args = _parser().parse_args(argv)
    paths = (args.sector_state_db, args.sector_macro_db, args.sector_radar_db)
    if any(not path.exists() for path in paths):
        print(json.dumps({"status": "configuration_error", "reason": "DB missing"}))
        return 2
    state = SectorOntologyRepository(DuckDBDatabase(args.sector_state_db))
    state_database = DuckDBDatabase(args.sector_state_db)
    macro = SectorOntologyRepository(DuckDBDatabase(args.sector_macro_db))
    radar = SectorOntologyRepository(DuckDBDatabase(args.sector_radar_db))
    as_of_date = _latest_common_as_of(state, macro)
    if as_of_date is None:
        print(json.dumps({"status": "configuration_error", "reason": "state missing"}))
        return 2
    research_as_of = datetime.combine(
        as_of_date,
        datetime.max.time(),
        tzinfo=UTC,
    )
    agent = SectorResearchAgent(
        _FixedSectorGateway(),
        SectorResearchPromptLoader(args.prompt_root),
    )
    outputs: dict[SectorId, SectorResearchOutput] = {}
    sector_inputs: dict[SectorId, SectorResearchInput] = {}
    for sector_id in _SECTORS:
        research_input = _build_input(
            sector_id,
            research_as_of=research_as_of,
            state=state,
            macro=macro,
            radar=radar,
        )
        result = agent.run(
            run_id=f"day36-sector-{sector_id.value}",
            model_name="fixed-sector-smoke-v1",
            research_input=research_input,
        )
        if result.status is not AgentStatus.OK or result.output is None:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "reason": "Sector Research Agent fixture failed",
                        "sector_id": sector_id.value,
                    }
                )
            )
            return 1
        outputs[sector_id] = result.output
        sector_inputs[sector_id] = research_input
    resolver = RepositorySectorContextResolver(
        ontology_repository=state,
        macro_repository=macro,
        radar_repository=radar,
        sector_outputs=outputs,
    )
    asset_summaries: list[JsonObject] = []
    context_files = []
    stamp = datetime.now(UTC)
    run_dir = args.output_root / stamp.strftime("%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, exist_ok=False)
    asset_bundle_builder = ResearchDataBundleService(
        instruments=InstrumentRepository(state_database),
        market_data=MarketDataRepository(state_database),
        documents=DocumentRepository(state_database),
    )
    for asset_id in _ASSETS:
        resolution = resolver.resolve(
            asset_id=asset_id,
            research_as_of=research_as_of,
        )
        if resolution.bundle is None:
            asset_summaries.append(
                {
                    "asset_id": str(asset_id),
                    "status": "degraded",
                    "reason": resolution.reason,
                }
            )
            continue
        bundle = resolution.bundle
        projections = {
            role.value: SectorContextProjector.for_role(bundle, role)
            for role in AgentName
        }
        context_path = run_dir / f"{str(asset_id).split(':')[1]}.sector_context.json"
        context_path.write_text(
            bundle.model_dump_json(indent=2),
            encoding="utf-8",
        )
        context_files.append(str(context_path))
        asset_bundle = asset_bundle_builder.build(
            ResearchDataBundleRequest(
                asset_id=asset_id,
                as_of=research_as_of,
                window_start=as_of_date - timedelta(days=400),
                window_end=as_of_date,
                dataset_version="phase4a_day36_fixed_real_snapshot_v1",
                requested_capabilities=tuple(DataCapability),
            )
        )
        asset_bundle_path = (
            run_dir / f"{str(asset_id).split(':')[1]}.research_data_bundle.json"
        )
        asset_bundle_path.write_text(
            asset_bundle.model_dump_json(indent=2),
            encoding="utf-8",
        )
        role_metrics: dict[str, JsonObject] = {
            role: {
                "provided_sector_claims": len(
                    projection.validated_claims or projection.context_claims
                ),
                "provided_events": len(projection.event_references),
                "context_chars": len(projection.model_dump_json()),
                "used_sector_claims": "NOT_MEASURED_PROJECTION_SMOKE",
            }
            for role, projection in projections.items()
        }
        asset_summaries.append(
            {
                "asset_id": str(asset_id),
                "status": resolution.status.value,
                "sector_id": bundle.sector_id.value,
                "chain_ids": list(bundle.active_chain_ids),
                "sector_context_id": bundle.context_id,
                "asset_data_bundle_id": asset_bundle.bundle_id,
                "asset_data_bundle_path": str(asset_bundle_path),
                "accepted_sector_claims": len(bundle.accepted_claims),
                "radar_events": len(bundle.active_events),
                "recursive_provenance_valid": all(
                    bool(claim.source_references and claim.evidence_ids)
                    for claim in bundle.accepted_claims
                ),
                "membership_seed_only": bundle.coverage.seed_only_membership,
                "memory_status": (
                    sector_inputs[
                        bundle.sector_id
                    ].memory_context.retrieval_metadata.status.value
                ),
                "without_sector": {
                    "provided_sector_claims": 0,
                    "provided_events": 0,
                    "context_chars": 0,
                },
                "with_sector": cast(JsonObject, role_metrics),
            }
        )
    manifest = {
        "status": "ok" if len(context_files) == len(_ASSETS) else "degraded",
        "run_id": run_dir.name,
        "research_as_of": research_as_of.isoformat(),
        "mode": "fixed_contract_real_sector_snapshots",
        "asset_agent_execution": False,
        "source_databases": [str(path) for path in paths],
        "assets": asset_summaries,
        "context_files": context_files,
    }
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({**manifest, "manifest_path": str(manifest_path)}, sort_keys=True))
    return 0 if manifest["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
