"""Offline pagination and attribution tests for Alpaca News."""

from __future__ import annotations

import json
from datetime import date
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

from src.adapters import AlpacaAdapter
from src.adapters.http import ProviderHTTPResponse


class _Transport:
    def __init__(self) -> None:
        self.requests: list[Request] = []

    def send(self, request: Request, timeout: float) -> ProviderHTTPResponse:
        del timeout
        self.requests.append(request)
        page = len(self.requests)
        item = {
            "id": page,
            "headline": f"Headline {page}",
            "summary": "Attributed summary",
            "content": "Not retained by default",
            "author": "Reporter",
            "created_at": f"2026-08-0{page + 1}T12:00:00Z",
            "updated_at": f"2026-08-0{page + 1}T13:00:00Z",
            "url": f"https://publisher.test/{page}",
            "source": "Benzinga",
            "symbols": ["AAPL"],
        }
        body = {"news": [item], "next_page_token": "next" if page == 1 else None}
        return ProviderHTTPResponse(200, {}, json.dumps(body).encode())


def test_alpaca_news_paginates_and_retains_original_attribution() -> None:
    transport = _Transport()
    adapter = AlpacaAdapter(
        api_key_id="fixture-id",
        api_secret_key="fixture-secret",
        api_base_url="https://alpaca.test",
        http_transport=transport,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )

    records = list(
        adapter.fetch_documents(["US:AAPL"], date(2026, 8, 2), date(2026, 8, 3))
    )

    assert len(records) == 2
    assert records[0]["record_type"] == "news_evidence"
    assert records[0]["original_source"] == "Benzinga"
    assert records[0]["source_url"] == "https://publisher.test/1"
    assert records[0]["content"] is None
    assert records[0]["source_locator"] == "alpaca:news:1"
    query = parse_qs(urlparse(transport.requests[1].full_url).query)
    assert query["page_token"] == ["next"]
    assert query["include_content"] == ["false"]
