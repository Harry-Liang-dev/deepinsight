"""Offline acceptance tests for Alpaca News UTC window semantics."""

from __future__ import annotations

import json
from datetime import date
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

import pytest

from src.adapters import AlpacaAdapter, ProviderUnavailableError
from src.adapters.http import ProviderHTTPResponse
from src.models.types import JsonObject


class _PagesTransport:
    def __init__(self, pages: list[JsonObject]) -> None:
        self._pages = pages
        self.requests: list[Request] = []

    def send(self, request: Request, timeout: float) -> ProviderHTTPResponse:
        del timeout
        self.requests.append(request)
        body = self._pages[len(self.requests) - 1]
        return ProviderHTTPResponse(200, {}, json.dumps(body).encode())


def _item(
    news_id: int,
    *,
    created_at: str,
    updated_at: str | None = None,
) -> JsonObject:
    return {
        "id": news_id,
        "headline": f"Headline {news_id}",
        "summary": "Attributed summary",
        "author": "Reporter",
        "created_at": created_at,
        "updated_at": created_at if updated_at is None else updated_at,
        "url": f"https://publisher.test/{news_id}",
        "source": "Benzinga",
        "symbols": ["AAPL"],
    }


def _adapter(transport: _PagesTransport) -> AlpacaAdapter:
    return AlpacaAdapter(
        api_key_id="fixture-id",
        api_secret_key="fixture-secret",
        api_base_url="https://alpaca.test",
        http_transport=transport,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )


def test_inclusive_utc_boundaries_and_explicit_query_timestamps() -> None:
    transport = _PagesTransport(
        [
            {
                "news": [
                    _item(1, created_at="2026-08-02T00:00:00Z"),
                    _item(2, created_at="2026-08-03T12:00:00Z"),
                    _item(3, created_at="2026-08-03T23:59:59.999999Z"),
                ],
                "next_page_token": None,
            }
        ]
    )
    adapter = _adapter(transport)

    records = list(
        adapter.fetch_documents(["US:AAPL"], date(2026, 8, 2), date(2026, 8, 3))
    )

    assert [record["news_id"] for record in records] == ["1", "2", "3"]
    query = parse_qs(urlparse(transport.requests[0].full_url).query)
    assert query["start"] == ["2026-08-02T00:00:00Z"]
    assert query["end"] == ["2026-08-03T23:59:59.999999Z"]
    assert adapter.news_fetch_diagnostics() == {
        "window_semantics": "alpaca_news_created_at_utc_closed_day_v1",
        "status": "ok",
        "request_start": "2026-08-02T00:00:00+00:00",
        "request_end": "2026-08-03T23:59:59.999999+00:00",
        "research_as_of": "2026-08-03T23:59:59.999999+00:00",
        "provider_returned_count": 3,
        "accepted_count": 3,
        "filtered_count": 0,
        "rejected_count": 0,
        "filter_reasons": {},
        "page_count": 1,
    }


def test_timezone_is_normalized_before_inclusive_boundary_check() -> None:
    transport = _PagesTransport(
        [
            {
                "news": [
                    _item(
                        1,
                        created_at="2026-08-02T20:00:00-04:00",
                        updated_at="2026-08-02T20:00:00-04:00",
                    )
                ],
                "next_page_token": None,
            }
        ]
    )

    records = list(
        _adapter(transport).fetch_documents(
            ["US:AAPL"], date(2026, 8, 3), date(2026, 8, 3)
        )
    )

    assert records[0]["created_at"] == "2026-08-03T00:00:00+00:00"


def test_real_failure_before_start_overfetch_is_filtered() -> None:
    transport = _PagesTransport(
        [
            {
                "news": [
                    _item(
                        61_485_240,
                        created_at="2026-08-28T03:32:06Z",
                        updated_at="2026-08-31T03:05:27Z",
                    ),
                    _item(2, created_at="2026-09-01T12:00:00Z"),
                ],
                "next_page_token": None,
            }
        ]
    )
    adapter = _adapter(transport)

    records = list(
        adapter.fetch_documents(["US:AAPL"], date(2026, 8, 31), date(2026, 9, 14))
    )

    assert [record["news_id"] for record in records] == ["2"]
    diagnostics = adapter.news_fetch_diagnostics()
    assert diagnostics["provider_returned_count"] == 2
    assert diagnostics["accepted_count"] == 1
    assert diagnostics["filtered_count"] == 1
    assert diagnostics["filter_reasons"] == {"before_start": 1}


@pytest.mark.parametrize(
    ("created_at", "updated_at"),
    (
        ("2026-08-04T00:00:00Z", "2026-08-04T00:00:00Z"),
        ("2026-08-03T12:00:00Z", "2026-08-04T00:00:00Z"),
    ),
)
def test_creation_or_revision_after_research_cutoff_is_rejected(
    created_at: str,
    updated_at: str,
) -> None:
    transport = _PagesTransport(
        [
            {
                "news": [
                    _item(1, created_at=created_at, updated_at=updated_at),
                ],
                "next_page_token": None,
            }
        ]
    )
    adapter = _adapter(transport)

    with pytest.raises(
        ProviderUnavailableError,
        match="exceeds the research cutoff",
    ):
        list(adapter.fetch_documents(["US:AAPL"], date(2026, 8, 2), date(2026, 8, 3)))

    diagnostics = adapter.news_fetch_diagnostics()
    assert diagnostics["status"] == "provider_error"
    assert diagnostics["rejected_count"] == 1
    assert diagnostics["filter_reasons"] == {"after_research_as_of": 1}


def test_ambiguous_timestamp_fails_closed() -> None:
    transport = _PagesTransport(
        [
            {
                "news": [
                    _item(1, created_at="2026-08-03T12:00:00"),
                ],
                "next_page_token": None,
            }
        ]
    )

    with pytest.raises(ProviderUnavailableError, match="include a timezone"):
        list(
            _adapter(transport).fetch_documents(
                ["US:AAPL"], date(2026, 8, 3), date(2026, 8, 3)
            )
        )


def test_pagination_duplicate_and_before_start_overfetch_are_counted() -> None:
    duplicate = _item(1, created_at="2026-08-03T12:00:00Z")
    transport = _PagesTransport(
        [
            {
                "news": [
                    _item(
                        9,
                        created_at="2026-08-01T12:00:00Z",
                        updated_at="2026-08-03T01:00:00Z",
                    ),
                    duplicate,
                ],
                "next_page_token": "page-2",
            },
            {
                "news": [duplicate, _item(2, created_at="2026-08-03T13:00:00Z")],
                "next_page_token": None,
            },
        ]
    )
    adapter = _adapter(transport)

    records = list(
        adapter.fetch_documents(["US:AAPL"], date(2026, 8, 2), date(2026, 8, 3))
    )

    assert [record["news_id"] for record in records] == ["1", "2"]
    diagnostics = adapter.news_fetch_diagnostics()
    assert diagnostics["provider_returned_count"] == 4
    assert diagnostics["accepted_count"] == 2
    assert diagnostics["filtered_count"] == 2
    assert diagnostics["filter_reasons"] == {
        "before_start": 1,
        "duplicate_news_id": 1,
    }
    assert diagnostics["page_count"] == 2


def test_empty_after_filter_is_a_valid_success() -> None:
    transport = _PagesTransport(
        [
            {
                "news": [
                    _item(
                        61_485_240,
                        created_at="2026-08-28T03:32:06Z",
                        updated_at="2026-08-31T03:05:27Z",
                    )
                ],
                "next_page_token": None,
            }
        ]
    )
    adapter = _adapter(transport)

    records = list(
        adapter.fetch_documents(["US:AAPL"], date(2026, 8, 31), date(2026, 9, 14))
    )

    assert records == []
    assert adapter.news_fetch_diagnostics()["status"] == "ok"
    assert adapter.news_fetch_diagnostics()["accepted_count"] == 0
    assert adapter.news_fetch_diagnostics()["filtered_count"] == 1
