"""Minimal replaceable queue boundary for durable Phase One report jobs."""

from __future__ import annotations

from collections import deque
from typing import Protocol, cast

from redis import Redis
from redis.exceptions import RedisError


class JobQueueError(RuntimeError):
    """Raised when report job queue operations fail."""


class ReportJobQueue(Protocol):
    """Queue stable job identifiers without duplicating request payloads."""

    def enqueue(self, job_id: str) -> None:
        """Append one job identifier."""
        ...

    def dequeue(self, *, timeout_seconds: int) -> str | None:
        """Return the next job identifier, or ``None`` after timeout."""
        ...


class RedisReportJobQueue:
    """Redis list queue with one small UTF-8 job identifier per message."""

    def __init__(
        self,
        redis_url: str,
        *,
        queue_name: str = "deepinsight:report_jobs",
        client: Redis | None = None,
    ) -> None:
        """Bind a Redis connection and queue name."""

        if not redis_url.strip():
            raise ValueError("Redis URL cannot be empty")
        if not queue_name.strip():
            raise ValueError("report queue name cannot be empty")
        self._client = client or Redis.from_url(redis_url, decode_responses=False)
        self._queue_name = queue_name

    def enqueue(self, job_id: str) -> None:
        """Append one validated job identifier."""

        if not job_id.strip():
            raise JobQueueError("report job ID cannot be empty")
        try:
            self._client.rpush(self._queue_name, job_id.encode("utf-8"))
        except RedisError as exc:
            raise JobQueueError("failed to enqueue report job") from exc

    def dequeue(self, *, timeout_seconds: int) -> str | None:
        """Block for at most the configured duration and decode one ID."""

        if timeout_seconds < 0:
            raise ValueError("queue timeout cannot be negative")
        try:
            item = cast(
                tuple[bytes, bytes] | None,
                self._client.blpop(
                    [self._queue_name],
                    timeout=timeout_seconds,
                ),
            )
        except RedisError as exc:
            raise JobQueueError("failed to dequeue report job") from exc
        if item is None:
            return None
        _, raw_job_id = item
        try:
            job_id = raw_job_id.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise JobQueueError("report queue message was not UTF-8") from exc
        if not job_id.strip():
            raise JobQueueError("report queue returned an empty job ID")
        return job_id


class InMemoryReportJobQueue:
    """Deterministic queue used by offline tests."""

    def __init__(self) -> None:
        self._items: deque[str] = deque()

    def enqueue(self, job_id: str) -> None:
        """Append one job identifier."""

        if not job_id.strip():
            raise JobQueueError("report job ID cannot be empty")
        self._items.append(job_id)

    def dequeue(self, *, timeout_seconds: int) -> str | None:
        """Return immediately without sleeping."""

        if timeout_seconds < 0:
            raise ValueError("queue timeout cannot be negative")
        return None if not self._items else self._items.popleft()
