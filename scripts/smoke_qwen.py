"""Run one opt-in DashScope Qwen Responses API compatibility smoke check.

This is a temporary operational check, not a production DeepInsight provider.
It intentionally bypasses the OpenAI-only Phase One Gateway while reusing the
installed OpenAI SDK and the existing ``RiskManagerResponse`` schema.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from pydantic import ValidationError

from src.schemas.agents import RiskManagerResponse

_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_DEFAULT_MODEL = "qwen3.8-max"
_TIMEOUT_SECONDS = 60.0
_SMOKE_PROMPT = """\
Return only one compact JSON object. Do not use Markdown code fences.
The JSON object must contain exactly these fields:
- "confirmed_risks": an array containing exactly one short string
- "scenario_risks": an array containing exactly one short string
- "watch_items": an array containing exactly one short string
- "narrative_risk_score": a number from 0 to 1
Use this minimal context: deepinsight-qwen-live-smoke.
Do not include investment advice, citations, or additional fields.
"""
_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")


class _ResponseLike(Protocol):
    """Narrow Responses API result surface used by this script."""

    @property
    def id(self) -> str:
        """Return the provider response identifier."""

    @property
    def model(self) -> str:
        """Return the resolved provider model."""

    @property
    def output_text(self) -> str:
        """Return the SDK-aggregated final text."""

    @property
    def output(self) -> Sequence[object]:
        """Return typed Responses output items."""

    @property
    def usage(self) -> object | None:
        """Return token usage metadata when supplied."""


@dataclass(frozen=True, slots=True)
class QwenSmokeConfig:
    """Environment-backed configuration for one manual Qwen request."""

    api_key: str
    model: str
    base_url: str
    timeout_seconds: float = _TIMEOUT_SECONDS


class QwenSmokeError(RuntimeError):
    """Safe smoke-check failure with a stable public error code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int | None = None,
        provider_type: str | None = None,
        provider_param: str | None = None,
        provider_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.provider_type = provider_type
        self.provider_param = provider_param
        self.provider_message = provider_message


def _load_config() -> QwenSmokeConfig:
    """Load the temporary smoke configuration from environment variables."""

    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise QwenSmokeError(
            "configuration_error",
            "缺少 DASHSCOPE_API_KEY，请仅通过环境变量注入。",
        )

    model = os.getenv("DASHSCOPE_MODEL", _DEFAULT_MODEL).strip()
    base_url = os.getenv("DASHSCOPE_BASE_URL", _DEFAULT_BASE_URL).strip()
    if not model or not base_url:
        raise QwenSmokeError(
            "configuration_error",
            "DASHSCOPE_MODEL 和 DASHSCOPE_BASE_URL 不得为空。",
        )
    return QwenSmokeConfig(api_key=api_key, model=model, base_url=base_url)


def _diagnostic_request(config: QwenSmokeConfig) -> dict[str, object]:
    """Return the exact request metadata without authorization credentials."""

    return {
        "endpoint": f"{config.base_url.rstrip('/')}/responses",
        "request_body": {
            "model": config.model,
            "input": _SMOKE_PROMPT,
            "enable_thinking": True,
        },
        "sdk_options": {
            "timeout_seconds": config.timeout_seconds,
            "max_retries": 0,
        },
    }


def _sanitize_provider_message(message: str | None, api_key: str) -> str | None:
    """Redact the injected credential and common API-key shapes."""

    if message is None:
        return None
    sanitized = message.replace(api_key, "[REDACTED]") if api_key else message
    return _KEY_PATTERN.sub("[REDACTED]", sanitized)


def _provider_error(exc: APIStatusError, api_key: str) -> QwenSmokeError:
    """Map an SDK status error to a safe, diagnostic smoke error."""

    status_code = exc.status_code
    if status_code in {401, 403}:
        code = "authentication_error"
        public_message = "DashScope 凭据或模型权限被拒绝"
    elif status_code == 429:
        code = "rate_limit"
        public_message = "DashScope 请求超过额度或速率限制"
    elif status_code == 400:
        code = "invalid_request"
        public_message = "DashScope 拒绝了请求参数"
    else:
        code = "provider_error"
        public_message = "DashScope 请求失败"

    body = exc.body if isinstance(exc.body, dict) else {}
    nested_error = body.get("error")
    error = nested_error if isinstance(nested_error, dict) else body
    provider_type = error.get("type")
    provider_param = error.get("param")
    provider_message = error.get("message")
    return QwenSmokeError(
        code,
        public_message,
        status_code=status_code,
        provider_type=provider_type if isinstance(provider_type, str) else None,
        provider_param=provider_param if isinstance(provider_param, str) else None,
        provider_message=_sanitize_provider_message(
            provider_message if isinstance(provider_message, str) else str(exc),
            api_key,
        ),
    )


def _reasoning_previews(response: _ResponseLike) -> list[str]:
    """Collect bounded reasoning summaries without exposing full model output."""

    previews: list[str] = []
    for item in response.output:
        if getattr(item, "type", None) != "reasoning":
            continue
        for summary in getattr(item, "summary", ()) or ():
            text = getattr(summary, "text", None)
            if isinstance(text, str) and text.strip():
                previews.append(text.strip()[:500])
    return previews


def _validate_response(response: _ResponseLike) -> RiskManagerResponse:
    """Parse and validate the final answer with the existing Agent schema."""

    try:
        content = json.loads(response.output_text)
    except json.JSONDecodeError as exc:
        raise QwenSmokeError(
            "invalid_json",
            "Qwen 最终响应不是有效 JSON",
        ) from exc
    if not isinstance(content, dict):
        raise QwenSmokeError(
            "invalid_json",
            "Qwen 最终响应 JSON 必须是对象",
        )

    try:
        validated = RiskManagerResponse.model_validate(content)
    except ValidationError as exc:
        raise QwenSmokeError(
            "schema_validation",
            "Qwen 响应未通过 RiskManagerResponse 校验",
        ) from exc

    groups = (
        validated.confirmed_risks,
        validated.scenario_risks,
        validated.watch_items,
    )
    if any(len(group) != 1 or not group[0].strip() for group in groups):
        raise QwenSmokeError(
            "schema_validation",
            "Qwen 响应不符合最小烟雾测试形状",
        )
    return validated


def _run_live(
    config: QwenSmokeConfig,
    *,
    client: object | None = None,
    diagnostic: bool = False,
) -> dict[str, object]:
    """Make exactly one compatible Responses request and validate its output."""

    sdk_client = (
        OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout_seconds,
            max_retries=0,
        )
        if client is None
        else client
    )
    try:
        response = cast(OpenAI, sdk_client).responses.create(
            model=config.model,
            input=_SMOKE_PROMPT,
            extra_body={"enable_thinking": True},
        )
    except APITimeoutError as exc:
        raise QwenSmokeError("timeout", "DashScope 请求超时") from exc
    except APIStatusError as exc:
        raise _provider_error(exc, config.api_key) from exc
    except APIConnectionError as exc:
        raise QwenSmokeError(
            "connection_error",
            "无法连接 DashScope Responses API",
        ) from exc

    typed_response = cast(_ResponseLike, response)
    _validate_response(typed_response)
    usage = getattr(typed_response, "usage", None)
    result: dict[str, object] = {
        "status": "ok",
        "provider": "dashscope-qwen-compatible",
        "model": getattr(typed_response, "model", config.model),
        "schema": RiskManagerResponse.__name__,
        "response_id": getattr(typed_response, "id", None),
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
    }
    if diagnostic:
        result["reasoning_summary_previews"] = _reasoning_previews(typed_response)
        result["diagnostic_request"] = _diagnostic_request(config)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    """Load configuration, execute the live check, and return a shell code."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="输出脱敏请求参数及最多 500 字的推理摘要",
    )
    args = parser.parse_args(argv)

    try:
        config = _load_config()
        result = _run_live(config, diagnostic=args.diagnostic)
    except QwenSmokeError as exc:
        error: dict[str, object] = {
            "status": "error",
            "error_code": exc.code,
            "message": str(exc),
        }
        if args.diagnostic:
            for name, value in (
                ("provider_status_code", exc.status_code),
                ("provider_type", exc.provider_type),
                ("provider_param", exc.provider_param),
                ("provider_message", exc.provider_message),
            ):
                if value is not None:
                    error[name] = value
            try:
                error["diagnostic_request"] = _diagnostic_request(_load_config())
            except QwenSmokeError:
                pass
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        return 2 if exc.code == "configuration_error" else 1

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
