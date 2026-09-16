"""Golden point-in-time replay regression tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from scripts.replay_golden import build_golden_replays
from src.schemas.golden_replay import (
    GoldenReplayManifest,
    GoldenReplayMemoryStatus,
    GoldenReplayTraceStatus,
)
from src.schemas.temporal import TemporalMetadata, TemporalSourceKind
from src.services.golden_replay import (
    GoldenReplayError,
    GoldenReplayLeakageFixture,
    validate_leakage_challenges,
)


@pytest.fixture(scope="module")
def replays() -> tuple[GoldenReplayManifest, ...]:
    """Build the two checked-in Golden runs once for focused assertions."""

    return build_golden_replays(datetime(2026, 9, 1, 12, tzinfo=UTC))


def test_phase3_golden_run_replays_without_historical_backfill(
    replays: tuple[GoldenReplayManifest, ...],
) -> None:
    """Keep the Phase 3 State, Episode, and Sample identities unchanged."""

    phase3 = replays[0]
    assert phase3.research_state_id == "research_state_fd95d91fbf0a635951884295"
    assert phase3.research_episode_id == "research_episode_67b3b89872e7d4246c37d7da"
    assert (
        phase3.research_dataset_sample_id == "research_sample_4b98c4b3f722981a81d51f5d"
    )
    assert phase3.sector_claims_provided == 0
    assert phase3.events_provided == 0
    assert phase3.attribution_ids == ()
    assert phase3.memory_status is GoldenReplayMemoryStatus.NOT_AVAILABLE_AT_SOURCE_RUN


def test_phase4a_golden_run_retains_sector_usage_and_empty_memory(
    replays: tuple[GoldenReplayManifest, ...],
) -> None:
    """Retain Day36 Sector/Radar usage without inventing missing Claim IDs."""

    phase4 = replays[1]
    assert phase4.research_state_id == "research_state_3da102d1a1515b82dbe4f9b7"
    assert phase4.research_episode_id == "research_episode_d4a588c6bac4fa6fe558cad5"
    assert (
        phase4.research_dataset_sample_id == "research_sample_f1b426e6b3eea228bdc61dba"
    )
    assert phase4.sector_claims_provided == 24
    assert phase4.sector_claims_used == 10
    assert phase4.events_provided == 6
    assert phase4.events_used == 4
    assert phase4.memory_status is GoldenReplayMemoryStatus.EMPTY_VALID
    assert phase4.memory_retrieval_count == 0
    assert phase4.memory_empty_valid is True
    partial = [
        item
        for item in phase4.traceability_examples
        if item.status is GoldenReplayTraceStatus.PARTIAL
    ]
    assert {item.trace_name for item in partial} == {
        "asset_manager_to_sector_claim_to_evidence",
        "context_to_agent_to_claim_to_episode",
    }


def test_replay_identity_ignores_audit_created_at(
    replays: tuple[GoldenReplayManifest, ...],
) -> None:
    """Exclude replay audit time from all semantic identities."""

    later = build_golden_replays(datetime(2026, 9, 2, 12, tzinfo=UTC))
    for first, second in zip(replays, later, strict=True):
        assert first.replay_id == second.replay_id
        assert first.input_fingerprint == second.input_fingerprint
        assert first.research_state_id == second.research_state_id
        assert first.research_episode_id == second.research_episode_id
        assert first.research_dataset_sample_id == second.research_dataset_sample_id
        assert first.created_at != second.created_at


def test_replay_declares_zero_external_calls_and_complete_core_traces(
    replays: tuple[GoldenReplayManifest, ...],
) -> None:
    """Make the offline boundary and core lineage machine-verifiable."""

    for replay in replays:
        assert replay.provider_call_count == 0
        assert replay.llm_call_count == 0
        assert all(item.status.value == "pass" for item in replay.leakage_checks)
        assert all(item.status.value == "pass" for item in replay.determinism_checks)
        names = {item.trace_name for item in replay.traceability_examples}
        assert "deterministic_feature_to_evidence_provider" in names
        assert "dataset_to_episode_to_state" in names


def test_golden_replay_leakage_challenge_rejects_five_future_inputs() -> None:
    """Exercise the shared PIT policy for every Day43 challenge category."""

    cutoff = datetime(2026, 8, 30, 23, 59, tzinfo=UTC)
    future = cutoff + timedelta(days=1)
    fixtures = tuple(
        GoldenReplayLeakageFixture(
            name=name,
            metadata=TemporalMetadata(
                source_kind=kind,
                available_at=future if name != "future_membership" else None,
                effective_from=(future.date() if name == "future_membership" else None),
            ),
        )
        for name, kind in (
            ("future_news", TemporalSourceKind.ALPACA_NEWS),
            ("future_radar", TemporalSourceKind.SECTOR_ANOMALY),
            ("future_memory", TemporalSourceKind.MEMORY),
            ("future_membership", TemporalSourceKind.SECTOR_MEMBERSHIP),
            ("future_filing", TemporalSourceKind.SEC_FILING),
        )
    )
    checks = validate_leakage_challenges(fixtures, research_as_of=cutoff)
    assert len(checks) == 5
    assert {item.evidence_ids[0] for item in checks} == {
        "future_available",
        "not_yet_effective",
    }


def test_usable_future_challenge_fails_closed() -> None:
    """Refuse a mislabeled challenge instead of declaring a false PASS."""

    cutoff = datetime(2026, 8, 30, 23, 59, tzinfo=UTC)
    fixture = GoldenReplayLeakageFixture(
        name="not_actually_future",
        metadata=TemporalMetadata(
            source_kind=TemporalSourceKind.ALPACA_NEWS,
            available_at=cutoff,
        ),
    )
    with pytest.raises(GoldenReplayError, match="unexpectedly usable"):
        validate_leakage_challenges((fixture,), research_as_of=cutoff)
