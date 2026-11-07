"""Code-owned development model profile; public prices are not account billing."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class ModelExecutionProfile:
    """Closed trusted-runtime identity, never deserialized from a request."""

    version: str
    model: str
    response_models: tuple[str, ...]
    context_ceiling: int
    input_reservation: int
    output_cap: int
    input_rate: Decimal
    output_rate: Decimal
    cached_rate: Decimal
    native_schema_probe: bool = False


QWEN38_DEVELOPMENT_PROFILE = ModelExecutionProfile(
    version="G113_R7_QWEN38_DEVELOPMENT_PROFILE_V1",
    model="qwen3.8-flash",
    response_models=("qwen3.8-flash",),
    context_ceiling=1000000,
    input_reservation=1000000,
    output_cap=8192,
    input_rate=Decimal("1"),
    output_rate=Decimal("3"),
    cached_rate=Decimal("0.1"),
)


MINIMAL2_SCHEMA_PROFILE = replace(
    QWEN38_DEVELOPMENT_PROFILE,
    version="MINIMAL2_SCHEMA_PROFILE_V1",
    output_cap=512,
    native_schema_probe=True,
)
MINIMAL2_EVIDENCE_PROFILE = replace(
    QWEN38_DEVELOPMENT_PROFILE,
    version="MINIMAL2_EVIDENCE_PROFILE_V1",
    output_cap=1024,
    native_schema_probe=True,
)


def require_profile(profile: ModelExecutionProfile | None) -> None:
    """Reject reconstructed, mutable or caller-selected tariff/model profiles."""
    if profile is not None and not any(
        profile is p
        for p in (
            QWEN38_DEVELOPMENT_PROFILE,
            MINIMAL2_SCHEMA_PROFILE,
            MINIMAL2_EVIDENCE_PROFILE,
        )
    ):
        raise ValueError("UNREGISTERED_DEVELOPMENT_MODEL_PROFILE")


def profile_record(profile: ModelExecutionProfile) -> dict[str, Any]:
    """Expose exact limits and conditional public reference, never a live permit."""
    require_profile(profile)
    return dict(
        version=profile.version,
        model=profile.model,
        response_models=list(profile.response_models),
        response_alias_policy="EXACT_REQUEST_ALIAS_ONLY_NO_UNVERIFIED_SNAPSHOT_GUESS",
        context_ceiling=profile.context_ceiling,
        input_reservation=profile.input_reservation,
        reservation_basis="CONSERVATIVE_CONTEXT_ENVELOPE_NOT_ACTUAL_TOKEN_COUNT",
        public_rounded_max_input="991K",
        public_rounded_max_output="131K",
        responses_input_limit="PUBLIC_DOC_APPROXIMATELY_80_PERCENT_POSSIBLE_TRUNCATION",
        exact_request_fit_certified=False,
        output_cap=profile.output_cap,
        exact_context_fit="UNKNOWN",
        tokenizer_template_authority="EXACT_MODEL_TOKENIZER_AND_TEMPLATE_AUTHORITY_UNAVAILABLE",
        public_price_source="https://www.qianwenai.com/models/qwen3.8-flash",
        public_price_reviewed_on="2026-11-04",
        currency="CNY",
        input_per_million=str(profile.input_rate),
        output_per_million=str(profile.output_rate),
        cached_input_per_million=str(profile.cached_rate),
        pricing_scope="PUBLIC_MODEL_PAGE_CONDITIONAL_REFERENCE_NOT_ACCOUNT_OR_REGION_TARIFF_CERTIFICATION",
        account_billing="UNKNOWN",
        account_model_access="UNKNOWN_NOT_PROBED",
        actual_resolved_model_version="UNKNOWN_UNTIL_PROVIDER_RESPONSE",
        cost_admission_gate="DISABLED_DEVELOPMENT_ONLY",
        execution_authorized=False,
    )


def reference_cost(
    profile: ModelExecutionProfile, inputs: int, outputs: int, cached: int = 0
) -> Decimal:
    """Calculate a conditional public-list estimate from actual Usage categories."""
    require_profile(profile)
    return (
        profile.input_rate * (inputs - cached)
        + profile.cached_rate * cached
        + profile.output_rate * outputs
    ) / Decimal(1000000)
