"""Safety fixtures for explicitly selected real-service tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def use_http_proxy_without_ambiguous_all_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Avoid HTTPX's unsupported generic ``socks://`` proxy scheme.

    Clash may publish both protocol-specific HTTP proxies and a generic SOCKS
    proxy. HTTPX can use the former for HTTPS requests. Removing only the two
    generic names keeps the live test deterministic without reading, logging,
    or modifying any proxy value in the parent process.
    """

    monkeypatch.delenv("ALL_PROXY", raising=False)
    monkeypatch.delenv("all_proxy", raising=False)
    yield
