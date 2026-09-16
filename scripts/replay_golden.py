"""Replay the two Phase 4B Golden runs from frozen artifacts only."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.build_research_episode import (
    manifest_episode_input,
    summary_episode_input,
)
from scripts.build_research_state import (
    load_agent_claims,
    state_sector_context_input,
)
from src.schemas.golden_replay import (
    GoldenReplayCheck,
    GoldenReplayManifest,
    GoldenReplayMemoryStatus,
)
from src.schemas.research_attribution import ResearchEpisodeAttribution
from src.schemas.research_data import ResearchDataBundle
from src.schemas.research_dataset import ResearchDatasetSample
from src.schemas.research_episode import ResearchEpisode
from src.schemas.research_state import ResearchStateBuildInput, ResearchStateSnapshot
from src.schemas.sector_context import SectorContextBundle
from src.schemas.temporal import TemporalMetadata, TemporalSourceKind
from src.services.golden_replay import (
    GoldenReplayError,
    GoldenReplayInput,
    GoldenReplayLeakageFixture,
    GoldenReplayService,
    validate_leakage_challenges,
)

_PHASE3_ROOT = Path("data/live_acceptance/20260814T100747Z")
_PHASE4_BUNDLE = Path(
    "data/sector_asset_integration/20260830T134805Z/" "AAPL.research_data_bundle.json"
)
_PHASE4_CONTEXT = Path(
    "data/live_sector_research/20260830T135456Z/" "AAPL.real_qwen_sector_context.json"
)
_PHASE4_SUMMARY = Path(
    "data/live_agent_contract/agent_contract_20260830T135643Z_70442a96/" "summary.json"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the zero-Provider, zero-LLM Golden PIT replay gate."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/golden_replay/day43"),
    )
    parser.add_argument(
        "--created-at",
        default="2026-09-01T12:00:00Z",
        help="Aware audit timestamp; excluded from semantic identities.",
    )
    return parser


def _leakage_checks(research_as_of: datetime) -> tuple[GoldenReplayCheck, ...]:
    future = research_as_of + timedelta(seconds=1)
    fixtures = tuple(
        GoldenReplayLeakageFixture(
            name=name,
            metadata=TemporalMetadata(
                source_kind=kind,
                available_at=future if name != "future_sector_membership" else None,
                effective_from=(
                    future.date() if name == "future_sector_membership" else None
                ),
            ),
        )
        for name, kind in (
            ("future_news", TemporalSourceKind.ALPACA_NEWS),
            ("future_radar_event", TemporalSourceKind.SECTOR_ANOMALY),
            ("future_memory", TemporalSourceKind.MEMORY),
            ("future_sector_membership", TemporalSourceKind.SECTOR_MEMBERSHIP),
            ("future_filing", TemporalSourceKind.SEC_FILING),
        )
    )
    return validate_leakage_challenges(fixtures, research_as_of=research_as_of)


def _phase3_input(created_at: datetime) -> GoldenReplayInput:
    bundle_path = _PHASE3_ROOT / "research_data_bundle.json"
    database_path = _PHASE3_ROOT / "duckdb/platform.duckdb"
    manifest_path = _PHASE3_ROOT / "run_manifest.json"
    state_path = Path(
        "data/research_state/day38/phase3_aapl_golden.research_state.json"
    )
    episode_path = Path(
        "data/research_episode/day39/phase3_aapl_golden.research_episode.json"
    )
    sample_path = Path(
        "data/research_dataset/day42/" "phase3_aapl_golden.research_dataset_sample.json"
    )
    bundle = ResearchDataBundle.model_validate_json(bundle_path.read_text())
    state = ResearchStateSnapshot.model_validate_json(state_path.read_text())
    episode = ResearchEpisode.model_validate_json(episode_path.read_text())
    sample = ResearchDatasetSample.model_validate_json(sample_path.read_text())
    claims, prompts, models = load_agent_claims(database_path)
    state_input = ResearchStateBuildInput(
        research_data_bundle=bundle,
        accepted_claims=claims,
        prompt_versions=prompts,
        model_versions=models,
        source_run_id="20260814T100747Z",
    )
    return GoldenReplayInput(
        replay_name="phase3_aapl_golden",
        source_run_id="20260814T100747Z",
        source_artifact_ids=tuple(
            str(path)
            for path in (
                bundle_path,
                database_path,
                manifest_path,
                state_path,
                episode_path,
                sample_path,
            )
        ),
        state_build_input=state_input,
        episode_build_input=manifest_episode_input(manifest_path, database_path, state),
        expected_state=state,
        expected_episode=episode,
        expected_sample=sample,
        leakage_checks=_leakage_checks(state.research_as_of),
        created_at=created_at,
        memory_status=GoldenReplayMemoryStatus.NOT_AVAILABLE_AT_SOURCE_RUN,
    )


def _phase4_input(created_at: datetime) -> GoldenReplayInput:
    state_path = Path(
        "data/research_state/day38/phase4a_aapl_sector_aware.research_state.json"
    )
    episode_path = Path(
        "data/research_episode/day39/" "phase4a_aapl_sector_aware.research_episode.json"
    )
    attribution_path = Path(
        "data/research_attribution/day41/"
        "phase4a_aapl_sector_aware.research_attribution.json"
    )
    sample_path = Path(
        "data/research_dataset/day42/"
        "phase4a_aapl_sector_aware.research_dataset_sample.json"
    )
    sector_manifest_path = _PHASE4_CONTEXT.parent / "manifest.json"
    bundle = ResearchDataBundle.model_validate_json(_PHASE4_BUNDLE.read_text())
    context = SectorContextBundle.model_validate_json(_PHASE4_CONTEXT.read_text())
    state = ResearchStateSnapshot.model_validate_json(state_path.read_text())
    episode = ResearchEpisode.model_validate_json(episode_path.read_text())
    attribution = ResearchEpisodeAttribution.model_validate_json(
        attribution_path.read_text()
    )
    sample = ResearchDatasetSample.model_validate_json(sample_path.read_text())
    state_input = ResearchStateBuildInput(
        research_data_bundle=bundle,
        sector_context=state_sector_context_input(context),
        source_run_id="agent_contract_20260830T135643Z_70442a96",
    )
    return GoldenReplayInput(
        replay_name="phase4a_aapl_sector_aware",
        source_run_id="agent_contract_20260830T135643Z_70442a96",
        source_artifact_ids=tuple(
            str(path)
            for path in (
                _PHASE4_BUNDLE,
                _PHASE4_CONTEXT,
                sector_manifest_path,
                _PHASE4_SUMMARY,
                state_path,
                episode_path,
                attribution_path,
                sample_path,
            )
        ),
        state_build_input=state_input,
        episode_build_input=summary_episode_input(_PHASE4_SUMMARY, state),
        expected_state=state,
        expected_episode=episode,
        expected_attribution=attribution,
        expected_sample=sample,
        sector_context=context,
        leakage_checks=_leakage_checks(state.research_as_of),
        created_at=created_at,
        memory_status=GoldenReplayMemoryStatus.EMPTY_VALID,
    )


def build_golden_replays(created_at: datetime) -> tuple[GoldenReplayManifest, ...]:
    """Build both canonical Golden manifests without external service calls."""

    service = GoldenReplayService()
    return tuple(
        service.replay(inputs)
        for inputs in (_phase3_input(created_at), _phase4_input(created_at))
    )


def main(argv: list[str] | None = None) -> int:
    """Run both Golden replays and persist credential-free manifests."""

    args = _parser().parse_args(argv)
    try:
        created_at = datetime.fromisoformat(args.created_at.replace("Z", "+00:00"))
        if created_at.tzinfo is None:
            raise ValueError("--created-at must be timezone-aware")
        manifests = build_golden_replays(created_at.astimezone(UTC))
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for manifest in manifests:
            output = args.output_dir / f"{manifest.replay_name}.golden_replay.json"
            output.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        summary = {
            "status": "pass",
            "provider_call_count": 0,
            "llm_call_count": 0,
            "known_limitations": [
                (
                    "Learning Memory has only passed empty-state PIT replay "
                    "validation; no replayed run currently has "
                    "memory_retrieval_count > 0."
                )
            ],
            "replays": [
                {
                    "replay_id": item.replay_id,
                    "replay_name": item.replay_name,
                    "state_id": item.research_state_id,
                    "episode_id": item.research_episode_id,
                    "sample_id": item.research_dataset_sample_id,
                    "status": item.replay_status.value,
                }
                for item in manifests
            ],
        }
        summary_path = args.output_dir / "acceptance_summary.json"
        summary_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(summary, sort_keys=True))
    except (GoldenReplayError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "provider_call_count": 0,
                    "llm_call_count": 0,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
