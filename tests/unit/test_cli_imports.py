"""Subprocess smoke tests for cycle-safe checked-in CLI entry points."""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "module",
    (
        "scripts.live_report",
        "scripts.smoke_sector_state",
        "scripts.smoke_sector_macro",
        "scripts.smoke_sector_radar",
        "scripts.smoke_sector_research",
        "scripts.smoke_sector_asset_integration",
        "scripts.build_research_state",
        "scripts.build_research_attribution",
    ),
)
def test_cli_help_imports_without_cycle(module: str) -> None:
    """Every affected CLI must initialize in a fresh interpreter."""

    completed = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout
    assert "circular import" not in completed.stderr
