"""Shared transport policy for OpenAI-compatible remote providers."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx
import openai

_SOCKS_SCHEMES = {"socks", "socks5", "socks5h"}
_HTTP_SCHEMES = {"http", "https"}
_GENERIC_PROXY_NAMES = ("ALL_PROXY", "all_proxy")
_PROTOCOL_PROXY_NAMES = (
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
)
_ALL_PROXY_NAMES = (*_GENERIC_PROXY_NAMES, *_PROTOCOL_PROXY_NAMES)


@dataclass(frozen=True, slots=True)
class ProviderTransportConfig:
    """Resolved transport mode without exposing a proxy URL in metadata."""

    proxy_mode: str
    transport_mode: str
    _proxy_url: str | None = field(default=None, repr=False, compare=False)

    def build_http_client(self) -> httpx.Client | None:
        """Build an explicit safe client only when ambient selection conflicts."""

        if self._proxy_url is None:
            return None
        return openai.DefaultHttpxClient(
            proxy=self._proxy_url,
            trust_env=False,
        )


def resolve_provider_transport_config(
    environment: Mapping[str, str] | None = None,
) -> ProviderTransportConfig:
    """Resolve one shared Chat/Embedding proxy policy.

    A protocol-specific HTTP proxy takes precedence only when an ambient
    generic SOCKS proxy would otherwise be selected by HTTPX. No environment
    variable is modified. A SOCKS-only environment remains delegated to the
    SDK so supported transports work and unsupported transports fail closed.

    Args:
        environment: Optional environment mapping for deterministic tests.

    Returns:
        Safe transport modes plus an internally retained explicit proxy URL.
    """

    values = os.environ if environment is None else environment
    generic_socks = any(
        _scheme(values.get(name)) in _SOCKS_SCHEMES for name in _GENERIC_PROXY_NAMES
    )
    protocol_http_proxy = next(
        (
            proxy
            for name in _PROTOCOL_PROXY_NAMES
            if (proxy := values.get(name)) and _scheme(proxy) in _HTTP_SCHEMES
        ),
        None,
    )
    if generic_socks and protocol_http_proxy is not None:
        return ProviderTransportConfig(
            proxy_mode="protocol_http_over_conflicting_socks",
            transport_mode="explicit_httpx_trust_env_false",
            _proxy_url=protocol_http_proxy,
        )
    if generic_socks:
        return ProviderTransportConfig(
            proxy_mode="socks_only",
            transport_mode="sdk_default_fail_closed",
        )
    if any(values.get(name) for name in _ALL_PROXY_NAMES):
        return ProviderTransportConfig(
            proxy_mode="ambient_proxy",
            transport_mode="sdk_default",
        )
    return ProviderTransportConfig(
        proxy_mode="no_proxy",
        transport_mode="sdk_default",
    )


def _scheme(value: str | None) -> str:
    return "" if not value else urlsplit(value).scheme.casefold()
