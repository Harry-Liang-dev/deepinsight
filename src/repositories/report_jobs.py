"""Durable report-job persistence and atomic lifecycle transitions."""

from __future__ import annotations

from datetime import datetime

import duckdb

from src.models.enums import TaskStatus
from src.repositories.base import (
    BaseRepository,
    RepositoryError,
    decode_json_object,
    encode_json,
)
from src.repositories.records import ReportJobRecord
from src.schemas.common import ErrorInfo
from src.schemas.reports import GenerateReportRequest

_COLUMNS = (
    "job_id",
    "request_json",
    "status",
    "report_id",
    "error_json",
    "attempt_count",
    "created_at",
    "started_at",
    "finished_at",
)


class ReportJobRepository(BaseRepository):
    """Store report requests independently from API and queue implementations."""

    def create(self, record: ReportJobRecord) -> None:
        """Insert one new queued report job.

        Args:
            record: Validated queued job.

        Raises:
            RepositoryError: If the job is not queued or cannot be inserted.
        """

        if record.status is not TaskStatus.QUEUED:
            raise RepositoryError("new report job must be queued")
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO report_jobs (
                        job_id, request_json, status, report_id, error_json,
                        attempt_count, created_at, started_at, finished_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), ?, ?)
                    """,
                    (
                        record.job_id,
                        encode_json(record.request.model_dump(mode="json")),
                        record.status.value,
                        record.report_id,
                        _encode_error(record.error),
                        record.attempt_count,
                        record.created_at,
                        record.started_at,
                        record.finished_at,
                    ),
                )
        except duckdb.Error as exc:
            raise RepositoryError("failed to create report job") from exc

    def get(self, job_id: str) -> ReportJobRecord | None:
        """Return one durable report job.

        Args:
            job_id: Stable job identifier.

        Returns:
            Matching record, or ``None``.
        """

        row = self._fetch_one(
            f"SELECT {', '.join(_COLUMNS)} FROM report_jobs WHERE job_id = ?",
            (job_id,),
        )
        return None if row is None else _map_row(row)

    def claim(self, job_id: str, *, started_at: datetime) -> ReportJobRecord | None:
        """Atomically claim a queued job for the single Worker.

        Args:
            job_id: Stable job identifier.
            started_at: Worker claim timestamp.

        Returns:
            Running job when claimed, otherwise ``None``.
        """

        try:
            with self._database.transaction() as connection:
                changed = connection.execute(
                    """
                    UPDATE report_jobs
                    SET status = ?, started_at = ?, finished_at = NULL,
                        error_json = NULL, attempt_count = attempt_count + 1
                    WHERE job_id = ? AND status = ?
                    RETURNING job_id
                    """,
                    (
                        TaskStatus.RUNNING.value,
                        started_at,
                        job_id,
                        TaskStatus.QUEUED.value,
                    ),
                ).fetchone()
                if changed is None:
                    return None
                row = connection.execute(
                    f"SELECT {', '.join(_COLUMNS)} FROM report_jobs WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
        except duckdb.Error as exc:
            raise RepositoryError("failed to claim report job") from exc
        if row is None:
            raise RepositoryError("claimed report job disappeared")
        return _map_row(row)

    def complete(
        self,
        job_id: str,
        *,
        report_id: str,
        finished_at: datetime,
    ) -> None:
        """Move one running job to completed.

        Args:
            job_id: Stable job identifier.
            report_id: Persisted report identifier.
            finished_at: Completion timestamp.
        """

        self._transition(
            job_id,
            expected_status=TaskStatus.RUNNING,
            status=TaskStatus.COMPLETED,
            report_id=report_id,
            error=None,
            finished_at=finished_at,
        )

    def fail(
        self,
        job_id: str,
        *,
        error: ErrorInfo,
        finished_at: datetime,
    ) -> None:
        """Move one running job to failed with a safe error.

        Args:
            job_id: Stable job identifier.
            error: Public-safe failure information.
            finished_at: Failure timestamp.
        """

        self._transition(
            job_id,
            expected_status=TaskStatus.RUNNING,
            status=TaskStatus.FAILED,
            report_id=None,
            error=error,
            finished_at=finished_at,
        )

    def fail_queued(
        self,
        job_id: str,
        *,
        error: ErrorInfo,
        finished_at: datetime,
    ) -> None:
        """Terminalize a job whose queue publication failed."""

        self._transition(
            job_id,
            expected_status=TaskStatus.QUEUED,
            status=TaskStatus.FAILED,
            report_id=None,
            error=error,
            finished_at=finished_at,
        )

    def requeue_interrupted(self) -> int:
        """Recover jobs left running by a terminated Worker.

        Returns:
            Number of jobs returned to the queueable state.
        """

        try:
            with self._database.transaction() as connection:
                rows = connection.execute(
                    """
                    UPDATE report_jobs
                    SET status = ?, started_at = NULL,
                        error_json = NULL, finished_at = NULL
                    WHERE status = ?
                    RETURNING job_id
                    """,
                    (TaskStatus.QUEUED.value, TaskStatus.RUNNING.value),
                ).fetchall()
        except duckdb.Error as exc:
            raise RepositoryError("failed to recover interrupted report jobs") from exc
        return len(rows)

    def list_queued(self) -> list[ReportJobRecord]:
        """Return queued jobs in deterministic submission order."""

        rows = self._fetch_all(
            f"""
            SELECT {", ".join(_COLUMNS)}
            FROM report_jobs
            WHERE status = ?
            ORDER BY created_at, job_id
            """,
            (TaskStatus.QUEUED.value,),
        )
        return [_map_row(row) for row in rows]

    def _transition(
        self,
        job_id: str,
        *,
        expected_status: TaskStatus,
        status: TaskStatus,
        report_id: str | None,
        error: ErrorInfo | None,
        finished_at: datetime,
    ) -> None:
        try:
            with self._database.transaction() as connection:
                row = connection.execute(
                    """
                    UPDATE report_jobs
                    SET status = ?, report_id = ?, error_json = ?, finished_at = ?
                    WHERE job_id = ? AND status = ?
                    RETURNING job_id
                    """,
                    (
                        status.value,
                        report_id,
                        _encode_error(error),
                        finished_at,
                        job_id,
                        expected_status.value,
                    ),
                ).fetchone()
                if row is None:
                    raise RepositoryError(
                        f"report job cannot transition to {status.value}"
                    )
        except duckdb.Error as exc:
            raise RepositoryError("failed to update report job") from exc


def _encode_error(error: ErrorInfo | None) -> str | None:
    return None if error is None else encode_json(error.model_dump(mode="json"))


def _map_row(row: tuple[object, ...]) -> ReportJobRecord:
    values = dict(zip(_COLUMNS, row, strict=True))
    values["request"] = GenerateReportRequest.model_validate(
        decode_json_object(values.pop("request_json"))
    )
    raw_error = values.pop("error_json")
    values["error"] = (
        None
        if raw_error is None
        else ErrorInfo.model_validate(decode_json_object(raw_error))
    )
    return ReportJobRecord.model_validate(values)
