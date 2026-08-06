"""Process-safe advisory locks for local DuckDB artifacts."""

from __future__ import annotations

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def duckdb_file_lock(database_path: Path) -> Iterator[None]:
    """Serialize local processes that mutate or copy one DuckDB file."""

    lock_path = database_path.with_suffix(f"{database_path.suffix}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
