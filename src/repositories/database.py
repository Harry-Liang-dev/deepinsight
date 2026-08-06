"""DuckDB connection lifecycle, bootstrap, and transaction boundaries."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

import duckdb

from src.repositories.locking import duckdb_file_lock
from src.repositories.schema import INDEX_DDL, TABLE_DDL


class DatabaseInitializationError(RuntimeError):
    """Raised when the DuckDB schema cannot be initialized."""


class DuckDBDatabase:
    """Own scoped DuckDB connections for one configured database file.

    Connections are serialized within the process and across local processes
    that use the same database path. Deployment still preserves a single
    report Worker so DuckDB remains an embedded database rather than a queue.
    """

    def __init__(self, path: str | Path) -> None:
        """Initialize a database handle without opening a connection.

        Args:
            path: Configured DuckDB file path.

        Raises:
            ValueError: If the supplied path is empty.
        """

        if not str(path).strip():
            raise ValueError("DuckDB path cannot be empty")
        self._path = Path(path)
        self._connection_lock = RLock()

    @property
    def path(self) -> Path:
        """Return the configured DuckDB file path."""

        return self._path

    def bootstrap(self) -> None:
        """Create all Phase One tables and indexes idempotently.

        Raises:
            DatabaseInitializationError: If DuckDB rejects schema creation.
        """

        self._ensure_parent_directory()
        try:
            with self.transaction() as connection:
                for statement in TABLE_DDL:
                    connection.execute(statement)
                for statement in INDEX_DDL:
                    connection.execute(statement)
        except duckdb.Error as exc:
            raise DatabaseInitializationError(
                f"failed to initialize DuckDB schema at {self._path}"
            ) from exc

    @contextmanager
    def connection(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """Yield a scoped connection and always close it afterward.

        Yields:
            An open DuckDB connection.
        """

        self._ensure_parent_directory()
        with self._connection_lock:
            with duckdb_file_lock(self._path):
                connection = duckdb.connect(database=str(self._path))
                try:
                    yield connection
                finally:
                    connection.close()

    @contextmanager
    def transaction(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """Yield a serialized transaction with commit-or-rollback semantics.

        Yields:
            An open DuckDB connection inside a transaction.
        """

        with self.connection() as connection:
            connection.execute("BEGIN TRANSACTION")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            else:
                connection.execute("COMMIT")

    def _ensure_parent_directory(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
