"""Replaceable application-service boundaries used by FastAPI routes."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from threading import RLock
from typing import Protocol
from uuid import uuid4

from src.api.errors import ApiError, service_unavailable
from src.api.schemas import MemorySnapshotResponse
from src.models.enums import TaskStatus
from src.orchestration.job_queue import JobQueueError, ReportJobQueue
from src.repositories import ReportJobRecord, ReportJobRepository, RepositoryError
from src.schemas.common import ErrorInfo, TaskStatusResponse
from src.schemas.memory import (
    MemorySearchRequest,
    MemorySearchResponse,
    MemoryWriteRequest,
    MemoryWriteResult,
)
from src.schemas.reports import GenerateReportRequest, ResearchReport


class ReportGenerator(Protocol):
    """Application boundary that turns one request into a completed report."""

    def generate(self, request: GenerateReportRequest) -> ResearchReport:
        """Generate and persist one completed report."""
        ...


class ReportTaskService(Protocol):
    """Submit, execute, and inspect local report jobs."""

    def submit(self, request: GenerateReportRequest) -> TaskStatusResponse:
        """Create one queued report job."""
        ...

    def run(self, job_id: str, request: GenerateReportRequest) -> None:
        """Execute one previously submitted job."""
        ...

    def get_status(self, job_id: str) -> TaskStatusResponse | None:
        """Return current job status, or ``None``."""
        ...


class ReportQueryService(Protocol):
    """Read reports without exposing Repository or SQL details."""

    def get(self, report_id: str) -> ResearchReport | None:
        """Return one report, or ``None``."""
        ...


class MemoryApiService(Protocol):
    """Public Memory operations exposed by the API."""

    def write(self, request: MemoryWriteRequest) -> MemoryWriteResult:
        """Write one attributable Memory item."""
        ...

    def search(self, request: MemorySearchRequest) -> MemorySearchResponse:
        """Search Memory through the existing application service."""
        ...


class SnapshotQueryService(Protocol):
    """Query existing snapshots without creating a new snapshot."""

    def get(self, snapshot_date: date) -> MemorySnapshotResponse | None:
        """Return safe snapshot metadata, or ``None``."""
        ...


@dataclass(frozen=True, slots=True)
class ApiServices:
    """All replaceable application services required by the HTTP layer."""

    report_tasks: ReportTaskService
    reports: ReportQueryService
    memory: MemoryApiService
    snapshots: SnapshotQueryService


class InProcessReportTaskService:
    """Run report jobs after the response without a distributed queue."""

    def __init__(
        self,
        generator: ReportGenerator,
        *,
        job_id_factory: Callable[[], str] | None = None,
    ) -> None:
        """Bind one report generator and instance-local task state."""

        self._generator = generator
        self._job_id_factory = job_id_factory or (lambda: f"job_report_{uuid4().hex}")
        self._jobs: dict[str, TaskStatusResponse] = {}
        self._lock = RLock()

    def submit(self, request: GenerateReportRequest) -> TaskStatusResponse:
        """Create one queued report job without running report logic."""

        del request
        job_id = self._job_id_factory()
        if not job_id.strip():
            raise service_unavailable("Report task ID generation failed.")
        status = TaskStatusResponse(job_id=job_id, status=TaskStatus.QUEUED)
        with self._lock:
            if job_id in self._jobs:
                raise service_unavailable("Report task ID collision occurred.")
            self._jobs[job_id] = status
        return status.model_copy(deep=True)

    def run(self, job_id: str, request: GenerateReportRequest) -> None:
        """Execute a queued job and retain a safe terminal status."""

        with self._lock:
            if job_id not in self._jobs:
                return
            self._jobs[job_id] = TaskStatusResponse(
                job_id=job_id,
                status=TaskStatus.RUNNING,
            )
        try:
            report = self._generator.generate(request)
            if report.status is not TaskStatus.COMPLETED:
                raise RuntimeError("report generator returned a non-terminal report")
            terminal = TaskStatusResponse(
                job_id=job_id,
                status=TaskStatus.COMPLETED,
                report_id=report.report_id,
            )
        except ApiError as exc:
            terminal = TaskStatusResponse(
                job_id=job_id,
                status=TaskStatus.FAILED,
                error=ErrorInfo(
                    code=exc.code,
                    message=exc.message,
                    retryable=exc.retryable,
                ),
            )
        except Exception:
            terminal = TaskStatusResponse(
                job_id=job_id,
                status=TaskStatus.FAILED,
                error=ErrorInfo(
                    code="report_generation_failed",
                    message="Report generation failed.",
                    retryable=True,
                ),
            )
        with self._lock:
            self._jobs[job_id] = terminal

    def get_status(self, job_id: str) -> TaskStatusResponse | None:
        """Return a defensive copy of one local task state."""

        with self._lock:
            status = self._jobs.get(job_id)
            return None if status is None else status.model_copy(deep=True)


class DurableReportTaskService:
    """Persist report requests in DuckDB and enqueue only their identifiers."""

    def __init__(
        self,
        jobs: ReportJobRepository,
        queue: ReportJobQueue,
        *,
        job_id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Bind durable task state and queue transport."""

        self._jobs = jobs
        self._queue = queue
        self._job_id_factory = job_id_factory or (lambda: f"job_report_{uuid4().hex}")
        self._clock = clock or (lambda: datetime.now(UTC))

    def submit(self, request: GenerateReportRequest) -> TaskStatusResponse:
        """Persist a queued request before publishing its stable identifier."""

        job_id = self._job_id_factory()
        if not job_id.strip():
            raise service_unavailable("Report task ID generation failed.")
        created_at = self._clock()
        try:
            self._jobs.create(
                ReportJobRecord(
                    job_id=job_id,
                    request=request,
                    status=TaskStatus.QUEUED,
                    created_at=created_at,
                )
            )
        except RepositoryError as exc:
            raise service_unavailable("Report task submission failed.") from exc
        try:
            self._queue.enqueue(job_id)
        except JobQueueError as exc:
            error = ErrorInfo(
                code="report_queue_unavailable",
                message="Report task queue is unavailable.",
                retryable=True,
            )
            try:
                self._jobs.fail_queued(
                    job_id,
                    error=error,
                    finished_at=self._clock(),
                )
            except RepositoryError as compensation_error:
                raise service_unavailable(
                    "Report task submission and compensation failed."
                ) from compensation_error
            raise service_unavailable("Report task submission failed.") from exc
        return TaskStatusResponse(job_id=job_id, status=TaskStatus.QUEUED)

    def run(self, job_id: str, request: GenerateReportRequest) -> None:
        """Leave execution to the separately deployed single Worker."""

        del job_id, request

    def get_status(self, job_id: str) -> TaskStatusResponse | None:
        """Read durable task state without consulting Redis."""

        try:
            record = self._jobs.get(job_id)
        except RepositoryError as exc:
            raise service_unavailable("Report task status is unavailable.") from exc
        if record is None:
            return None
        return TaskStatusResponse(
            job_id=record.job_id,
            status=record.status,
            report_id=record.report_id,
            error=record.error,
        )


class UnavailableReportGenerator:
    """Explicit default used until a process wires the full report workflow."""

    def generate(self, request: GenerateReportRequest) -> ResearchReport:
        """Fail safely without invoking any external dependency."""

        del request
        raise service_unavailable("Report generation is not configured.")


class EmptyReportQueryService:
    """Default report query with no configured persistence dependency."""

    def get(self, report_id: str) -> ResearchReport | None:
        """Return no report without touching local storage."""

        del report_id
        return None


class UnavailableMemoryApiService:
    """Default Memory boundary that fails explicitly and safely."""

    def write(self, request: MemoryWriteRequest) -> MemoryWriteResult:
        """Reject writes until a Memory service is injected."""

        del request
        raise service_unavailable("Memory service is not configured.")

    def search(self, request: MemorySearchRequest) -> MemorySearchResponse:
        """Reject searches until a Memory service is injected."""

        del request
        raise service_unavailable("Memory service is not configured.")


class EmptySnapshotQueryService:
    """Default query-only snapshot boundary."""

    def get(self, snapshot_date: date) -> MemorySnapshotResponse | None:
        """Return no snapshot without inspecting the filesystem."""

        del snapshot_date
        return None


class LocalSnapshotQueryService:
    """Read validated local snapshot manifests without creating artifacts."""

    def __init__(self, snapshot_root: Path) -> None:
        """Bind the configured snapshot root."""

        self._snapshot_root = snapshot_root

    def get(self, snapshot_date: date) -> MemorySnapshotResponse | None:
        """Return the latest valid local snapshot for one UTC date."""

        if not self._snapshot_root.is_dir():
            return None
        candidates: list[tuple[datetime, Path]] = []
        for bundle in self._snapshot_root.iterdir():
            manifest_path = bundle / "manifest.json"
            if not bundle.is_dir() or not manifest_path.is_file():
                continue
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                created_at = datetime.fromisoformat(str(payload["created_at"]))
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                continue
            if (
                payload.get("bundle_type") == "snapshot"
                and created_at.date() == snapshot_date
            ):
                candidates.append((created_at, bundle))
        if not candidates:
            return None
        _, latest = max(candidates, key=lambda candidate: candidate[0])
        return MemorySnapshotResponse(
            snapshot_date=snapshot_date,
            duckdb_artifact=(
                "platform.duckdb" if (latest / "platform.duckdb").is_file() else None
            ),
            faiss_artifacts=(
                ["faiss.tar.gz"] if (latest / "faiss.tar.gz").is_file() else []
            ),
        )


def default_api_services() -> ApiServices:
    """Create safe, network-free defaults for a startable API process."""

    return ApiServices(
        report_tasks=InProcessReportTaskService(UnavailableReportGenerator()),
        reports=EmptyReportQueryService(),
        memory=UnavailableMemoryApiService(),
        snapshots=EmptySnapshotQueryService(),
    )
