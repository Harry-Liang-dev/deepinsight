"""Offline contract tests for data provider adapters."""

from __future__ import annotations

import gzip
import json
from datetime import date
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

import pytest

from src.adapters import (
    AlpacaAdapter,
    BloombergLicensedAdapter,
    CNINFOAdapter,
    FakeProviderAdapter,
    HKEXNewsAdapter,
    LSEGLicensedAdapter,
    ProviderUnavailableError,
    SECEDGARAdapter,
    WindAdapter,
    XSearchAdapter,
)
from src.adapters.http import ProviderHTTPClient, ProviderHTTPResponse
from src.adapters.providers import _decode_http_payload


class _MockHTTPTransport:
    """Return queued or URL-mapped responses without network access."""

    def __init__(
        self,
        responses: (
            dict[str, ProviderHTTPResponse] | list[ProviderHTTPResponse | Exception]
        ),
    ) -> None:
        self.responses = responses
        self.requests: list[Request] = []
        self.timeouts: list[float] = []

    def send(
        self,
        request: Request,
        timeout: float,
    ) -> ProviderHTTPResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        if isinstance(self.responses, dict):
            return self.responses[request.full_url]
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _response(
    body: str,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> ProviderHTTPResponse:
    return ProviderHTTPResponse(
        status_code=status,
        headers=headers or {},
        body=body.encode(),
    )


def _mock_http_client(
    transport: _MockHTTPTransport,
) -> ProviderHTTPClient:
    return ProviderHTTPClient(
        user_agent="DeepInsight test@example.com",
        request_timeout=3.0,
        max_retries=2,
        requests_per_second=5.0,
        transport=transport,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )


@pytest.mark.parametrize(
    "adapter_type",
    [
        WindAdapter,
        CNINFOAdapter,
        HKEXNewsAdapter,
        XSearchAdapter,
        LSEGLicensedAdapter,
        BloombergLicensedAdapter,
    ],
)
def test_real_provider_boundaries_never_attempt_network(adapter_type: type) -> None:
    """Unconfigured provider boundaries fail explicitly and offline."""

    adapter = adapter_type()
    health = adapter.healthcheck()

    assert health["status"] == "unavailable"
    assert health["network_attempted"] is False
    with pytest.raises(ProviderUnavailableError, match="not configured"):
        list(adapter.fetch_instruments())


def test_fake_provider_filters_fixed_records() -> None:
    """The fake provider supplies deterministic requested records."""

    adapter = FakeProviderAdapter(
        eod_bars=[
            {
                "asset_id": "US:AAPL",
                "market": "US",
                "trade_date": "2026-07-30",
                "close": 210.0,
            },
            {
                "asset_id": "US:MSFT",
                "market": "US",
                "trade_date": "2026-07-30",
                "close": 500.0,
            },
        ]
    )

    result = list(adapter.fetch_eod_bars(["US:AAPL"], date(2026, 7, 30)))

    assert adapter.healthcheck()["mode"] == "offline"
    assert [item["asset_id"] for item in result] == ["US:AAPL"]


def test_alpaca_adapter_maps_and_paginates_official_daily_bars() -> None:
    """Alpaca pages should become canonical records without leaking its keys."""

    transport = _MockHTTPTransport(
        [
            _response("""
                {
                  "bars": {
                    "AAPL": [{
                      "t": "2026-08-03T04:00:00Z",
                      "o": 208.1,
                      "h": 211.2,
                      "l": 207.5,
                      "c": 210.4,
                      "v": 123456,
                      "vw": 209.9,
                      "n": 4200
                    }]
                  },
                  "next_page_token": "opaque+/token="
                }
                """),
            _response("""
                {
                  "bars": {
                    "AAPL": [{
                      "t": "2026-08-04T04:00:00Z",
                      "o": 210.5,
                      "h": 213.0,
                      "l": 209.8,
                      "c": 212.2,
                      "v": 234567,
                      "vw": 211.7
                    }]
                  },
                  "next_page_token": null
                }
                """),
        ]
    )
    adapter = AlpacaAdapter(
        api_key_id="fixture-key-id",
        api_secret_key="fixture-secret",
        api_base_url="https://alpaca.test",
        page_limit=1,
        http_transport=transport,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )

    records = list(
        adapter.fetch_eod_bars_range(
            ["US:AAPL"],
            date(2026, 8, 3),
            date(2026, 8, 4),
        )
    )

    assert records == [
        {
            "asset_id": "US:AAPL",
            "market": "US",
            "trade_date": "2026-08-03",
            "open": 208.1,
            "high": 211.2,
            "low": 207.5,
            "close": 210.4,
            "adj_close": None,
            "volume": 123456,
            "turnover": None,
            "vwap": 209.9,
            "feed_identity": "iex",
            "coverage_scope": (
                "IEX single-exchange US equity feed; not consolidated SIP; "
                "adjustment=raw"
            ),
        },
        {
            "asset_id": "US:AAPL",
            "market": "US",
            "trade_date": "2026-08-04",
            "open": 210.5,
            "high": 213.0,
            "low": 209.8,
            "close": 212.2,
            "adj_close": None,
            "volume": 234567,
            "turnover": None,
            "vwap": 211.7,
            "feed_identity": "iex",
            "coverage_scope": (
                "IEX single-exchange US equity feed; not consolidated SIP; "
                "adjustment=raw"
            ),
        },
    ]
    assert list(adapter.fetch_instruments()) == []
    assert adapter.healthcheck() == {
        "provider": "alpaca_market_data",
        "market_scope": "US",
        "status": "configured",
        "access_mode": "official",
        "network_attempted": False,
        "feed": "iex",
        "adjustment": "raw",
        "max_retries": 2,
        "requests_per_minute": 180.0,
        "capabilities": ["eod_bars", "news"],
        "coverage_scope": ("IEX single-exchange US equity feed; not consolidated SIP"),
    }

    first_request = transport.requests[0]
    assert first_request.full_url.startswith("https://alpaca.test/v2/stocks/bars?")
    first_query = parse_qs(urlparse(first_request.full_url).query)
    second_query = parse_qs(urlparse(transport.requests[1].full_url).query)
    assert first_query == {
        "symbols": ["AAPL"],
        "timeframe": ["1Day"],
        "start": ["2026-08-03"],
        "end": ["2026-08-04"],
        "limit": ["1"],
        "adjustment": ["raw"],
        "feed": ["iex"],
        "sort": ["asc"],
    }
    assert second_query["page_token"] == ["opaque+/token="]
    assert first_request.get_header("Apca-api-key-id") == "fixture-key-id"
    assert first_request.get_header("Apca-api-secret-key") == "fixture-secret"


def test_alpaca_adjusted_research_series_is_explicit_in_request_and_metadata() -> None:
    """Adjusted and raw OHLC series must remain semantically distinguishable."""

    transport = _MockHTTPTransport(
        [_response('{"bars":{"AAPL":[{"t":"2026-08-03T04:00:00Z","c":10}]}}')]
    )
    adapter = AlpacaAdapter(
        api_key_id="fixture-key-id",
        api_secret_key="fixture-secret",
        adjustment="all",
        http_transport=transport,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )

    records = list(
        adapter.fetch_eod_bars_range(["US:AAPL"], date(2026, 8, 3), date(2026, 8, 3))
    )

    query = parse_qs(urlparse(transport.requests[0].full_url).query)
    assert query["adjustment"] == ["all"]
    assert str(records[0]["coverage_scope"]).endswith("adjustment=all")


def test_alpaca_single_date_contract_and_missing_data_are_explicit() -> None:
    """A no-trading-day response stays empty and creates no synthetic bar."""

    transport = _MockHTTPTransport([_response('{"bars": {}, "next_page_token": null}')])
    adapter = AlpacaAdapter(
        api_key_id="fixture-key-id",
        api_secret_key="fixture-secret",
        http_transport=transport,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )

    records = list(
        adapter.fetch_eod_bars(
            ["US:AAPL"],
            date(2026, 8, 2),
        )
    )

    assert records == []
    query = parse_qs(urlparse(transport.requests[0].full_url).query)
    assert query["start"] == ["2026-08-02"]
    assert query["end"] == ["2026-08-02"]


def test_alpaca_rejects_unrequested_symbols_and_auth_failures() -> None:
    """Malformed provenance and permanent authentication errors are surfaced."""

    unexpected = AlpacaAdapter(
        api_key_id="fixture-key-id",
        api_secret_key="fixture-secret",
        http_transport=_MockHTTPTransport([_response("""
                    {
                      "bars": {
                        "MSFT": [{
                          "t": "2026-08-03T04:00:00Z",
                          "o": 1,
                          "h": 1,
                          "l": 1,
                          "c": 1
                        }]
                      },
                      "next_page_token": null
                    }
                    """)]),
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )
    with pytest.raises(ProviderUnavailableError, match="unrequested"):
        list(
            unexpected.fetch_eod_bars(
                ["US:AAPL"],
                date(2026, 8, 3),
            )
        )

    auth_transport = _MockHTTPTransport([_response("", status=401)])
    unauthorized = AlpacaAdapter(
        api_key_id="fixture-key-id",
        api_secret_key="fixture-secret",
        http_transport=auth_transport,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )
    with pytest.raises(ProviderUnavailableError, match="status 401"):
        list(
            unauthorized.fetch_eod_bars(
                ["US:AAPL"],
                date(2026, 8, 3),
            )
        )
    assert len(auth_transport.requests) == 1


def test_alpaca_rejects_duplicate_daily_bars_in_one_sync() -> None:
    """Provider duplicates are surfaced instead of silently overwriting a bar."""

    duplicate_bar = {
        "t": "2026-08-03T04:00:00Z",
        "o": 208.1,
        "h": 211.2,
        "l": 207.5,
        "c": 210.4,
        "v": 123456,
    }
    transport = _MockHTTPTransport(
        [
            _response(
                json.dumps(
                    {
                        "bars": {"AAPL": [duplicate_bar, duplicate_bar]},
                        "next_page_token": None,
                    }
                )
            )
        ]
    )
    adapter = AlpacaAdapter(
        api_key_id="fixture-key-id",
        api_secret_key="fixture-secret",
        http_transport=transport,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )

    with pytest.raises(ProviderUnavailableError, match="duplicate daily bar"):
        list(
            adapter.fetch_eod_bars_range(
                ["US:AAPL"],
                date(2026, 8, 3),
                date(2026, 8, 3),
            )
        )


def test_sec_adapter_maps_official_submission_and_filing() -> None:
    """SEC metadata and filing HTML should become stable provider records."""

    responses = {
        "https://data.sec.gov/submissions/CIK0000320193.json": """
        {
          "name": "Apple Inc.",
          "tickers": ["AAPL"],
          "exchanges": ["Nasdaq"],
          "filings": {"recent": {
            "accessionNumber": ["0000320193-26-000001"],
            "filingDate": ["2026-08-01"],
            "acceptanceDateTime": ["20260801123000"],
            "form": ["10-Q"],
            "primaryDocument": ["aapl-20260627.htm"]
          }}
        }
        """,
        (
            "https://www.sec.gov/Archives/edgar/data/320193/"
            "000032019326000001/aapl-20260627.htm"
        ): "<html><body><h1>Apple 10-Q</h1><p>Revenue disclosed.</p></body></html>",
    }
    transport = _MockHTTPTransport(
        {url: _response(body) for url, body in responses.items()}
    )

    adapter = SECEDGARAdapter(
        user_agent="DeepInsight test@example.com",
        cik_by_asset={"US:AAPL": "320193"},
        http_transport=transport,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )

    instruments = list(adapter.fetch_instruments())
    documents = list(
        adapter.fetch_documents(
            ["US:AAPL"],
            date(2026, 7, 1),
            date(2026, 8, 2),
        )
    )

    assert instruments == [
        {
            "asset_id": "US:AAPL",
            "market": "US",
            "exchange_code": "NASDAQ",
            "company_name": "Apple Inc.",
            "currency": "USD",
            "metadata": {"cik": "0000320193"},
        }
    ]
    assert len(documents) == 1
    assert documents[0]["document_id"] == ("sec-0000320193-000032019326000001")
    assert documents[0]["raw_text"] == "Apple 10-Q Revenue disclosed."
    assert documents[0]["metadata"] == {
        "cik": "0000320193",
        "accession_number": "0000320193-26-000001",
        "provider_locator": ("sec:accession:0000320193-26-000001"),
        "primary_document": "aapl-20260627.htm",
        "form": "10-Q",
        "filing_date": "2026-08-01",
    }
    assert len(transport.requests) == 2


def test_sec_adapter_reads_overlapping_historical_submission_page() -> None:
    """A date window may continue through SEC's official filing pages."""

    submissions_url = "https://data.sec.gov/submissions/CIK0000320193.json"
    page_url = "https://data.sec.gov/submissions/" "CIK0000320193-submissions-001.json"
    filing_url = (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000032019320000001/aapl-20191228.htm"
    )
    transport = _MockHTTPTransport(
        {
            submissions_url: _response("""
                {
                  "name": "Apple Inc.",
                  "tickers": ["AAPL"],
                  "exchanges": ["Nasdaq"],
                  "filings": {
                    "recent": {},
                    "files": [{
                      "name": "CIK0000320193-submissions-001.json",
                      "filingFrom": "2019-01-01",
                      "filingTo": "2020-12-31"
                    }]
                  }
                }
                """),
            page_url: _response("""
                {
                  "accessionNumber": ["0000320193-20-000001"],
                  "filingDate": ["2020-01-29"],
                  "acceptanceDateTime": ["20200129120000"],
                  "form": ["10-Q"],
                  "primaryDocument": ["aapl-20191228.htm"]
                }
                """),
            filing_url: _response(
                "<html><body>Historical filing evidence.</body></html>"
            ),
        }
    )
    adapter = SECEDGARAdapter(
        user_agent="DeepInsight test@example.com",
        cik_by_asset={"US:AAPL": "320193"},
        http_transport=transport,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )

    documents = list(
        adapter.fetch_documents(
            ["US:AAPL"],
            date(2020, 1, 1),
            date(2020, 2, 1),
        )
    )

    assert len(documents) == 1
    assert documents[0]["source_url"] == filing_url
    metadata = documents[0]["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["provider_locator"] == ("sec:accession:0000320193-20-000001")
    assert [request.full_url for request in transport.requests] == [
        submissions_url,
        page_url,
        filing_url,
    ]


def test_provider_http_client_sends_identity_timeout_and_rate_limits() -> None:
    """Governed requests carry headers and respect the configured cadence."""

    transport = _MockHTTPTransport([_response("one"), _response("two")])
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    client = ProviderHTTPClient(
        user_agent="DeepInsight test@example.com",
        request_timeout=7.0,
        max_retries=0,
        requests_per_second=2.0,
        transport=transport,
        clock=lambda: now[0],
        sleeper=sleep,
    )

    assert (
        client.get_text(
            "https://data.sec.gov/one",
            accept="application/json",
        )
        == "one"
    )
    assert (
        client.get_text(
            "https://data.sec.gov/two",
            accept="application/json",
        )
        == "two"
    )

    assert sleeps == [0.5]
    assert transport.timeouts == [7.0, 7.0]
    request = transport.requests[0]
    assert request.get_header("User-agent") == ("DeepInsight test@example.com")
    assert request.get_header("Accept") == "application/json"
    assert request.get_header("Accept-encoding") == "gzip, deflate"


def test_provider_http_client_retries_transient_statuses_with_bounds() -> None:
    """Retry-After and bounded exponential backoff govern transient errors."""

    transport = _MockHTTPTransport(
        [
            _response("", status=429, headers={"Retry-After": "2"}),
            _response("", status=503),
            _response("ok"),
        ]
    )
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    client = ProviderHTTPClient(
        user_agent="DeepInsight test@example.com",
        request_timeout=3.0,
        max_retries=2,
        requests_per_second=5.0,
        backoff_base_seconds=0.5,
        transport=transport,
        clock=lambda: now[0],
        sleeper=sleep,
    )

    result = client.get_text(
        "https://data.sec.gov/retry",
        accept="application/json",
    )

    assert result == "ok"
    assert sleeps == [2.0, 1.0]
    assert len(transport.requests) == 3


def test_provider_http_client_honors_rate_limit_reset_header() -> None:
    """A 429 should not retry before the provider's Unix reset time."""

    transport = _MockHTTPTransport(
        [
            _response(
                "",
                status=429,
                headers={"X-RateLimit-Reset": "1012"},
            ),
            _response("ok"),
        ]
    )
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    client = ProviderHTTPClient(
        user_agent="DeepInsight test@example.com",
        request_timeout=3.0,
        max_retries=1,
        requests_per_second=5.0,
        max_backoff_seconds=60.0,
        transport=transport,
        clock=lambda: now[0],
        wall_clock=lambda: 1000.0 + now[0],
        sleeper=sleep,
    )

    assert (
        client.get_text(
            "https://data.alpaca.markets/v2/stocks/bars",
            accept="application/json",
        )
        == "ok"
    )
    assert sleeps == [12.0]


def test_provider_http_client_does_not_retry_permanent_http_error() -> None:
    """A permanent 4xx response is surfaced immediately."""

    transport = _MockHTTPTransport([_response("", status=404)])
    client = _mock_http_client(transport)

    with pytest.raises(ProviderUnavailableError, match="status 404"):
        client.get_text(
            "https://data.sec.gov/missing",
            accept="application/json",
        )

    assert len(transport.requests) == 1


def test_provider_http_client_surfaces_exhausted_network_error() -> None:
    """Network failures are retried finitely and never swallowed."""

    transport = _MockHTTPTransport([URLError("offline"), TimeoutError(), OSError()])
    client = _mock_http_client(transport)

    with pytest.raises(ProviderUnavailableError, match="after 3 attempts"):
        client.get_text(
            "https://data.sec.gov/unavailable",
            accept="application/json",
        )

    assert len(transport.requests) == 3


def test_provider_http_client_surfaces_invalid_compression() -> None:
    """A corrupt encoded response becomes a stable Provider error."""

    transport = _MockHTTPTransport(
        [
            ProviderHTTPResponse(
                status_code=200,
                headers={"Content-Encoding": "gzip"},
                body=b"not-gzip",
            )
        ]
    )
    client = _mock_http_client(transport)

    with pytest.raises(ProviderUnavailableError, match="decoding failed"):
        client.get_text(
            "https://data.sec.gov/corrupt",
            accept="application/json",
        )


def test_sec_adapter_requires_identified_user_agent() -> None:
    """SEC access must not run as an undeclared automated tool."""

    with pytest.raises(ValueError, match="contact email"):
        SECEDGARAdapter(
            user_agent="DeepInsight",
            cik_by_asset={"US:AAPL": "320193"},
        )


def test_sec_adapter_decodes_gzip_json_payload() -> None:
    """SEC's recommended gzip response must be decoded before JSON parsing."""

    expected = '{"name":"Apple Inc."}'

    decoded = _decode_http_payload(
        gzip.compress(expected.encode()),
        "gzip",
    )

    assert decoded == expected


def test_fake_provider_can_fail_after_partial_yield() -> None:
    """A configured failure can model a provider stream interruption."""

    adapter = FakeProviderAdapter(
        instruments=[
            {"asset_id": "US:AAPL"},
            {"asset_id": "US:MSFT"},
        ],
        fail_stream="instruments",
        fail_after=1,
    )
    stream = iter(adapter.fetch_instruments())

    assert next(stream)["asset_id"] == "US:AAPL"
    with pytest.raises(ProviderUnavailableError, match="configured failure"):
        next(stream)
