"""Compatibility entry point for the unified Qwen LLM Gateway smoke."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence

from scripts.smoke_llm import main as gateway_smoke_main
from src.core import LLMProviderName, load_settings


def main(argv: Sequence[str] | None = None) -> int:
    """Require Qwen selection and delegate to the unified Gateway smoke.

    Args:
        argv: Optional command-line arguments forwarded to ``smoke_llm``.

    Returns:
        Process exit code from the unified live smoke.
    """

    settings = load_settings()
    if settings.llm.provider is not LLMProviderName.QWEN:
        print(
            json.dumps(
                {
                    "status": "configuration_error",
                    "message": (
                        "请设置 DEEPINSIGHT_LLM_PROVIDER=qwen；"
                        "本脚本不再维护平行 SDK 调用路径。"
                    ),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    return gateway_smoke_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
