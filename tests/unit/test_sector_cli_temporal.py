"""Phase4 CLI exact-instant contract tests without Provider calls."""

from __future__ import annotations

from datetime import UTC, datetime

from scripts import (
    live_report,
    smoke_sector_asset_integration,
    smoke_sector_macro,
    smoke_sector_radar,
    smoke_sector_research,
    smoke_sector_state,
)

_INSTANT = "2026-09-15T12:30:34+08:00"
_EXPECTED = datetime(2026, 9, 15, 4, 30, 34, tzinfo=UTC)


def test_all_phase4_live_clis_preserve_identical_exact_instant() -> None:
    """Every live-chain CLI uses the shared parser without EOD expansion."""

    parsers = (
        live_report._parser(),
        smoke_sector_state._parser(),
        smoke_sector_macro._parser(),
        smoke_sector_radar._parser(),
        smoke_sector_research._parser(),
        smoke_sector_asset_integration._parser(),
    )
    required_args = (
        (),
        (),
        ("--sector-state-db", "state.duckdb"),
        (
            "--sector-state-db",
            "state.duckdb",
            "--sector-macro-db",
            "macro.duckdb",
        ),
        (),
        (),
    )
    clocks = [
        parser.parse_args((*extra, "--as-of", _INSTANT)).as_of
        for parser, extra in zip(parsers, required_args, strict=True)
    ]
    assert {clock.research_as_of for clock in clocks} == {_EXPECTED}


def test_live_report_manifest_clock_is_not_market_eod() -> None:
    """The canonical instant and latest completed session remain separate."""

    clock = live_report._parser().parse_args(("--as-of", _INSTANT)).as_of
    assert clock.research_as_of == _EXPECTED
    assert clock.market_session_date.isoformat() == "2026-09-14"
