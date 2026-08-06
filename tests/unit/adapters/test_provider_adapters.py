"""Offline contract tests for data provider adapters."""

from __future__ import annotations

import gzip
from datetime import date

import pytest

from src.adapters import (
    AlpacaAdapter,
    BloombergLicensedAdapter,
    CNINFOAdapter,
    FakeProviderAdapter,
    FREDAdapter,
    HKEXNewsAdapter,
    LSEGLicensedAdapter,
    ProviderUnavailableError,
    SECEDGARAdapter,
    WindAdapter,
    XSearchAdapter,
)
from src.adapters.providers import _decode_http_payload


@pytest.mark.parametrize(
    "adapter_type",
    [
        WindAdapter,
        CNINFOAdapter,
        HKEXNewsAdapter,
        FREDAdapter,
        AlpacaAdapter,
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
    requested: list[str] = []

    def fetch(url: str) -> str:
        requested.append(url)
        return responses[url]

    adapter = SECEDGARAdapter(
        user_agent="DeepInsight test@example.com",
        cik_by_asset={"US:AAPL": "320193"},
        fetch_text=fetch,
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
        "primary_document": "aapl-20260627.htm",
        "form": "10-Q",
        "filing_date": "2026-08-01",
    }
    assert len(requested) == 2


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
