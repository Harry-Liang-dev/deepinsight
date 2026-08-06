"""Deterministic daily report submission through the public API."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.core import AppSettings
from src.models.identifiers import AssetId
from src.reports import STANDARD_SECTION_NAMES


class SchedulerSubmissionError(RuntimeError):
    """Raised when the public report API rejects a scheduled request."""


def submit_daily_reports(
    settings: AppSettings,
    *,
    now: datetime | None = None,
) -> list[str]:
    """Submit one single-asset request per configured asset."""

    report_date = (now or datetime.now(UTC)).date().isoformat()
    job_ids: list[str] = []
    for configured in settings.scheduler.asset_ids:
        asset_id = AssetId(configured)
        payload = {
            "report_date": report_date,
            "market_scope": asset_id.market.value,
            "report_type": "single_asset",
            "asset_ids": [str(asset_id)],
            "language": "en",
            "include_sections": list(STANDARD_SECTION_NAMES),
            "force_refresh": False,
        }
        endpoint = f"{settings.web.api_base_url.rstrip('/')}/v1/reports/generate"
        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(
                request,
                timeout=settings.web.request_timeout_seconds,
            ) as response:
                decoded = json.loads(response.read())
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise SchedulerSubmissionError(
                "scheduled report submission failed"
            ) from exc
        job_id = decoded.get("job_id") if isinstance(decoded, dict) else None
        if not isinstance(job_id, str) or not job_id:
            raise SchedulerSubmissionError(
                "scheduled report response contained no job ID"
            )
        job_ids.append(job_id)
    return job_ids
