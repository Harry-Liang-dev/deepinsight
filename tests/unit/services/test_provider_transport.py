"""Tests for the shared OpenAI-compatible Provider transport policy."""

from __future__ import annotations

from src.services.provider_transport import resolve_provider_transport_config


def test_transport_policy_prefers_http_over_conflicting_socks() -> None:
    """A usable HTTPS proxy must override conflicting generic SOCKS safely."""

    secret = "proxy-secret-must-not-leak"
    config = resolve_provider_transport_config(
        {
            "HTTPS_PROXY": "http://proxy.unit.test:8080",
            "ALL_PROXY": f"socks://user:{secret}@proxy.unit.test:1080",
        }
    )

    assert config.proxy_mode == "protocol_http_over_conflicting_socks"
    assert config.transport_mode == "explicit_httpx_trust_env_false"
    assert secret not in repr(config)


def test_transport_policy_keeps_socks_only_fail_closed() -> None:
    """SOCKS-only environments must not silently become direct connections."""

    config = resolve_provider_transport_config(
        {"all_proxy": "socks5://proxy.unit.test:1080"}
    )

    assert config.proxy_mode == "socks_only"
    assert config.transport_mode == "sdk_default_fail_closed"
    assert config.build_http_client() is None


def test_transport_policy_no_proxy_keeps_sdk_default() -> None:
    """An empty environment should preserve normal SDK behavior."""

    config = resolve_provider_transport_config({})

    assert config.proxy_mode == "no_proxy"
    assert config.transport_mode == "sdk_default"
    assert config.build_http_client() is None
