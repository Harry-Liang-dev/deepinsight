"""Closed Qwen pilot registry and offline request/usage checks; no activation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
from openai import OpenAI
from openai.types.responses import Response
from pydantic import SecretStr

from src.core.settings import QwenSettings
from src.schemas.research_v2_shared import canonical, digest
from src.services.development_model_profile import (
    ModelExecutionProfile,
    require_profile,
)
from src.services.llm_provider import LLMProviderCall, QwenProvider
from src.services.retained_pilot_budget import PilotLimits, PilotMeter, PilotStop

SNAPSHOT = "qwen3.7-flash-2026-07-15"
BEIJING = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def published_authority() -> dict[str, Any]:
    """Return Main's dated official-doc review, not a provider/account receipt."""
    return dict(
        version="qwen_beijing_pilot_documentation_review/1.0.0",
        reviewed_on="2026-10-09",
        documented_model=SNAPSHOT,
        region="cn-beijing",
        endpoint=BEIJING + "/responses",
        official_sources=[
            "https://help.aliyun.com/zh/model-studio/qwen3-7-flash",
            "https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-responses",
        ],
        evidence_kind="REVIEWED_DOCUMENTATION_NOT_RAW_HTTP_RECEIPT",
        max_input=991808,
        max_output=131072,
        context_length=1000000,
        thinking=False,
        standard_price=dict(
            input_tier_max_tokens=32000,
            currency="CNY",
            input_per_million="0.2",
            output_per_million="0.8",
            billing="STANDARD_LIST_NOT_ACCOUNT_BILL",
        ),
        standard_tiers=[
            dict(input_max=32000, input_rate="0.2", output_rate="0.8"),
            dict(input_max=256000, input_rate="0.6", output_rate="2.4"),
            dict(input_max=1000000, input_rate="1.2", output_rate="4.8"),
        ],
        account_access="NOT_TESTED",
        account_pricing="UNKNOWN",
        tokenizer_identity=None,
        message_template_identity=None,
        token_bound_proven=False,
    )


def cny_budget_proposal() -> dict[str, Any]:
    """Price conditional bounded attempts; this is not token or spend authority."""
    maximum = (Decimal("0.2") * 192000 + Decimal("0.8") * 24576) / 1000000
    return dict(
        version="qwen_beijing_cny_pilot_proposal/1.0.0",
        currency="CNY",
        calls=12,
        initial=8,
        followups=2,
        retries=2,
        input_per_call=16000,
        output_per_call=2048,
        aggregate_tokens=216576,
        maximum_standard_cost=str(maximum),
        proposed_cost="0.06",
        price_registry_identity=digest(published_authority()),
        status="UNAPPROVED_CONDITIONAL_ON_VERIFIED_REQUEST_TOKEN_BOUND",
        authorized_cost=None,
        account_bill=None,
        execution_authorized=False,
    )


def cny_pilot_limits() -> PilotLimits:
    """Return finite same-currency simulation limits, not permission to dispatch."""
    return PilotLimits(
        currency="CNY",
        cost_ceiling=Decimal("0.06"),
        input_per_million=Decimal("0.2"),
        output_per_million=Decimal("0.8"),
    )


def prepared_configuration(config: QwenSettings) -> dict[str, Any]:
    """Propose an explicit snapshot override without changing environment defaults."""
    if (
        config.base_url != BEIJING
        or config.model_default not in ("qwen3.7-flash", SNAPSHOT)
        or config.enable_thinking
        or config.store_remote
        or config.max_retries != 0
    ):
        raise ValueError("PILOT_UNREVIEWED_MODEL_CONFIGURATION")
    return dict(
        configured_model=config.model_default,
        proposed_request_model=SNAPSHOT,
        explicit_pilot_override=config.model_default != SNAPSHOT,
        endpoint=BEIJING + "/responses",
        region="cn-beijing",
        timeout_seconds=config.timeout_seconds,
        retries_inside_transport=0,
        output_limit=2048,
        account_access="NOT_TESTED",
        execution_authorized=False,
        registry_identity=digest(published_authority()),
    )


class _CapturedRequest(RuntimeError):
    """End the offline inspection exactly at the SDK transport boundary."""


class _CaptureClient:
    def __init__(self) -> None:
        self.request: dict[str, Any] | None = None

    @property
    def responses(self) -> _CaptureClient:
        return self

    def create(
        self,
        *,
        model: str,
        instructions: str,
        input: str,
        store: bool,
        timeout: float,
        extra_body: object | None,
        text: object | None = None,
    ) -> Response:
        self.request = dict(
            model=model,
            instructions=instructions,
            input=input,
            store=store,
            timeout=timeout,
            extra_body=extra_body,
        )
        if text is not None:
            self.request["text"] = text
        raise _CapturedRequest("OFFLINE_TRANSPORT_CAPTURE")


def request_audit(
    call: LLMProviderCall,
    *,
    output_cap: int = 2048,
    model_profile: ModelExecutionProfile | None = None,
) -> dict[str, Any]:
    """Capture the actual Qwen serializer, not a guessed subset or token estimate."""
    require_profile(model_profile)
    expected_model = model_profile.model if model_profile else SNAPSHOT
    if call.model != expected_model:
        raise ValueError("PILOT_REQUEST_MODEL_IDENTITY")
    if type(output_cap) is not int or not 16 <= output_cap <= 8192:
        raise ValueError("PILOT_OUTPUT_CAP")
    client = _CaptureClient()
    settings = QwenSettings.model_validate(
        dict(
            api_key=SecretStr("OFFLINE_SENTINEL_NOT_A_CREDENTIAL"),
            QWEN_MODEL_NAME=expected_model,
            base_url=BEIJING,
            max_retries=0,
            store_remote=False,
            enable_thinking=False,
            max_output_tokens=output_cap,
        )
    )
    provider = QwenProvider(
        settings,
        client=client,
        native_schema_probe=bool(model_profile and model_profile.native_schema_probe),
    )
    try:
        provider._create_response(
            model=call.model,
            system_prompt=call.system_prompt,
            encoded_input=provider.encode_input_payload(call.input_payload),
            response_schema=call.response_schema,
            schema_name="pilot_response",
        )
    except _CapturedRequest:
        if client.request is None:
            raise ValueError("PILOT_EMPTY_REQUEST_CAPTURE") from None
    else:
        raise ValueError("PILOT_OFFLINE_CAPTURE_DID_NOT_STOP")
    bodies: list[bytes] = []

    def capture_http(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content)
        return httpx.Response(
            200,
            json={
                "id": "offline-wire-audit",
                "object": "response",
                "created_at": 0,
                "model": expected_model,
                "output": [],
                "status": "completed",
            },
        )

    # Run the real SDK serialization with an in-memory transport. No DNS/socket
    # is opened; neither fake response nor bytes are token-counting authority.
    with httpx.Client(transport=httpx.MockTransport(capture_http)) as http:
        with OpenAI(
            api_key="OFFLINE_SENTINEL_NOT_A_CREDENTIAL",
            base_url=BEIJING,
            max_retries=0,
            http_client=http,
        ) as sdk:
            QwenProvider(
                settings,
                client=sdk,
                native_schema_probe=bool(
                    model_profile and model_profile.native_schema_probe
                ),
            )._create_response(
                model=call.model,
                system_prompt=call.system_prompt,
                encoded_input=provider.encode_input_payload(call.input_payload),
                response_schema=call.response_schema,
                schema_name="pilot_response",
            )
    if len(bodies) != 1:
        raise ValueError("PILOT_WIRE_CAPTURE_COUNT")
    body = bodies[0]
    return dict(
        full_sdk_arguments=client.request,
        request_identity=digest(client.request),
        serialized_utf8_bytes=len(canonical(client.request)),
        bytes_are_not_tokens=True,
        serialized_http_body=body.decode("utf-8"),
        http_body_sha256=hashlib.sha256(body).hexdigest(),
        http_body_bytes=len(body),
        canonical_http_identity=digest(json.loads(body)),
        local_response_schema=call.response_schema,
        local_response_schema_identity=digest(call.response_schema),
        native_schema_transmitted=bool(
            model_profile and model_profile.native_schema_probe
        ),
        provider_message_template="UNVERIFIED",
        input_tokens=None,
        input_token_bound=None,
        output_reservation=output_cap,
        status="FAIL",
        reason="EXACT_MODEL_TOKENIZER_AND_TEMPLATE_AUTHORITY_UNAVAILABLE",
        real_llm_calls=0,
    )


def require_counting_authority(audit: dict[str, Any]) -> None:
    """No model-compatible counter has been approved; never turn bytes into tokens."""
    del audit  # Caller-controlled counts cannot confer authority.
    raise PilotStop("PILOT_TOKENIZER_AUTHORITY_UNAVAILABLE")


def settle_usage(
    meter: PilotMeter,
    response: dict[str, Any],
    *,
    request_id: str,
    persist: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    """Prepare strict Responses usage accounting; absent usage halts further calls.

    This helper does not dispatch. Its meter must be independently configured
    with the published CNY rates and a same-currency authorized ceiling.
    No USD/CNY conversion or account billing confirmation is inferred.
    """
    try:
        if meter.active is None:
            raise ValueError("NO_RESERVED_ATTEMPT")
        if (
            meter.limits.currency != "CNY"
            or meter.limits.input_per_million != Decimal("0.2")
            or meter.limits.output_per_million != Decimal("0.8")
            or meter.limits.input_per_call > 32000
        ):
            raise ValueError("UNBOUND_PRICE_TIER")
        if response.get("model") != SNAPSHOT:
            raise ValueError("MODEL_RESPONSE_IDENTITY")
        response_id = response.get("id")
        if (
            not isinstance(response_id, str)
            or not response_id
            or not request_id
            or len(request_id) > 128
        ):
            raise ValueError("MISSING_PROVIDER_IDENTITIES")
        usage = response.get("usage")
        if not isinstance(usage, dict):
            raise ValueError("MISSING_PROVIDER_USAGE")
        inputs, outputs, total = (
            usage.get(k) for k in ("input_tokens", "output_tokens", "total_tokens")
        )
        if any(type(n) is not int or n < 0 for n in (inputs, outputs, total)):
            raise ValueError("INVALID_PROVIDER_USAGE")
        assert isinstance(inputs, int) and isinstance(outputs, int)
        if total != inputs + outputs:
            raise ValueError("PROVIDER_USAGE_SUM_MISMATCH")
        row = dict(
            model=SNAPSHOT,
            region="cn-beijing",
            request_id=request_id,
            response_id=response_id,
            input_tokens=inputs,
            output_tokens=outputs,
            total_tokens=total,
            currency="CNY",
            estimated_cost=str(
                (Decimal("0.2") * inputs + Decimal("0.8") * outputs) / Decimal(1000000)
            ),
            actual_billable_cost=None,
            accounting_confidence="SERVER_USAGE_WITH_STANDARD_PRICE_ESTIMATE",
            registry_identity=digest(published_authority()),
        )
        persist(row)  # Durable detailed usage must precede releasing reservation.
        meter.settle(inputs, outputs)
        return row
    except Exception as error:
        meter.fail("PILOT_USAGE_OR_DURABLE_ACCOUNTING_FAILED")
        raise PilotStop("PILOT_USAGE_OR_DURABLE_ACCOUNTING_FAILED") from error
