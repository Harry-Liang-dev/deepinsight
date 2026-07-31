"""Replaceable application-service boundaries used by FastAPI routes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from threading import RLock
from typing import Protocol
from uuid import uuid4

from src.api.errors import ApiError, service_unavailable
from src.api.schemas import MemorySnapshotResponse
from src.models.enums import TaskStatus
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


def default_api_services() -> ApiServices:
    """Create safe, network-free defaults for a startable API process."""

    return ApiServices(
        report_tasks=InProcessReportTaskService(UnavailableReportGenerator()),
        reports=EmptyReportQueryService(),
        memory=UnavailableMemoryApiService(),
        snapshots=EmptySnapshotQueryService(),
    )
