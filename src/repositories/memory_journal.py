"""Opt-in append-only audit sidecar in the existing Memory DuckDB database."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

from src.repositories.base import BaseRepository
from src.repositories.locking import duckdb_file_lock

type OrderedJournalSnapshot = tuple[tuple[int, str, str], ...]


def require_contiguous_history(snapshot: OrderedJournalSnapshot) -> None:
    """Check actual physical positions; never repair or synthesize stored sequence."""
    if any(
        sequence != position for position, (sequence, _, _) in enumerate(snapshot, 1)
    ):
        raise ValueError("JOURNAL_STALE_REVISION")


class MemoryJournalRepository(BaseRepository):
    """Store adapter receipts, never a second Memory or ResearchState database."""

    @property
    def database_path(self) -> Path:
        """Return the existing DB identity for composition-root consistency checks."""
        return self._database.path.resolve()

    def bootstrap(self) -> None:
        """Apply the additive, idempotent G85 audit-table migration."""
        self._execute(
            """CREATE TABLE IF NOT EXISTS memory_incremental_journal (
            stream VARCHAR NOT NULL, sequence BIGINT NOT NULL,
            identity VARCHAR NOT NULL, payload VARCHAR NOT NULL,
            PRIMARY KEY(stream, sequence), UNIQUE(stream, identity))""",
            (),
        )

    @contextmanager
    def serialized(self) -> Iterator[None]:
        """Serialize multi-step Memory writes across threads and local processes."""
        with duckdb_file_lock(self._database.path.with_suffix(".g85-operation")):
            yield

    def entries(self, stream: str) -> tuple[tuple[str, str], ...]:
        """Read the original ordered receipt bytes for replay and auditing."""
        rows = self._fetch_all(
            "SELECT identity,payload FROM memory_incremental_journal "
            "WHERE stream=? ORDER BY sequence",
            (stream,),
        )
        return tuple((str(r[0]), str(r[1])) for r in rows)

    def entries_with_sequence(self, stream: str) -> OrderedJournalSnapshot:
        """Read the full physical ordered history without projecting out sequence."""
        rows = self._fetch_all(
            "SELECT sequence,identity,payload FROM memory_incremental_journal "
            "WHERE stream=? ORDER BY sequence",
            (stream,),
        )
        return tuple((cast(int, r[0]), str(r[1]), str(r[2])) for r in rows)

    def append(
        self,
        stream: str,
        identity: str,
        payload: str,
        expected: int,
        *,
        expected_entries: tuple[tuple[str, str], ...] | None = None,
        expected_snapshot: OrderedJournalSnapshot | None = None,
    ) -> int:
        """Bind complete State history in the INSERT/idempotency transaction.

        Other streams retain their original optional pair-snapshot contract.
        State streams cannot downgrade to that projection or an omitted snapshot.
        """
        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT sequence,identity,payload FROM memory_incremental_journal "
                "WHERE stream=? ORDER BY sequence",
                [stream],
            ).fetchall()
            if stream.startswith("state-events:") and expected_snapshot is None:
                raise ValueError("JOURNAL_ORDERED_SNAPSHOT_REQUIRED")
            if expected_snapshot is not None:
                actual = tuple(
                    (int(seq), str(key), str(body)) for seq, key, body in rows
                )
                require_contiguous_history(actual)
                require_contiguous_history(expected_snapshot)
                if actual != expected_snapshot or len(actual) != expected:
                    raise ValueError("JOURNAL_STALE_REVISION")
            if (
                expected_entries is not None
                and tuple((str(key), str(body)) for _, key, body in rows)
                != expected_entries
            ):
                raise ValueError("JOURNAL_STALE_REVISION")
            for seq, key, body in rows:
                if key == identity:
                    if body != payload:
                        raise ValueError("JOURNAL_IDEMPOTENCY_CONFLICT")
                    return int(seq)
            if len(rows) != expected:
                raise ValueError("JOURNAL_STALE_REVISION")
            connection.execute(
                "INSERT INTO memory_incremental_journal VALUES (?,?,?,?)",
                [stream, expected + 1, identity, payload],
            )
            return expected + 1
