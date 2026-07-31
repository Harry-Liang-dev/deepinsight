"""Initialize the configured Phase One DuckDB database."""

from __future__ import annotations

from src.core import load_settings
from src.repositories import DuckDBDatabase


def main() -> int:
    """Bootstrap the configured DuckDB schema.

    Returns:
        Process exit code.
    """

    settings = load_settings()
    database = DuckDBDatabase(settings.storage.duckdb_path)
    database.bootstrap()
    print(f"DuckDB schema initialized: {database.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
