"""Small read-only client for the public report API."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

from src.models.types import JsonObject


class ReportWebClientError(RuntimeError):
    """Raised when the read-only report API request fails."""


def fetch_report(
    api_base_url: str,
    report_id: str,
    *,
    timeout_seconds: int,
) -> JsonObject:
    """Fetch one report through FastAPI without accessing DuckDB directly."""

    if not report_id.strip():
        raise ValueError("report ID cannot be empty")
    endpoint = f"{api_base_url.rstrip('/')}/v1/reports/{quote(report_id, safe='')}"
    return _fetch_object(endpoint, timeout_seconds=timeout_seconds)


def fetch_task_status(
    api_base_url: str,
    job_id: str,
    *,
    timeout_seconds: int,
) -> JsonObject:
    """Fetch durable task progress through FastAPI."""

    if not job_id.strip():
        raise ValueError("job ID cannot be empty")
    endpoint = (
        f"{api_base_url.rstrip('/')}/v1/reports/jobs/" f"{quote(job_id, safe='')}"
    )
    return _fetch_object(endpoint, timeout_seconds=timeout_seconds)


def _fetch_object(endpoint: str, *, timeout_seconds: int) -> JsonObject:
    try:
        with urlopen(endpoint, timeout=timeout_seconds) as response:
            decoded = json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise ReportWebClientError("report API request failed") from exc
    if not isinstance(decoded, dict):
        raise ReportWebClientError("report API response was not an object")
    return decoded
