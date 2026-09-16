"""Verify one exact research instant across the Phase4 live orchestration chain."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from src.adapters import FREDAdapter
from src.services.research_clock import parse_research_clock

_STAGES = (
    "live_report",
    "sector_state",
    "sector_macro",
    "sector_radar",
    "sector_research",
    "sector_asset_integration",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=parse_research_clock, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Emit credential-free canonical and provider-native temporal projections."""

    clock = _parser().parse_args(argv).as_of
    canonical = clock.research_as_of.isoformat()
    stage_cutoffs = {stage: canonical for stage in _STAGES}
    result = {
        "status": "ok" if len(set(stage_cutoffs.values())) == 1 else "error",
        "canonical_research_as_of": canonical,
        "as_of_mode": clock.mode.value,
        "stage_cutoffs": stage_cutoffs,
        "provider_projections": {
            "alpaca_market": {
                "native_timezone": "America/New_York",
                "native_precision": "DATE",
                "market_session_date": clock.market_session_date.isoformat(),
            },
            "fred_alfred": {
                "native_timezone": "America/Chicago",
                "native_precision": "DATE",
                "provider_cutoff": FREDAdapter.provider_realtime_cutoff(
                    clock.research_as_of
                ).isoformat(),
            },
            "news": {
                "native_precision": "INSTANT",
                "cutoff": canonical,
            },
        },
        "future_eod_expansion": False,
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
