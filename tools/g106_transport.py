"""Select the existing HTTPS proxy without parsing unrelated invalid fallback URLs.

No proxy URL is persisted, no environment is mutated, and no direct-route fallback
is provided. Only the frozen Qwen HTTPS endpoint is in scope.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from httpx._utils import URLPattern, get_environment_proxies

from src.services.pilot_model_readiness import BEIJING


def configured_https_proxy() -> tuple[str, dict[str, Any]]:
    """Use the installed HTTPX selector order including NO_PROXY, without sockets."""
    target = httpx.URL(BEIJING + "/responses")
    routes = sorted(
        (URLPattern(key), value) for key, value in get_environment_proxies().items()
    )
    for pattern, value in routes:
        if pattern.matches(target):
            if value is None:
                raise ValueError("G106_TARGET_PROXY_BYPASS_NOT_ALLOWED")
            # Validate only the route actually selected for this frozen endpoint.
            # Never reinterpret socks:// as SOCKS5 or alter a configured route.
            scheme = httpx.URL(value).scheme
            if scheme not in ("http", "https"):
                raise ValueError("G106_SELECTED_PROXY_PROTOCOL_UNCONFIRMED")
            httpx.Proxy(value)
            return value, {
                "selection": "EXISTING_HTTPX_ENVIRONMENT_ROUTE_FOR_FROZEN_HTTPS_TARGET",
                "proxy_protocol": scheme,
                "no_proxy_preserved": True,
                "trust_env": True,
                "environment_mutated": False,
                "fallback_proxy_reinterpreted": False,
                "proxy_url_recorded": False,
            }
    raise ValueError("G106_CONFIGURED_HTTPS_PROXY_REQUIRED")


class DispatchCheckedTransport(httpx.BaseTransport):
    """Gate original transport admission; preserve its HTTP and close behavior."""

    def __init__(
        self, inner: httpx.BaseTransport, check: Callable[[httpx.Request], None]
    ) -> None:
        self.inner, self.check = inner, check

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        """Check at transport entry; failures never enter the underlying sender."""
        self.check(request)
        return self.inner.handle_request(request)

    def close(self) -> None:
        """Close the original transport."""
        self.inner.close()


def recovery_client(
    hooks: dict[str, list[Callable[..., Any]]],
    *,
    fixture_transport: httpx.MockTransport | None = None,
    before_transport: Callable[[httpx.Request], None] | None = None,
) -> httpx.Client:
    """Keep the configured target proxy, environment TLS and original SDK transport."""
    proxy, _ = configured_https_proxy()
    if fixture_transport is not None:
        if type(fixture_transport) is not httpx.MockTransport:
            raise ValueError("G106_FIXTURE_TRANSPORT_REQUIRED")
        return httpx.Client(
            transport=(
                DispatchCheckedTransport(fixture_transport, before_transport)
                if before_transport
                else fixture_transport
            ),
            trust_env=True,
            follow_redirects=False,
            event_hooks=hooks,
        )
    # Explicit proxy suppresses parsing unused ALL_PROXY, not the required egress.
    # The executor's original wire hook permits only the frozen endpoint, no redirects.
    if before_transport is not None:
        return httpx.Client(
            transport=DispatchCheckedTransport(
                httpx.HTTPTransport(proxy=proxy, trust_env=True, retries=0),
                before_transport,
            ),
            trust_env=True,
            follow_redirects=False,
            event_hooks=hooks,
        )
    return httpx.Client(
        proxy=proxy, trust_env=True, follow_redirects=False, event_hooks=hooks
    )
