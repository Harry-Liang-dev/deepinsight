"""Explicit multi-source live report test excluded from default pytest."""

from __future__ import annotations

import os

import pytest

from scripts import live_report

pytestmark = pytest.mark.live

_REQUIRED_LIVE_NAMES = (
    "QWEN_API_KEY",
    "QWEN_MODEL_NAME",
    "APCA_API_KEY_ID",
    "APCA_API_SECRET_KEY",
    "APCA_API_BASE_URL",
    "DEEPINSIGHT_PROVIDER_SEC_USER_AGENT",
    "DEEPINSIGHT_PROVIDER_SEC_CIK_MAP",
    "DEEPINSIGHT_LIVE_DATASET_VERSION",
    "DEEPINSIGHT_LIVE_AS_OF_DATE",
    "DEEPINSIGHT_LIVE_DATA_START",
    "DEEPINSIGHT_LIVE_DATA_END",
)


@pytest.mark.skipif(
    any(not os.getenv(name) for name in _REQUIRED_LIVE_NAMES)
    or os.getenv("DEEPINSIGHT_LLM_PROVIDER") != "qwen",
    reason="Complete live report environment variables are not configured",
)
def test_multisource_live_report_and_evaluation() -> None:
    """Run the production SEC, Alpaca, Qwen, report, and Judge chain."""

    assert live_report.main() == 0
