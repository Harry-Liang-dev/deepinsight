"""Create one configured local DeepInsight backup."""

from __future__ import annotations

import json

from src.core import load_settings
from src.operations import create_backup


def main() -> None:
    """Create a backup and print its relative configured path."""

    settings = load_settings()
    path = create_backup(settings.storage)
    print(json.dumps({"status": "ok", "backup_path": str(path)}))


if __name__ == "__main__":
    main()
