"""Offline official-FRED and ALFRED-vintage adapter tests."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

import pytest

from src.adapters import (
    FREDAdapter,
    FREDProviderRequestError,
    ProviderUnavailableError,
)
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


@pytest.mark.parametrize(
    ("research_as_of", "expected"),
    (
        (datetime(2026, 9, 14, 20, tzinfo=UTC), date(2026, 9, 14)),
        (datetime(2026, 9, 15, 3, 56, tzinfo=UTC), date(2026, 9, 14)),
        (datetime(2026, 9, 15, 6, tzinfo=UTC), date(2026, 9, 15)),
        (datetime(2026, 1, 15, 5, 30, tzinfo=UTC), date(2026, 1, 14)),
    ),
)
def test_fred_projects_global_instant_to_provider_calendar(
    research_as_of: datetime,
    expected: date,
) -> None:
    """America/Chicago projection must handle UTC boundaries and DST."""

    assert FREDAdapter.provider_realtime_cutoff(research_as_of) == expected


def test_fred_rejects_naive_runtime_cutoff() -> None:
    """An ambiguous runtime timestamp must fail closed."""

    with pytest.raises(ValueError, match="timezone-aware"):
        FREDAdapter.provider_realtime_cutoff(datetime(2026, 9, 15, 3, 56))


class _EchoVintageTransport:
    def __init__(self) -> None:
        self.requests: list[Request] = []

    def send(self, request: Request, timeout: float) -> ProviderHTTPResponse:
        assert timeout == 7.0
        self.requests.append(request)
        parsed = urlparse(request.full_url)
        if parsed.path.endswith("/series"):
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
            query = parse_qs(parsed.query)
            cutoff = query["realtime_start"][0]
            body = {
                "observations": [
                    {
                        "realtime_start": cutoff,
                        "realtime_end": cutoff,
                        "date": "2026-08-01",
                        "value": "4.33",
                    }
                ]
            }
        return ProviderHTTPResponse(200, {}, json.dumps(body).encode())


def test_fred_exact_failed_instant_uses_previous_chicago_date() -> None:
    """Replay the 2026-09-15 03:56Z preflight without a future vintage."""

    transport = _EchoVintageTransport()
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
            date(2025, 8, 11),
            date(2026, 9, 15),
            datetime(2026, 9, 15, 3, 56, tzinfo=UTC),
        )
    )

    query = parse_qs(urlparse(transport.requests[1].full_url).query)
    assert query["observation_end"] == ["2026-09-15"]
    assert query["realtime_start"] == ["2026-09-14"]
    assert query["realtime_end"] == ["2026-09-14"]
    assert records[0]["realtime_start"] == "2026-09-14"
    source_locator = records[0]["source_locator"]
    assert isinstance(source_locator, str)
    assert source_locator.endswith("vintage:2026-09-14")


class _FREDErrorTransport:
    def __init__(self, body: str) -> None:
        self.body = body

    def send(self, request: Request, timeout: float) -> ProviderHTTPResponse:
        del timeout
        if urlparse(request.full_url).path.endswith("/series"):
            return ProviderHTTPResponse(
                200,
                {},
                json.dumps(
                    {
                        "seriess": [
                            {
                                "id": "FEDFUNDS",
                                "title": "Federal Funds Rate",
                                "units": "Percent",
                                "frequency": "Monthly",
                            }
                        ]
                    }
                ).encode(),
            )
        return ProviderHTTPResponse(400, {}, self.body.encode())


@pytest.mark.parametrize(
    "body",
    (
        json.dumps(
            {
                "error_code": 400,
                "error_message": (
                    "Bad Request. Variable realtime_start can not be after "
                    "today's date. api_key=fixture-key"
                ),
            }
        ),
        '<error code="400" message="Bad Request. Future realtime_start."/>',
    ),
)
def test_fred_http_error_preserves_safe_provider_diagnostics(body: str) -> None:
    """JSON/XML FRED errors retain useful fields but never credential values."""

    adapter = FREDAdapter(
        api_key="fixture-key",
        request_timeout=7.0,
        http_transport=_FREDErrorTransport(body),
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )

    with pytest.raises(FREDProviderRequestError) as raised:
        list(
            adapter.fetch_macro_series(
                ["FEDFUNDS"],
                date(2025, 8, 11),
                date(2026, 9, 15),
                datetime(2026, 9, 15, 3, 56, tzinfo=UTC),
            )
        )

    error = raised.value
    assert error.provider == "fred"
    assert error.status_code == 400
    assert str(error.fred_error_code) == "400"
    assert "Bad Request" in error.fred_error_message_safe
    assert "fixture-key" not in str(error)
    assert "api_key" in error.request_parameter_names
    assert error.realtime_start == "2026-09-14"
    assert error.realtime_end == "2026-09-14"


def test_fred_rejects_response_vintage_after_provider_cutoff() -> None:
    """A provider response cannot override the requested PIT vintage."""

    adapter = FREDAdapter(
        api_key="fixture-key",
        request_timeout=7.0,
        http_transport=_Transport(),
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )

    with pytest.raises(
        ProviderUnavailableError,
        match="vintage metadata does not match",
    ):
        list(
            adapter.fetch_macro_series(
                ["FEDFUNDS"],
                date(2026, 1, 1),
                date(2026, 8, 1),
                date(2026, 8, 9),
            )
        )
