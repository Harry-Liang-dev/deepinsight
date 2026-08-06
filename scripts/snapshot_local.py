"""Create one configured local DeepInsight snapshot."""

from __future__ import annotations

import json

from src.core import load_settings
from src.operations import create_snapshot


def main() -> None:
    """Create a snapshot and print its relative configured path."""

    settings = load_settings()
    path = create_snapshot(settings.storage)
    print(json.dumps({"status": "ok", "snapshot_path": str(path)}))


if __name__ == "__main__":
    main()
