"""Shared Repository mechanics and persistence serialization helpers."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import cast

import duckdb
from pydantic import BaseModel

from src.models.types import JsonObject, JsonValue
from src.repositories.database import DuckDBDatabase


class RepositoryError(RuntimeError):
    """Raised when a persistence operation cannot be completed."""

    def __init__(
        self,
        message: str,
        *,
        database_error_type: str | None = None,
    ) -> None:
        """Retain only a safe database exception class for diagnostics."""

        super().__init__(message)
        self.database_error_type = database_error_type


class TransientRepositoryError(RepositoryError):
    """Raised for a narrowly classified retryable database failure."""


class BaseRepository:
    """Base class that keeps DuckDB execution inside the Repository layer."""

    def __init__(self, database: DuckDBDatabase) -> None:
        """Bind the Repository to one database lifecycle owner.

        Args:
            database: Bootstrapped DuckDB database handle.
        """

        self._database = database

    def _execute(self, sql: str, parameters: Sequence[object]) -> None:
        try:
            with self._database.transaction() as connection:
                connection.execute(sql, parameters)
        except duckdb.Error as exc:
            raise _repository_error(exc, operation="write") from None

    def _executemany(
        self,
        sql: str,
        parameter_rows: Sequence[Sequence[object]],
    ) -> None:
        """Execute one statement for many rows within one transaction."""

        if not parameter_rows:
            return
        try:
            with self._database.transaction() as connection:
                connection.executemany(sql, parameter_rows)
        except duckdb.Error as exc:
            raise _repository_error(exc, operation="write") from None

    def _fetch_one(
        self,
        sql: str,
        parameters: Sequence[object],
    ) -> tuple[object, ...] | None:
        try:
            with self._database.connection() as connection:
                row = connection.execute(sql, parameters).fetchone()
        except duckdb.Error as exc:
            raise _repository_error(exc, operation="read") from None
        return cast(tuple[object, ...] | None, row)

    def _fetch_all(
        self,
        sql: str,
        parameters: Sequence[object],
    ) -> list[tuple[object, ...]]:
        try:
            with self._database.connection() as connection:
                rows = connection.execute(sql, parameters).fetchall()
        except duckdb.Error as exc:
            raise _repository_error(exc, operation="read") from None
        return cast(list[tuple[object, ...]], rows)


def _repository_error(
    exc: duckdb.Error,
    *,
    operation: str,
) -> RepositoryError:
    """Map DuckDB failures without exposing SQL, values, or raw messages."""

    error_type = type(exc).__name__
    message = f"DuckDB {operation} operation failed"
    if _is_transient_duckdb_error(exc):
        return TransientRepositoryError(
            message,
            database_error_type=error_type,
        )
    return RepositoryError(message, database_error_type=error_type)


def _is_transient_duckdb_error(exc: duckdb.Error) -> bool:
    """Recognize only bounded connection, conflict, and lock failures."""

    if isinstance(exc, duckdb.SerializationException):
        return True
    normalized = str(exc).casefold()
    if isinstance(exc, duckdb.ConnectionException):
        return any(
            marker in normalized
            for marker in (
                "temporary",
                "temporarily",
                "connection reset",
                "connection refused",
                "could not open",
                "failed to open",
            )
        )
    if isinstance(exc, duckdb.TransactionException):
        return any(marker in normalized for marker in ("conflict", "serialization"))
    if isinstance(exc, duckdb.IOException):
        return any(
            marker in normalized
            for marker in (
                "could not set lock",
                "conflicting lock",
                "database is locked",
                "resource temporarily unavailable",
            )
        )
    return False


def encode_json(value: JsonValue) -> str:
    """Serialize a validated JSON-compatible value deterministically.

    Args:
        value: JSON-compatible domain value.

    Returns:
        Compact deterministic JSON text.
    """

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def decode_json_value(value: object) -> JsonValue:
    """Deserialize one persisted JSON value.

    Args:
        value: DuckDB scalar expected to contain JSON text.

    Returns:
        The decoded JSON-compatible value.

    Raises:
        RepositoryError: If the stored value is not valid JSON.
    """

    try:
        decoded: object = json.loads(str(value))
    except (TypeError, ValueError) as exc:
        raise RepositoryError("stored value is not valid JSON") from exc
    return cast(JsonValue, decoded)


def decode_json_object(value: object) -> JsonObject:
    """Deserialize one persisted JSON object.

    Args:
        value: DuckDB scalar expected to contain JSON object text.

    Returns:
        The decoded JSON object.

    Raises:
        RepositoryError: If the stored value is not a JSON object.
    """

    decoded = decode_json_value(value)
    if not isinstance(decoded, dict):
        raise RepositoryError("stored JSON value is not an object")
    return decoded


def map_row[RecordT: BaseModel](
    model_type: type[RecordT],
    columns: Sequence[str],
    row: Sequence[object],
) -> RecordT:
    """Validate a positional DuckDB row as a typed record.

    Args:
        model_type: Pydantic model class used at the Repository boundary.
        columns: Selected columns in result order.
        row: Positional DuckDB result.

    Returns:
        A validated model instance.
    """

    return model_type.model_validate(dict(zip(columns, row, strict=True)))
