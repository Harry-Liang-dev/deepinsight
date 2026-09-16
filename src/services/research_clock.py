"""Canonical research-instant parsing and provider calendar projections."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from src.schemas.temporal import require_utc_aware

_NEW_YORK = ZoneInfo("America/New_York")


class ResearchAsOfMode(StrEnum):
    """Backward-compatible date mode and exact live instant mode."""

    DATE = "date"
    INSTANT = "instant"


@dataclass(frozen=True)
class ResearchClock:
    """One immutable canonical cutoff plus explicit calendar projections."""

    research_as_of: datetime
    mode: ResearchAsOfMode

    @property
    def snapshot_date(self) -> date:
        """Return the legacy UTC date used by date-keyed Sector artifacts."""

        return self.research_as_of.date()

    @property
    def market_session_date(self) -> date:
        """Return the latest completed US market session (weekday calendar v1)."""

        local = self.research_as_of.astimezone(_NEW_YORK)
        candidate = local.date()
        if local.timetz().replace(tzinfo=None) < time(16):
            candidate -= timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate -= timedelta(days=1)
        return candidate


def parse_research_clock(value: str) -> ResearchClock:
    """Parse a legacy date or a timezone-aware ISO-8601 instant."""

    raw = value.strip()
    try:
        if len(raw) == 10:
            parsed_date = date.fromisoformat(raw)
            return ResearchClock(
                research_as_of=datetime.combine(parsed_date, time.max, tzinfo=UTC),
                mode=ResearchAsOfMode.DATE,
            )
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return ResearchClock(
            research_as_of=require_utc_aware(parsed),
            mode=ResearchAsOfMode.INSTANT,
        )
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "as-of must be YYYY-MM-DD or a timezone-aware ISO-8601 instant"
        ) from exc


def live_research_clock(now: datetime | None = None) -> ResearchClock:
    """Capture the single exact UTC information cutoff for a live run."""

    instant = datetime.now(UTC) if now is None else require_utc_aware(now)
    return ResearchClock(research_as_of=instant, mode=ResearchAsOfMode.INSTANT)
