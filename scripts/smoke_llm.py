"""Run one explicit, low-cost live LLM Gateway smoke check.

This module is intentionally outside the default pytest suite. It loads the
same application settings and invokes the same production ``LLMGateway`` used
by DeepInsight, while keeping its cache in a temporary DuckDB database.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from tempfile import TemporaryDirectory
from typing import Any, cast

import structlog
from pydantic import ValidationError
from structlog.testing import CapturingLogger

from src.core import AppSettings, load_settings
from src.models.types import JsonObject
from src.repositories import DuckDBDatabase, LLMCacheRepository
from src.schemas.agents import RiskManagerResponse
from src.services import (
    LLMCacheError,
    LLMGateway,
    LLMProviderError,
    OpenAIProvider,
)

_SYSTEM_PROMPT = (
    "Return only one compact JSON object with exactly these fields: "
    "confirmed_risks, scenario_risks, watch_items, narrative_risk_score. "
    "Each list must contain exactly one short string. "
    "narrative_risk_score must be a number from 0 to 1. "
    "Do not add markdown, citations, recommendations, or extra fields."
)
_INPUT_MARKER = "deepinsight-live-smoke-minimal-input"
_INPUT_PAYLOAD: JsonObject = {"context": _INPUT_MARKER}
_REQUIRED_LOG_FIELDS = {
    "provider",
    "model",
    "status",
    "cache_hit",
    "latency_ms",
    "request_fingerprint",
}
_REQUIRED_SUCCESS_LOG_FIELDS = {
    *_REQUIRED_LOG_FIELDS,
    "prompt_tokens",
    "completion_tokens",
    "response_id",
}


class SmokeCheckError(RuntimeError):
    """Raised when the live smoke response or metadata fails validation."""


def _diagnostic_request(settings: AppSettings) -> dict[str, object]:
    """Return the exact smoke request body without authorization headers."""

    encoded_input = OpenAIProvider.encode_input_payload(_INPUT_PAYLOAD)
    return {
        "endpoint": "https://api.openai.com/v1/responses",
        "request_body": {
            "model": settings.openai.model_fast,
            "instructions": _SYSTEM_PROMPT,
            "input": encoded_input,
            "text": {"format": {"type": "json_object"}},
            "store": settings.openai.store_remote,
        },
        "sdk_options": {
            "timeout_seconds": settings.openai.timeout_seconds,
            "max_retries": settings.openai.max_retries,
        },
    }


def _capturing_logger() -> tuple[Any, CapturingLogger]:
    """Create a bound logger whose emitted metadata can be inspected."""

    logger = CapturingLogger()
    bound_logger = structlog.BoundLogger(logger, [], {})
    return cast(Any, bound_logger), logger


def _assert_log_safety(
    logger: CapturingLogger,
    *,
    api_key: str,
) -> dict[str, Any]:
    """Verify captured records contain metadata but no request secrets."""

    if not logger.calls:
        raise SmokeCheckError("LLM Gateway did not emit request metadata")

    serialized_logs = repr(logger.calls)
    forbidden_values = (api_key, _SYSTEM_PROMPT, _INPUT_MARKER)
    if any(value and value in serialized_logs for value in forbidden_values):
        raise SmokeCheckError("LLM Gateway logs contain sensitive request data")

    metadata = dict(logger.calls[-1].kwargs)
    missing_fields = _REQUIRED_LOG_FIELDS.difference(metadata)
    if missing_fields:
        raise SmokeCheckError("LLM Gateway logs are missing required metadata")
    if metadata["status"] == "error" and "error_code" not in metadata:
        raise SmokeCheckError("LLM Gateway failure log is missing its error code")
    return metadata


def _validate_response(content: dict[str, object]) -> RiskManagerResponse:
    """Validate provider JSON with the existing Phase One Agent schema."""

    response = RiskManagerResponse.model_validate(content)
    groups = (
        response.confirmed_risks,
        response.scenario_risks,
        response.watch_items,
    )
    if any(len(group) != 1 or not group[0].strip() for group in groups):
        raise SmokeCheckError("LLM response did not follow the compact smoke shape")
    return response


def _run_live_check(settings: AppSettings, api_key: str) -> dict[str, object]:
    """Execute exactly one Gateway invocation and return safe result metadata."""

    bound_logger, captured_logger = _capturing_logger()
    model = settings.openai.model_fast

    with TemporaryDirectory(prefix="deepinsight-llm-smoke-") as temporary_root:
        database = DuckDBDatabase(f"{temporary_root}/smoke.duckdb")
        database.bootstrap()
        cache = LLMCacheRepository(database)
        gateway = LLMGateway(
            cache,
            settings.openai,
            logger=bound_logger,
        )

        try:
            content = gateway.invoke_json(
                model,
                _SYSTEM_PROMPT,
                _INPUT_PAYLOAD,
            )
        except (LLMCacheError, LLMProviderError):
            _assert_log_safety(captured_logger, api_key=api_key)
            raise

        metadata = _assert_log_safety(captured_logger, api_key=api_key)
        missing_success_fields = _REQUIRED_SUCCESS_LOG_FIELDS.difference(metadata)
        if missing_success_fields:
            raise SmokeCheckError(
                "LLM Gateway success log is missing required metadata"
            )
        response = _validate_response(cast(dict[str, object], content))
        cache_key = LLMGateway.build_cache_key(
            model,
            _SYSTEM_PROMPT,
            _INPUT_PAYLOAD,
        )
        cached = cache.get(cache_key)
        if cached is None:
            raise SmokeCheckError(
                "LLM response was not persisted in the temporary cache"
            )
        cached_response = RiskManagerResponse.model_validate(cached.response)
        if cached_response != response:
            raise SmokeCheckError("Cached LLM response differs from validated output")
        if (
            metadata["provider"] != "openai"
            or metadata["status"] != "ok"
            or metadata["cache_hit"] is not False
        ):
            raise SmokeCheckError("LLM Gateway success metadata is inconsistent")

        return {
            "status": "ok",
            "provider": metadata["provider"],
            "model": metadata["model"],
            "schema": RiskManagerResponse.__name__,
            "cache_persisted": True,
            "prompt_tokens": metadata["prompt_tokens"],
            "completion_tokens": metadata["completion_tokens"],
            "response_id": metadata["response_id"],
            "request_fingerprint": metadata["request_fingerprint"],
        }


def main(argv: Sequence[str] | None = None) -> int:
    """Load live configuration, run the smoke check, and return a shell code."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="print the redacted provider response and exact smoke request body",
    )
    args = parser.parse_args(argv)
    settings = load_settings()
    secret = settings.openai.api_key
    if secret is None or not secret.get_secret_value().strip():
        print(
            "未执行：缺少 OPENAI_API_KEY，请通过环境变量或本地 .env 注入。",
            file=sys.stderr,
        )
        return 2
    if settings.openai.max_retries != 0:
        print(
            "未执行：烟雾测试要求 OPENAI_MAX_RETRIES=0，以保证最多一次远程请求。",
            file=sys.stderr,
        )
        return 2
    if settings.openai.store_remote:
        print(
            "未执行：烟雾测试要求 OPENAI_STORE_REMOTE=false。",
            file=sys.stderr,
        )
        return 2

    api_key = secret.get_secret_value()
    try:
        result = _run_live_check(settings, api_key)
    except (LLMCacheError, LLMProviderError) as exc:
        error_result: dict[str, object] = {
            "status": "error",
            "error_code": exc.code,
            "message": str(exc),
        }
        if isinstance(exc, LLMProviderError):
            provider_metadata = {
                "provider_code": exc.provider_code,
                "provider_param": exc.provider_param,
                "provider_type": exc.provider_type,
                "provider_request_id": exc.provider_request_id,
            }
            error_result.update(
                {
                    key: value
                    for key, value in provider_metadata.items()
                    if value is not None
                }
            )
            if args.diagnostic:
                diagnostic = _diagnostic_request(settings)
                if exc.provider_endpoint is not None:
                    diagnostic["endpoint"] = exc.provider_endpoint
                error_result.update(
                    {
                        "provider_status_code": exc.provider_status_code,
                        "provider_message": exc.provider_message,
                        "provider_retry_after": exc.provider_retry_after,
                        "provider_rate_limit_reset_requests": (
                            exc.provider_rate_limit_reset_requests
                        ),
                        "provider_rate_limit_reset_tokens": (
                            exc.provider_rate_limit_reset_tokens
                        ),
                        "diagnostic_request": diagnostic,
                    }
                )
        print(
            json.dumps(error_result, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    except ValidationError:
        print(
            '{"status":"error","error_code":"schema_validation",'
            '"message":"LLM response failed RiskManagerResponse validation"}',
            file=sys.stderr,
        )
        return 1
    except SmokeCheckError as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_code": "smoke_validation",
                    "message": str(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
