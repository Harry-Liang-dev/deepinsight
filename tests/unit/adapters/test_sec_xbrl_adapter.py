"""Offline mock-HTTP tests for SEC Company Facts normalization."""

from __future__ import annotations

import json
from datetime import date
from urllib.request import Request

import pytest

from src.adapters import ProviderUnavailableError, SECEDGARAdapter
from src.adapters.http import ProviderHTTPResponse

COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK0000320193.json"


class _CompanyFactsTransport:
    """Return one fixed Company Facts response without network access."""

    def __init__(self, payload: object, *, status_code: int = 200) -> None:
        self._payload = payload
        self._status_code = status_code
        self.requests: list[Request] = []
        self.timeouts: list[float] = []

    def send(self, request: Request, timeout: float) -> ProviderHTTPResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        payload = (
            {
                "filings": {
                    "recent": {
                        "accessionNumber": ["0000320193-26-000001"],
                        "acceptanceDateTime": ["20260801120000"],
                        "filingDate": ["2026-08-01"],
                    }
                }
            }
            if request.full_url == SUBMISSIONS_URL
            else self._payload
        )
        return ProviderHTTPResponse(
            status_code=self._status_code,
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload).encode(),
        )


def _fact(
    value: float,
    *,
    start: str | None = "2026-03-29",
    end: str = "2026-06-27",
    filed: str = "2026-08-01",
    form: str = "10-Q",
    accession: str = "0000320193-26-000001",
) -> dict[str, object]:
    result: dict[str, object] = {
        "end": end,
        "val": value,
        "accn": accession,
        "fy": 2026,
        "fp": "Q3",
        "form": form,
        "filed": filed,
    }
    if start is not None:
        result["start"] = start
    return result


def _payload() -> dict[str, object]:
    return {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {"shares": [_fact(15.2, start=None)]}
                }
            },
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            _fact(150.0, start="2025-09-28"),
                            _fact(60.0),
                            _fact(50.0, filed="2026-06-01"),
                        ]
                    }
                },
                "GrossProfit": {"units": {"USD": [_fact(30.0)]}},
                "NetIncomeLoss": {"units": {"USD": [_fact(20.0)]}},
                "EarningsPerShareBasic": {"units": {"USD/shares": [_fact(1.25)]}},
                "Assets": {"units": {"USD": [_fact(400.0, start=None)]}},
            },
        },
    }


def test_sec_company_facts_maps_only_requested_filing_window() -> None:
    """Adapter hides XBRL tags and selects the discrete quarterly duration."""

    transport = _CompanyFactsTransport(_payload())
    adapter = SECEDGARAdapter(
        user_agent="DeepInsight test@example.com",
        cik_by_asset={"US:AAPL": "320193"},
        request_timeout=7.0,
        http_transport=transport,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )

    records = list(
        adapter.fetch_fundamentals_range(
            ["US:AAPL"],
            date(2026, 7, 1),
            date(2026, 8, 2),
        )
    )

    assert records == [
        {
            "asset_id": "US:AAPL",
            "market": "US",
            "fiscal_period_end": "2026-06-27",
            "report_type": "10-Q",
            "filing_url": (
                "https://www.sec.gov/Archives/edgar/data/320193/" "000032019326000001/"
            ),
            "filing_date": "2026-08-01",
            "accepted_at": "2026-08-01T12:00:00+00:00",
            "source_record_id": "sec:accession:0000320193-26-000001",
            "revenue": 60.0,
            "gross_profit": 30.0,
            "net_income": 20.0,
            "eps_basic": 1.25,
            "total_assets": 400.0,
            "shares_outstanding": 15.2,
        }
    ]
    assert [request.full_url for request in transport.requests] == [
        COMPANY_FACTS_URL,
        SUBMISSIONS_URL,
    ]
    assert transport.requests[0].get_header("User-agent") == (
        "DeepInsight test@example.com"
    )
    assert transport.timeouts == [7.0, 7.0]
    assert "RevenueFromContractWithCustomerExcludingAssessedTax" not in records[0]


def test_sec_company_facts_rejects_wrong_market_and_http_failure() -> None:
    """Canonical-market validation and HTTP failures remain explicit."""

    adapter = SECEDGARAdapter(
        user_agent="DeepInsight test@example.com",
        cik_by_asset={"US:AAPL": "320193"},
        http_transport=_CompanyFactsTransport(_payload()),
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )
    with pytest.raises(ValueError, match="canonical US"):
        list(
            adapter.fetch_fundamentals_range(
                ["HK:0700.HK"],
                date(2026, 7, 1),
                date(2026, 8, 2),
            )
        )

    failed = SECEDGARAdapter(
        user_agent="DeepInsight test@example.com",
        cik_by_asset={"US:AAPL": "320193"},
        max_retries=0,
        http_transport=_CompanyFactsTransport({}, status_code=429),
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )
    with pytest.raises(ProviderUnavailableError, match="status 429"):
        list(
            failed.fetch_fundamentals_range(
                ["US:AAPL"],
                date(2026, 7, 1),
                date(2026, 8, 2),
            )
        )


def test_sec_company_facts_rejects_malformed_target_fact() -> None:
    """Malformed in-window financial values cannot be silently discarded."""

    payload = _payload()
    facts = payload["facts"]
    assert isinstance(facts, dict)
    us_gaap = facts["us-gaap"]
    assert isinstance(us_gaap, dict)
    us_gaap["GrossProfit"] = {"units": {"USD": [_fact(float("nan"))]}}
    adapter = SECEDGARAdapter(
        user_agent="DeepInsight test@example.com",
        cik_by_asset={"US:AAPL": "320193"},
        http_transport=_CompanyFactsTransport(payload),
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )

    with pytest.raises(ProviderUnavailableError, match="finite"):
        list(
            adapter.fetch_fundamentals_range(
                ["US:AAPL"],
                date(2026, 7, 1),
                date(2026, 8, 2),
            )
        )
