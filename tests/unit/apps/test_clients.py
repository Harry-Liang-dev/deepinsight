"""Tests for Scheduler submission and read-only Web access."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from apps.scheduler import jobs
from apps.scheduler.jobs import SchedulerSubmissionError
from apps.web import client
from apps.web.client import ReportWebClientError
from src.core import AppSettings, SchedulerSettings, WebSettings


class Response:
    """Minimal context-managed HTTP response."""

    def __init__(self, payload: object) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read(self) -> bytes:
        """Return encoded response content."""

        return self._payload


def test_scheduler_submits_phase_one_request_through_public_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scheduler must not access repositories or place payloads in Redis."""

    captured: list[tuple[str, dict[str, Any]]] = []

    def fake_urlopen(request: Any, *, timeout: int) -> Response:
        captured.append(
            (
                request.full_url,
                json.loads(request.data),
            )
        )
        assert timeout == 4
        return Response({"job_id": "job-scheduled"})

    monkeypatch.setattr(jobs, "urlopen", fake_urlopen)
    settings = AppSettings(
        scheduler=SchedulerSettings(asset_ids=["US:AAPL"]),
        web=WebSettings(
            api_base_url="http://api:8000",
            request_timeout_seconds=4,
        ),
    )

    result = jobs.submit_daily_reports(
        settings,
        now=datetime(2026, 8, 7, tzinfo=UTC),
    )

    assert result == ["job-scheduled"]
    endpoint, payload = captured[0]
    assert endpoint == "http://api:8000/v1/reports/generate"
    assert payload["asset_ids"] == ["US:AAPL"]
    assert payload["report_type"] == "single_asset"
    assert payload["report_date"] == "2026-08-07"


def test_scheduler_rejects_response_without_job_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A superficially successful HTTP response is not sufficient."""

    monkeypatch.setattr(jobs, "urlopen", lambda *args, **kwargs: Response({}))

    with pytest.raises(SchedulerSubmissionError, match="no job ID"):
        jobs.submit_daily_reports(
            AppSettings(
                scheduler=SchedulerSettings(asset_ids=["US:AAPL"]),
            )
        )


def test_web_client_fetches_encoded_report_id_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Web should retrieve JSON only through the public GET endpoint."""

    calls: list[tuple[str, int]] = []

    def fake_urlopen(endpoint: str, *, timeout: int) -> Response:
        calls.append((endpoint, timeout))
        return Response({"report_id": "rep/one", "report_markdown": "# Report"})

    monkeypatch.setattr(client, "urlopen", fake_urlopen)

    result = client.fetch_report(
        "http://api:8000/",
        "rep/one",
        timeout_seconds=3,
    )

    assert result["report_id"] == "rep/one"
    assert calls == [("http://api:8000/v1/reports/rep%2Fone", 3)]


def test_web_client_fetches_durable_job_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read-only UI should expose Worker progress through FastAPI."""

    calls: list[str] = []

    def fake_urlopen(endpoint: str, *, timeout: int) -> Response:
        del timeout
        calls.append(endpoint)
        return Response({"job_id": "job/one", "status": "running"})

    monkeypatch.setattr(client, "urlopen", fake_urlopen)

    result = client.fetch_task_status(
        "http://api:8000",
        "job/one",
        timeout_seconds=3,
    )

    assert result["status"] == "running"
    assert calls == ["http://api:8000/v1/reports/jobs/job%2Fone"]


def test_web_client_rejects_non_object_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Web should fail explicitly on an invalid API contract."""

    monkeypatch.setattr(client, "urlopen", lambda *args, **kwargs: Response([]))

    with pytest.raises(ReportWebClientError, match="not an object"):
        client.fetch_report("http://api", "rep-1", timeout_seconds=3)
