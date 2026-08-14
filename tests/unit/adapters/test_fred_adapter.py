"""Offline official-FRED and ALFRED-vintage adapter tests."""

from __future__ import annotations

import json
from datetime import date
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

from src.adapters import FREDAdapter
from src.adapters.http import ProviderHTTPResponse


class _Transport:
    def __init__(self) -> None:
        self.requests: list[Request] = []

    def send(self, request: Request, timeout: float) -> ProviderHTTPResponse:
        assert timeout == 7.0
        self.requests.append(request)
        path = urlparse(request.full_url).path
        body: object
        if path.endswith("/series"):
            body = {
                "seriess": [
                    {
                        "id": "FEDFUNDS",
                        "title": "Federal Funds Rate",
                        "units": "Percent",
                        "frequency": "Monthly",
                    }
                ]
            }
        else:
            body = {
                "observations": [
                    {
                        "realtime_start": "2026-08-10",
                        "realtime_end": "2026-08-10",
                        "date": "2026-07-01",
                        "value": "4.33",
                    }
                ]
            }
        return ProviderHTTPResponse(200, {}, json.dumps(body).encode())


def test_fred_preserves_realtime_vintage_and_stable_locator() -> None:
    transport = _Transport()
    adapter = FREDAdapter(
        api_key="fixture-key",
        request_timeout=7.0,
        http_transport=transport,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )

    records = list(
        adapter.fetch_macro_series(
            ["FEDFUNDS"],
            date(2026, 1, 1),
            date(2026, 8, 1),
            date(2026, 8, 10),
        )
    )

    assert records == [
        {
            "series_id": "FEDFUNDS",
            "region_code": "US",
            "observation_date": "2026-07-01",
            "indicator_name": "Federal Funds Rate",
            "value": "4.33",
            "unit": "Percent",
            "frequency": "Monthly",
            "realtime_start": "2026-08-10",
            "realtime_end": "2026-08-10",
            "source_locator": (
                "fred:series:FEDFUNDS:observation:2026-07-01:" "vintage:2026-08-10"
            ),
        }
    ]
    query = parse_qs(urlparse(transport.requests[1].full_url).query)
    assert query["realtime_start"] == ["2026-08-10"]
    assert query["realtime_end"] == ["2026-08-10"]
    assert transport.requests[0].get_header("User-agent") == "DeepInsight/0.1"
