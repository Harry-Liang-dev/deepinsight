"""Explicit real-Provider smokes excluded from the default test suite."""

from __future__ import annotations

import os

import pytest

from scripts import smoke_alpaca, smoke_qwen, smoke_sec_edgar

pytestmark = pytest.mark.live


@pytest.mark.skipif(
    not os.getenv("QWEN_API_KEY")
    or not os.getenv("QWEN_MODEL_NAME")
    or os.getenv("DEEPINSIGHT_LLM_PROVIDER") != "qwen",
    reason="Qwen live environment variables are not configured",
)
def test_qwen_gateway_live() -> None:
    """Call Qwen only through the unified LLM Gateway smoke."""

    assert smoke_qwen.main([]) == 0


@pytest.mark.skipif(
    not os.getenv("APCA_API_KEY_ID")
    or not os.getenv("APCA_API_SECRET_KEY")
    or not os.getenv("APCA_API_BASE_URL"),
    reason="Alpaca live environment variables are not configured",
)
def test_alpaca_market_data_live() -> None:
    """Call the configured real Alpaca EOD Provider smoke."""

    assert smoke_alpaca.main([]) == 0


@pytest.mark.skipif(
    not os.getenv("DEEPINSIGHT_PROVIDER_SEC_USER_AGENT")
    or not os.getenv("DEEPINSIGHT_PROVIDER_SEC_CIK_MAP"),
    reason="SEC live environment variables are not configured",
)
def test_sec_edgar_live() -> None:
    """Call the identified real SEC EDGAR Provider smoke."""

    assert smoke_sec_edgar.main([]) == 0
