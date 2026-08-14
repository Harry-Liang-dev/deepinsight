"""Global separation between deterministic offline and explicit live tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

_LIVE_ENVIRONMENT_NAMES = (
    "DEEPINSIGHT_LLM_PROVIDER",
    "QWEN_API_KEY",
    "QWEN_MODEL_NAME",
    "OPENAI_API_KEY",
    "APCA_API_KEY_ID",
    "APCA_API_SECRET_KEY",
    "APCA_API_BASE_URL",
    "DEEPINSIGHT_PROVIDER_SEC_USER_AGENT",
    "DEEPINSIGHT_PROVIDER_SEC_CIK_MAP",
    "DEEPINSIGHT_LIVE_DATASET_VERSION",
    "DEEPINSIGHT_LIVE_AS_OF_DATE",
    "DEEPINSIGHT_LIVE_DATA_START",
    "DEEPINSIGHT_LIVE_DATA_END",
    "STOCKTWITS_MCP_ENABLED",
    "STOCKTWITS_MCP_URL",
    "STOCKTWITS_MCP_TOKEN_STORE",
    "STOCKTWITS_MCP_REDIRECT_URI",
    "STOCKTWITS_MCP_TRUST_ENV",
)


@pytest.fixture(autouse=True)
def isolate_offline_tests_from_live_shell(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Prevent a prepared developer shell from changing offline tests."""

    if request.node.get_closest_marker("live") is None:
        for name in _LIVE_ENVIRONMENT_NAMES:
            monkeypatch.delenv(name, raising=False)
    yield
