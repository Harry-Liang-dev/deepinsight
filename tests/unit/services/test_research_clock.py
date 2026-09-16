"""Canonical research instant and provider-calendar projection regressions."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

import pytest

from src.services.research_clock import ResearchAsOfMode, parse_research_clock


def test_sector_cli_accepts_exact_utc_instant_without_eod_expansion() -> None:
    """Instant mode preserves the exact canonical cutoff."""

    clock = parse_research_clock("2026-09-15T04:30:34Z")
    assert clock.mode is ResearchAsOfMode.INSTANT
    assert clock.research_as_of == datetime(2026, 9, 15, 4, 30, 34, tzinfo=UTC)


def test_offset_aware_instant_normalizes_to_utc() -> None:
    """Offset-aware CLI input maps to the canonical UTC timeline."""

    clock = parse_research_clock("2026-09-15T12:30:34+08:00")
    assert clock.research_as_of == datetime(2026, 9, 15, 4, 30, 34, tzinfo=UTC)


def test_naive_instant_is_rejected() -> None:
    """No CLI silently assumes a timezone for an instant."""

    with pytest.raises(argparse.ArgumentTypeError, match="timezone-aware"):
        parse_research_clock("2026-09-15T04:30:34")


def test_historical_date_mode_keeps_legacy_eod_semantics() -> None:
    """Golden date commands retain their frozen UTC-EOD interpretation."""

    clock = parse_research_clock("2026-08-30")
    assert clock.mode is ResearchAsOfMode.DATE
    assert clock.research_as_of == datetime.max.replace(
        year=2026, month=8, day=30, tzinfo=UTC
    )


def test_live_instant_projects_to_completed_us_session() -> None:
    """Market session is a projection and never replaces research_as_of."""

    clock = parse_research_clock("2026-09-15T04:30:34Z")
    assert clock.market_session_date.isoformat() == "2026-09-14"
    assert clock.snapshot_date.isoformat() == "2026-09-15"
