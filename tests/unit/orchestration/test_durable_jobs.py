"""Tests for durable report submission and single-Worker execution."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from redis import Redis

from src.api.errors import ApiError
from src.api.services import DurableReportTaskService
from src.models.enums import TaskStatus
from src.orchestration import (
    InMemoryReportJobQueue,
    JobQueueError,
    RedisReportJobQueue,
    ReportWorker,
)
from src.reports import ReportAssembler
from src.repositories import DuckDBDatabase, ReportJobRepository
from src.repositories.records import ReportJobRecord
from src.schemas.common import ErrorInfo
from src.schemas.reports import GenerateReportRequest, ResearchReport
from tests.fixtures.report_data import make_report_input

NOW = datetime(2026, 8, 7, 8, 0, tzinfo=UTC)


class CompletedGenerator:
    """Return one deterministic completed report."""

    def generate(self, request: GenerateReportRequest) -> ResearchReport:
        """Generate a completed fixture while retaining the public boundary."""

        del request
        return ReportAssembler().assemble(
            make_report_input(),
            status=TaskStatus.COMPLETED,
        )


class FailingGenerator:
    """Raise a private failure that must not escape durable task state."""

    def generate(self, request: GenerateReportRequest) -> ResearchReport:
        """Fail deterministically."""

        del request
        raise RuntimeError("private provider detail")


class FailingQueue(InMemoryReportJobQueue):
    """Reject publication after the request has been persisted."""

    def enqueue(self, job_id: str) -> None:
        """Fail without retaining the identifier."""

        del job_id
        raise JobQueueError("redis unavailable")


class FakeRedisClient:
    """Record the exact Redis list payload used by the queue adapter."""

    def __init__(self) -> None:
        self.items: list[bytes] = []

    def rpush(self, queue_name: str, value: bytes) -> int:
        """Append bytes as Redis would."""

        assert queue_name == "queue"
        self.items.append(value)
        return len(self.items)

    def blpop(
        self,
        queue_names: list[str],
        *,
        timeout: int,
    ) -> tuple[bytes, bytes] | None:
        """Pop one deterministic item."""

        assert queue_names == ["queue"]
        assert timeout == 0
        if not self.items:
            return None
        return b"queue", self.items.pop(0)


def _repository(tmp_path: Path) -> ReportJobRepository:
    database = DuckDBDatabase(tmp_path / "jobs.duckdb")
    database.bootstrap()
    return ReportJobRepository(database)


def test_durable_service_persists_request_and_queues_only_job_id(
    tmp_path: Path,
) -> None:
    """Submission should make DuckDB authoritative before Redis dispatch."""

    repository = _repository(tmp_path)
    queue = InMemoryReportJobQueue()
    request = make_report_input().request
    service = DurableReportTaskService(
        repository,
        queue,
        job_id_factory=lambda: "job-1",
        clock=lambda: NOW,
    )

    status = service.submit(request)

    stored = repository.get("job-1")
    assert status.status is TaskStatus.QUEUED
    assert stored is not None
    assert stored.request == request
    assert queue.dequeue(timeout_seconds=0) == "job-1"


def test_redis_adapter_transports_utf8_job_id_only() -> None:
    """Redis boundary should encode no request, prompt, or credential payload."""

    fake = FakeRedisClient()
    queue = RedisReportJobQueue(
        "redis://unused",
        queue_name="queue",
        client=cast(Redis, fake),
    )

    queue.enqueue("job-一")

    assert fake.items == ["job-一".encode()]
    assert queue.dequeue(timeout_seconds=0) == "job-一"
    assert queue.dequeue(timeout_seconds=0) is None


def test_worker_claims_and_completes_one_persisted_job(tmp_path: Path) -> None:
    """One Worker iteration should atomically complete a queued job."""

    repository = _repository(tmp_path)
    queue = InMemoryReportJobQueue()
    repository.create(
        ReportJobRecord(
            job_id="job-complete",
            request=make_report_input().request,
            status=TaskStatus.QUEUED,
            created_at=NOW,
        )
    )
    queue.enqueue("job-complete")
    worker = ReportWorker(
        repository,
        queue,
        CompletedGenerator(),
        clock=lambda: NOW,
    )

    assert worker.run_once(timeout_seconds=0)

    stored = repository.get("job-complete")
    assert stored is not None
    assert stored.status is TaskStatus.COMPLETED
    assert stored.report_id == "report-1"
    assert stored.attempt_count == 1
    assert stored.error is None


def test_queue_failure_terminalizes_persisted_submission(tmp_path: Path) -> None:
    """An API 503 must not leave a queued job that later executes invisibly."""

    repository = _repository(tmp_path)
    service = DurableReportTaskService(
        repository,
        FailingQueue(),
        job_id_factory=lambda: "job-no-queue",
        clock=lambda: NOW,
    )

    with pytest.raises(ApiError) as captured:
        service.submit(make_report_input().request)

    stored = repository.get("job-no-queue")
    assert captured.value.status_code == 503
    assert stored is not None
    assert stored.status is TaskStatus.FAILED
    assert stored.error is not None
    assert stored.error.code == "report_queue_unavailable"


def test_worker_maps_private_failure_to_safe_terminal_error(tmp_path: Path) -> None:
    """Provider details must not leak into durable API-visible task errors."""

    repository = _repository(tmp_path)
    queue = InMemoryReportJobQueue()
    repository.create(
        ReportJobRecord(
            job_id="job-failed",
            request=make_report_input().request,
            status=TaskStatus.QUEUED,
            created_at=NOW,
        )
    )
    queue.enqueue("job-failed")

    assert ReportWorker(
        repository,
        queue,
        FailingGenerator(),
        clock=lambda: NOW,
    ).run_once(timeout_seconds=0)

    stored = repository.get("job-failed")
    assert stored is not None
    assert stored.status is TaskStatus.FAILED
    assert stored.error == ErrorInfo(
        code="report_generation_failed",
        message="Report generation failed.",
        retryable=True,
    )
    assert "private" not in stored.error.message


def test_worker_recovers_interrupted_job_and_ignores_duplicate_message(
    tmp_path: Path,
) -> None:
    """Restart recovery should requeue running jobs without double execution."""

    repository = _repository(tmp_path)
    queue = InMemoryReportJobQueue()
    repository.create(
        ReportJobRecord(
            job_id="job-recover",
            request=make_report_input().request,
            status=TaskStatus.QUEUED,
            created_at=NOW,
        )
    )
    assert repository.claim("job-recover", started_at=NOW) is not None
    worker = ReportWorker(
        repository,
        queue,
        CompletedGenerator(),
        clock=lambda: NOW,
    )

    assert worker.recover_interrupted() == 1
    assert worker.run_once(timeout_seconds=0)
    queue.enqueue("job-recover")
    assert not worker.run_once(timeout_seconds=0)

    stored = repository.get("job-recover")
    assert stored is not None
    assert stored.status is TaskStatus.COMPLETED
    assert stored.attempt_count == 2
