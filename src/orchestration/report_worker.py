"""Single-Worker execution for durable report jobs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

import structlog

from src.models.enums import TaskStatus
from src.orchestration.job_queue import ReportJobQueue
from src.repositories.report_jobs import ReportJobRepository
from src.schemas.common import ErrorInfo
from src.schemas.reports import GenerateReportRequest, ResearchReport

_LOGGER = structlog.get_logger(__name__)


class ReportGenerator(Protocol):
    """Generate one completed report without exposing implementation details."""

    def generate(self, request: GenerateReportRequest) -> ResearchReport:
        """Generate one completed report."""
        ...


class ReportWorker:
    """Claim and execute one queued report at a time."""

    def __init__(
        self,
        jobs: ReportJobRepository,
        queue: ReportJobQueue,
        generator: ReportGenerator,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Bind durable state, queue transport, and report generator."""

        self._jobs = jobs
        self._queue = queue
        self._generator = generator
        self._clock = clock or (lambda: datetime.now(UTC))

    def recover_interrupted(self) -> int:
        """Requeue records left running after an interrupted Worker."""

        recovered = self._jobs.requeue_interrupted()
        for job in self._jobs.list_queued():
            self._queue.enqueue(job.job_id)
        return recovered

    def run_once(self, *, timeout_seconds: int = 5) -> bool:
        """Execute at most one queue message."""

        job_id = self._queue.dequeue(timeout_seconds=timeout_seconds)
        if job_id is None:
            return False
        job = self._jobs.claim(job_id, started_at=self._clock())
        if job is None:
            return False
        try:
            report = self._generator.generate(job.request)
            if report.status is not TaskStatus.COMPLETED:
                raise RuntimeError("report generator returned a non-terminal report")
        except Exception as exc:
            _LOGGER.error(
                "report_job_failed",
                job_id=job.job_id,
                error_type=type(exc).__name__,
            )
            self._jobs.fail(
                job.job_id,
                error=ErrorInfo(
                    code="report_generation_failed",
                    message="Report generation failed.",
                    retryable=True,
                ),
                finished_at=self._clock(),
            )
        else:
            self._jobs.complete(
                job.job_id,
                report_id=report.report_id,
                finished_at=self._clock(),
            )
            _LOGGER.info(
                "report_job_completed",
                job_id=job.job_id,
                report_id=report.report_id,
            )
        return True
