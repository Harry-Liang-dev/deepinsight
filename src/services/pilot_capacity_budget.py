"""Versioned server-capacity cost safety, not hosted-tokenizer or spend authority.

The existing meter supplies durable reservation, concurrency and elapsed limits.
This adapter reserves the entire documented model capacity, not estimated input
tokens. Real dispatch remains disabled; rehearsal uses the existing Fake boundary.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from src.schemas.research_v2_shared import digest
from src.services.development_model_profile import (
    ModelExecutionProfile,
    profile_record,
    reference_cost,
    require_profile,
)
from src.services.llm_provider import LLMProviderCall
from src.services.pilot_model_readiness import (
    BEIJING,
    SNAPSHOT,
    published_authority,
    request_audit,
)
from src.services.retained_pilot_budget import PilotLimits, PilotMeter, PilotStop

MAX_INPUT = 991808
MAX_OUTPUT = 8192
R3_CONTRACT = "G73_R3_NATIVE_CONTEXT_METERED_PILOT_V1"


def r3_limits() -> PilotLimits:
    """Exact R3 capacity exposure; neither a 32K proof nor a spending approval."""
    return PilotLimits(
        calls=24,
        retries=0,
        input_per_call=MAX_INPUT,
        output_per_call=2048,
        total_tokens=24 * (MAX_INPUT + 2048),
        currency="CNY",
        cost_ceiling=Decimal("2.00"),
        input_per_million=Decimal("1.2"),
        output_per_million=Decimal("4.8"),
        seconds=24 * 90,
    )


def _token_details(value: Any, bound: int, *, output: bool = False) -> int:
    """Validate optional ordinary details; never price an unknown subcategory."""
    if value is None:
        return 0
    allowed = (
        {"reasoning_tokens"}
        if output
        else {
            "cached_tokens",
            "cache_write_tokens",
            "cache_creation_tokens",
            "cache_creation_input_tokens",
        }
    )
    if not isinstance(value, dict) or set(value) - allowed:
        raise PilotStop("PILOT_USAGE_UNREGISTERED_DETAIL")
    for key, count in value.items():
        if type(count) is not int or not 0 <= count <= bound:
            raise PilotStop("PILOT_USAGE_INVALID_DETAIL_COUNT")
        if key != "cached_tokens" and count != 0:
            raise PilotStop("PILOT_USAGE_UNAUTHORIZED_REASONING_OR_CACHE_CREATION")
    # Cache reads remain INCLUDED in gross input at ordinary rates: no discount
    # or new charge policy. Creation is not a cached read.
    return int(value.get("cached_tokens", 0))


def _usage_details(response: dict[str, Any], usage: dict[str, Any]) -> None:
    """Close the entire supported ordinary-text billing envelope before settlement."""
    allowed = {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "input_tokens_details",
        "output_tokens_details",
        "x_details",
        "x_tools",
    }
    if set(usage) - allowed:
        raise PilotStop("PILOT_USAGE_UNREGISTERED_BILLING_FIELD")
    for envelope in (response, usage):
        tools = envelope.get("x_tools")
        if tools is not None and (not isinstance(tools, dict) or tools):
            raise PilotStop("PILOT_USAGE_UNAUTHORIZED_TOOLS")
    if any(
        response.get(key) is not None
        for key in (
            "billing",
            "billing_details",
            "cost",
            "x_details",
            "cache_creation",
            "cache_creation_tokens",
            "cache_creation_input_tokens",
            "reasoning_tokens",
        )
    ):
        raise PilotStop("PILOT_USAGE_UNREGISTERED_RESPONSE_CHARGE")
    cached = _token_details(usage.get("input_tokens_details"), usage["input_tokens"])
    _token_details(
        usage.get("output_tokens_details"), usage["output_tokens"], output=True
    )
    details = usage.get("x_details")
    if details is None:
        return
    # One ordinary response_api billing row is the documented text-only case.
    # Extra/duplicate billing rows are not silently summed into ordinary tokens.
    if not isinstance(details, list) or len(details) != 1:
        raise PilotStop("PILOT_USAGE_UNREGISTERED_BILLING_ROWS")
    row = details[0]
    if (
        not isinstance(row, dict)
        or set(row)
        - {
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "x_billing_type",
            "prompt_tokens_details",
            "input_tokens_details",
            "output_tokens_details",
            "x_tools",
        }
        or row.get("x_billing_type") != "response_api"
    ):
        raise PilotStop("PILOT_USAGE_UNREGISTERED_BILLING_TYPE")
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        if type(row.get(key)) is not int or row[key] != usage[key]:
            raise PilotStop("PILOT_USAGE_DETAIL_TOTAL_MISMATCH")
    if row.get("x_tools") is not None and (
        not isinstance(row["x_tools"], dict) or row["x_tools"]
    ):
        raise PilotStop("PILOT_USAGE_UNAUTHORIZED_TOOLS")
    for key in ("prompt_tokens_details", "input_tokens_details"):
        if key in row and _token_details(row[key], usage["input_tokens"]) != cached:
            raise PilotStop("PILOT_USAGE_CACHE_DETAIL_MISMATCH")
    _token_details(
        row.get("output_tokens_details"), usage["output_tokens"], output=True
    )


def capacity_envelope(
    model_profile: ModelExecutionProfile | None = None,
) -> dict[str, Any]:
    """Return the legacy envelope or explicit development reference profile."""
    require_profile(model_profile)
    if model_profile is not None:
        return profile_record(model_profile)
    return dict(
        version="qwen_beijing_capacity_cost_envelope/1.0.0",
        model=SNAPSHOT,
        endpoint=BEIJING + "/responses",
        region="cn-beijing",
        documentation_identity=digest(published_authority()),
        maximum_input=MAX_INPUT,
        context=1000000,
        default_output=4096,
        maximum_output=MAX_OUTPUT,
        maximum_calls=12,
        initial_calls=8,
        followup_calls=2,
        retries=2,
        concurrency=1,
        automatic_retries=0,
        elapsed_seconds=1200,
        currency="CNY",
        proposed_ceiling="20.00",
        per_attempt_reservation="1.2294912",
        maximum_standard_cost="14.7538944",
        aggregate_capacity_reservation=12000000,
        exact_token_count="UNKNOWN",
        context_enforcement="SERVER_ENFORCED_NOT_LOCAL_FIT_CERTIFICATION",
        assumptions=[
            "Fixed snapshot, Beijing ordinary non-thinking text inference only",
            "Server enforces documented input/context and requested output cap",
            "No tools, search, cache creation, batch, multimodal or paid extras",
            "Highest ordinary input/output rates 1.2/4.8 CNY per million",
            "No discount, FX conversion or account-specific billing assertion",
            "Full reservation retained on missing usage; further calls halt",
        ],
        execution_authorized=False,
        account_access="NOT_TESTED",
        actual_bill=None,
    )


def capacity_limits(
    model_profile: ModelExecutionProfile | None = None,
) -> PilotLimits:
    """Reserve a capacity envelope; model profiles never grant live permission."""
    require_profile(model_profile)
    if model_profile is not None:
        return PilotLimits(
            calls=8,
            retries=0,
            input_per_call=model_profile.input_reservation,
            output_per_call=model_profile.output_cap,
            total_tokens=8
            * (model_profile.input_reservation + model_profile.output_cap),
            currency="CNY",
            cost_ceiling=Decimal("1"),
            input_per_million=model_profile.input_rate,
            output_per_million=model_profile.output_rate,
            seconds=4800,
        )
    return PilotLimits(
        input_per_call=MAX_INPUT,
        output_per_call=MAX_OUTPUT,
        total_tokens=12000000,
        currency="CNY",
        cost_ceiling=Decimal("20.00"),
        input_per_million=Decimal("1.2"),
        output_per_million=Decimal("4.8"),
    )


class CapacityMeter(PilotMeter):
    """Bind full request and approved scope before existing durable reservation."""

    development_accounting = False

    def __init__(
        self,
        persist: Callable[[dict[str, Any]], None],
        *,
        scope: dict[str, Any],
        initial_call_limit: int = 8,
        model_profile: ModelExecutionProfile | None = None,
    ) -> None:
        """Bind orchestration's validated Plan, input and permission scope."""
        require_profile(model_profile)
        if model_profile is not None and not self.development_accounting:
            raise ValueError("DEVELOPMENT_PROFILE_REQUIRES_ACCOUNTING_POLICY")
        self.model_profile = model_profile
        self.expected_model = model_profile.model if model_profile else SNAPSHOT
        self.input_reservation = (
            model_profile.input_reservation if model_profile else MAX_INPUT
        )
        self.settlement_cached = 0
        super().__init__(capacity_limits(model_profile), persist)
        g48 = (
            initial_call_limit == 54
            and scope.get("contract") == "G48_PAIRED_PAID_PRODUCER_V1"
            and scope.get("attempts") == 54
        )
        g54 = (
            initial_call_limit == 12
            and scope.get("contract") == "G54_RESEARCH_PAID_PRODUCER_V1"
            and scope.get("attempts") == 12
        )
        self.r3 = (
            initial_call_limit == 24
            and scope.get("contract") == R3_CONTRACT
            and scope.get("attempts") == 24
        )
        if type(initial_call_limit) is not int or not (
            1 <= initial_call_limit <= 10 or g48 or g54 or self.r3
        ):
            raise ValueError("INVALID_INITIAL_CALL_LIMIT")
        if model_profile is not None and initial_call_limit > 8:
            raise ValueError("DEVELOPMENT_PROFILE_CALL_LIMIT")
        self.initial_call_limit = initial_call_limit
        self.scope_identity = digest(scope)
        self.pending: dict[str, Any] | None = None
        self.current: dict[str, Any] | None = None
        self.initial_calls = self.followup_calls = 0
        self.prepared_identity: str | None = None
        if self.r3:
            self.limits = r3_limits()

    def _envelope_identity(self) -> str:
        if self.model_profile is not None:
            return digest(profile_record(self.model_profile))
        if not self.r3:
            return digest(capacity_envelope())
        return digest(
            dict(
                contract=R3_CONTRACT,
                model=SNAPSHOT,
                endpoint=BEIJING + "/responses",
                limits={
                    k: str(v) if isinstance(v, Decimal) else v
                    for k, v in asdict(r3_limits()).items()
                },
                pricing_identity=digest(published_authority()),
                settlement="APPLICABLE_VERIFIED_TIER_ESTIMATE",
            )
        )

    def _price(self, inputs: int, outputs: int) -> Decimal:
        if self.model_profile is not None:
            return reference_cost(
                self.model_profile, inputs, outputs, self.settlement_cached
            )
        if not self.r3:
            return super()._price(inputs, outputs)
        a, b = (
            ("0.2", "0.8")
            if inputs <= 32000
            else ("0.6", "2.4") if inputs <= 256000 else ("1.2", "4.8")
        )
        return (Decimal(a) * inputs + Decimal(b) * outputs) / Decimal(1000000)

    def prepare_request(
        self,
        call: LLMProviderCall,
        *,
        scope: dict[str, Any],
        endpoint: str = BEIJING + "/responses",
        output_cap: int = 4096,
        kind: str = "INITIAL",
    ) -> dict[str, Any]:
        """Serialize the actual SDK request offline, checking scope and paid surface."""
        try:
            if self.stopped or self.pending is not None or self.active is not None:
                raise ValueError("STOPPED_OR_CONCURRENT")
            if (
                endpoint != BEIJING + "/responses"
                or digest(scope) != self.scope_identity
            ):
                raise ValueError("ENDPOINT_OR_APPROVED_SCOPE")
            if kind not in ("INITIAL", "FOLLOWUP", "RETRY"):
                raise ValueError("ATTEMPT_KIND")
            if self.r3 and (kind != "INITIAL" or output_cap != 2048):
                raise ValueError("R3_EXACT_ATTEMPT_SCOPE")
            if self.model_profile is not None and (
                kind != "INITIAL" or output_cap != self.model_profile.output_cap
            ):
                raise ValueError("DEVELOPMENT_PROFILE_EXACT_ATTEMPT_SCOPE")
            audit = request_audit(
                call, output_cap=output_cap, model_profile=self.model_profile
            )
            audit.update(
                status="PASS",
                reason="COMPLETE_REQUEST_CAPTURE_WITH_CAPACITY_RESERVATION",
                exact_token_count="UNKNOWN",
                endpoint=endpoint,
                scope_identity=self.scope_identity,
                envelope_identity=self._envelope_identity(),
                attempt_kind=kind,
            )
            self.validate_request(audit)
            self.prepared_identity = audit["http_body_sha256"]
            self.pending = dict(audit)
            return dict(audit)
        except Exception as error:
            self.fail("PILOT_CAPACITY_REQUEST_INVALID")
            raise PilotStop("PILOT_CAPACITY_REQUEST_INVALID") from error

    def validate_request(self, audit: dict[str, Any]) -> None:
        """Reject tampered bodies, substituted context and unreviewed paid options."""
        if self.r3 and (
            self.limits != r3_limits()
            or self.initial_call_limit != 24
            or audit["attempt_kind"] != "INITIAL"
            or audit["output_reservation"] != 2048
        ):
            raise PilotStop("R3_LIMIT_DRIFT")
        if self.model_profile is not None and (
            self.limits.input_per_call != self.model_profile.input_reservation
            or self.limits.output_per_call != self.model_profile.output_cap
            or self.limits.retries != 0
            or audit["attempt_kind"] != "INITIAL"
            or audit["output_reservation"] != self.model_profile.output_cap
        ):
            raise PilotStop("DEVELOPMENT_PROFILE_LIMIT_DRIFT")
        raw = audit["serialized_http_body"].encode("utf-8")
        body = json.loads(raw)
        if (
            hashlib.sha256(raw).hexdigest() != audit["http_body_sha256"]
            or len(raw) != audit["http_body_bytes"]
            or digest(body) != audit["canonical_http_identity"]
            or audit["endpoint"] != BEIJING + "/responses"
            or audit["scope_identity"] != self.scope_identity
            or audit["envelope_identity"] != self._envelope_identity()
            or set(body)
            != {
                "model",
                "instructions",
                "input",
                "store",
                "enable_thinking",
                "max_output_tokens",
            }
            | (
                {"text"}
                if self.model_profile and self.model_profile.native_schema_probe
                else set()
            )
            or body["model"] != self.expected_model
            or body["store"] is not False
            or body["enable_thinking"] is not False
            or not isinstance(body["input"], str)
            or not isinstance(body["instructions"], str)
            or type(body["max_output_tokens"]) is not int
            or not 16 <= body["max_output_tokens"] <= MAX_OUTPUT
            or body["max_output_tokens"] != audit["output_reservation"]
        ):
            raise PilotStop("PILOT_REQUEST_IDENTITY_OR_PAID_FEATURE")
        if self.model_profile and self.model_profile.native_schema_probe:

            expected = {
                "format": {
                    "type": "json_schema",
                    "name": "minimal_semantic_proposal",
                    "strict": True,
                    "schema": audit["local_response_schema"],
                }
            }
            if (
                body.get("text") != expected
                or digest(audit["local_response_schema"])
                != "a9986e27384792d1fce294ef516cc9aa41a86817c8b4313854a3cb96e12d1381"
            ):
                raise PilotStop("MINIMAL2_NATIVE_SCHEMA_DRIFT")

    def _record(self, row: dict[str, Any]) -> None:
        binding = self.pending if row["event"] == "RESERVED" else self.current
        super()._record(
            dict(
                row,
                currency="CNY",
                envelope_identity=self._envelope_identity(),
                exact_token_count="UNKNOWN",
                reservation_basis=(
                    "CONSERVATIVE_CONTEXT_ENVELOPE_NOT_ACTUAL_TOKEN_COUNT"
                    if self.model_profile
                    else "DOCUMENTED_SERVER_CAPACITY_NOT_TOKEN_ESTIMATE"
                ),
                request_identity=binding["http_body_sha256"] if binding else None,
                scope_identity=self.scope_identity,
            )
        )

    def reserve(self, inputs: int, *, retry: bool = False) -> int:
        """Only a fully checked pending request can consume a proposed attempt."""
        try:
            if self.pending is None or inputs != self.input_reservation:
                raise PilotStop("PILOT_CAPACITY_RESERVATION_REQUIRED")
            self.validate_request(self.pending)
            if self.pending["http_body_sha256"] != self.prepared_identity:
                raise PilotStop("PILOT_SUBSTITUTED_SERIALIZED_REQUEST")
            kind = self.pending["attempt_kind"]
            if retry != (kind == "RETRY"):
                raise PilotStop("PILOT_RETRY_CLASSIFICATION")
            if (
                kind == "INITIAL" and self.initial_calls >= self.initial_call_limit
            ) or (kind == "FOLLOWUP" and self.followup_calls >= 2):
                raise PilotStop("PILOT_ROLE_CALL_LIMIT")
            result = super().reserve(inputs, retry=retry)
            self.current, self.pending = self.pending, None
            self.initial_calls += int(kind == "INITIAL")
            self.followup_calls += int(kind == "FOLLOWUP")
            return result
        except Exception as error:
            if self.stopped is None:
                self.fail("PILOT_CAPACITY_RESERVATION_FAILED")
            raise PilotStop("PILOT_CAPACITY_RESERVATION_FAILED") from error

    def settle(
        self, inputs: int | None, outputs: int | None, *, retries: int = 0
    ) -> None:
        """Enforce the captured output cap even when reserving the larger envelope."""
        if (
            self.current is None
            or type(outputs) is not int
            or outputs > self.current["output_reservation"]
        ):
            self.fail("PILOT_CAPTURED_OUTPUT_CAP_OR_USAGE")
            raise PilotStop("PILOT_CAPTURED_OUTPUT_CAP_OR_USAGE")
        super().settle(inputs, outputs, retries=retries)
        self.current = None

    def reconcile(
        self,
        response: dict[str, Any],
        *,
        request_id: str,
        persist: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        """Persist server usage and tier estimate before releasing any reservation."""
        try:
            usage = response["usage"]
            inputs, outputs, total = (
                usage[k] for k in ("input_tokens", "output_tokens", "total_tokens")
            )
            if (
                self.active is None
                or self.current is None
                or response.get("model")
                not in (
                    self.model_profile.response_models
                    if self.model_profile
                    else (SNAPSHOT,)
                )
                or not isinstance(response.get("id"), str)
                or not response["id"]
                or not request_id
                or len(request_id) > 128
                or response.get("paid_features") not in (None, [])
                or any(
                    not isinstance(item, dict) or item.get("type") != "message"
                    for item in response.get("output", [])
                )
                or any(type(v) is not int or v < 0 for v in (inputs, outputs, total))
                or inputs > self.input_reservation
                or outputs > self.current["output_reservation"]
                or total != inputs + outputs
            ):
                raise ValueError("UNBOUND_SERVER_USAGE")
            _usage_details(response, usage)
            if self.model_profile is not None:
                if total > self.model_profile.context_ceiling:
                    raise PilotStop("PILOT_CONTEXT_CAPACITY_EXCEEDED")
                detail = usage.get("input_tokens_details")
                cached = (
                    detail.get("cached_tokens") if isinstance(detail, dict) else None
                )
                self.settlement_cached = cached if type(cached) is int else 0
                estimate = reference_cost(
                    self.model_profile, inputs, outputs, self.settlement_cached
                )
                row = dict(
                    model=response["model"],
                    requested_model=self.expected_model,
                    actual_resolved_model=response["model"],
                    region="cn-beijing",
                    request_id=request_id,
                    response_id=response["id"],
                    input_tokens=inputs,
                    output_tokens=outputs,
                    total_tokens=total,
                    cached_tokens=cached,
                    uncached_tokens=(inputs - cached if type(cached) is int else None),
                    cache_category_status=(
                        "PROVIDER_REPORTED"
                        if cached is not None
                        else "UNKNOWN_NOT_REPORTED"
                    ),
                    price_version=self._envelope_identity(),
                    currency="CNY",
                    estimated_cost=str(estimate) if cached is not None else None,
                    conservative_gross_input_reference=str(
                        reference_cost(self.model_profile, inputs, outputs)
                    ),
                    reference_scope=profile_record(self.model_profile)["pricing_scope"],
                    accounting_confidence="SERVER_USAGE_CONDITIONAL_PUBLIC_REFERENCE",
                    actual_billable_cost=None,
                    account_bill="UNKNOWN",
                    ledger_policy="PUBLIC_REFERENCE_ONLY_NO_COST_GATE",
                    validated_usage=usage,
                    usage_validation_version="ordinary_text_usage_envelope/1.0.0",
                )
                persist(row)
                self.settle(inputs, outputs)
                return row
            a, b = (
                ("0.2", "0.8")
                if inputs <= 32000
                else ("0.6", "2.4") if inputs <= 256000 else ("1.2", "4.8")
            )
            row = dict(
                model=SNAPSHOT,
                region="cn-beijing",
                request_id=request_id,
                response_id=response["id"],
                input_tokens=inputs,
                output_tokens=outputs,
                total_tokens=total,
                price_version=digest(published_authority()),
                currency="CNY",
                estimated_cost=str(
                    (Decimal(a) * inputs + Decimal(b) * outputs) / Decimal(1000000)
                ),
                accounting_confidence="SERVER_USAGE_PUBLIC_STANDARD_ESTIMATE",
                actual_billable_cost=None,
                ledger_policy=(
                    "APPLICABLE_VERIFIED_TIER_ESTIMATE"
                    if self.r3
                    else "CONSERVATIVE_HIGHEST_RATE_RETAINED"
                ),
                validated_usage=usage,
                usage_validation_version="ordinary_text_usage_envelope/1.0.0",
            )
            persist(row)
            # Ledger keeps highest-rate cost, even when actual tier estimate is lower.
            self.settle(inputs, outputs)
            return row
        except Exception as error:
            reason = (
                str(error)
                if isinstance(error, PilotStop)
                else ("PILOT_USAGE_OR_DURABLE_ACCOUNTING_FAILED")
            )
            self.fail(reason)
            raise PilotStop(reason) from error

    def context_exceeded(self) -> None:
        """Keep unknown reservation, stop, and preserve State; never trim citations."""
        self.fail("CONTEXT_LENGTH_EXCEEDED")
