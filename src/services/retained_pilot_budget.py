"""Finite reservation ledger at the existing Gateway boundary, disabled for live use.

No financial-data or Evidence authority is defined here. Rehearsal metering is
explicitly simulated; a live permit, tokenizer and pricing registration are still
required before the disabled activation boundary can be replaced by reviewed code.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from time import monotonic
from typing import Any, Literal

from pydantic import BaseModel

from src.models.types import JsonObject
from src.services.llm_gateway import LLMGateway, LLMRunResult
from src.services.llm_provider import FakeLLMProvider


class PilotStop(RuntimeError):
    """Safe stop code without provider content or credentials."""


@dataclass(frozen=True)
class PilotLimits:
    """Finite proposed or test limits; construction never grants spending authority."""

    calls: int = 12
    retries: int = 2
    input_per_call: int = 16000
    output_per_call: int = 2048
    total_tokens: int = 216576
    cost_ceiling: Decimal = Decimal("5.00")
    currency: Literal["USD", "CNY"] = "USD"
    input_per_million: Decimal | None = None
    output_per_million: Decimal | None = None
    seconds: float = 1200.0

    def __post_init__(self) -> None:
        """Reject unbounded, coerced, nonfinite or negative accounting inputs."""
        if self.currency not in ("USD", "CNY"):
            raise ValueError("INVALID_BUDGET_CURRENCY")
        for n in (
            self.calls,
            self.input_per_call,
            self.output_per_call,
            self.total_tokens,
        ):
            if type(n) is not int or n <= 0:
                raise ValueError("INVALID_PILOT_LIMIT")
        if type(self.retries) is not int or not 0 <= self.retries <= self.calls:
            raise ValueError("INVALID_RETRY_LIMIT")
        if not 0 < self.seconds < float("inf"):
            raise ValueError("INVALID_TIME_LIMIT")
        for value in (
            self.cost_ceiling,
            self.input_per_million,
            self.output_per_million,
        ):
            if value is not None and (not value.is_finite() or value < 0):
                raise ValueError("INVALID_PRICE_OR_CEILING")
        if self.cost_ceiling <= 0:
            raise ValueError("INVALID_PRICE_OR_CEILING")


class PilotMeter:
    """Reserve before dispatch; persist every attempt and never refund unknown usage."""

    def __init__(
        self,
        limits: PilotLimits,
        persist: Callable[[dict[str, Any]], None],
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        """Require caller-owned append-only persistence and an elapsed-time clock."""
        self.limits, self.persist, self.clock = limits, persist, clock
        self.started = clock()
        self.calls = self.retries = self.tokens = 0
        self.cost = Decimal(0)
        self.active: tuple[int, int, Decimal] | None = None
        self.stopped: str | None = None
        self.receipts: list[dict[str, Any]] = []

    def _record(self, row: dict[str, Any]) -> None:
        try:
            self.persist(dict(row))
        except Exception:
            self.stopped = "PILOT_LEDGER_PERSISTENCE_FAILED"
            raise PilotStop(self.stopped) from None
        self.receipts.append(dict(row))

    def _price(self, inputs: int, outputs: int) -> Decimal:
        a, b = self.limits.input_per_million, self.limits.output_per_million
        if a is None or b is None:
            raise PilotStop("PILOT_PRICE_UNAVAILABLE")
        return (a * inputs + b * outputs) / Decimal(1000000)

    def reserve(self, inputs: int, *, retry: bool = False) -> int:
        """Charge a complete attempt before the Gateway can receive its input."""
        try:
            return self._reserve(inputs, retry=retry)
        except PilotStop as error:
            if self.stopped is None:
                self.fail(str(error))
            raise

    def _reserve(self, inputs: int, *, retry: bool) -> int:
        if self.stopped:
            raise PilotStop(self.stopped)
        if self.active is not None:
            raise PilotStop("PILOT_CONCURRENT_CALL")
        if self.clock() - self.started >= self.limits.seconds:
            raise PilotStop("PILOT_TIME_EXHAUSTED")
        if type(inputs) is not int or not 0 < inputs <= self.limits.input_per_call:
            raise PilotStop("PILOT_INPUT_LIMIT")
        if self.calls >= self.limits.calls:
            raise PilotStop("PILOT_CALL_LIMIT")
        if retry and self.retries >= self.limits.retries:
            raise PilotStop("PILOT_RETRY_LIMIT")
        tokens = inputs + self.limits.output_per_call
        cost = self._price(inputs, self.limits.output_per_call)
        if self.tokens + tokens > self.limits.total_tokens:
            raise PilotStop("PILOT_TOKEN_LIMIT")
        if self.cost + cost > self.limits.cost_ceiling:
            raise PilotStop("PILOT_COST_LIMIT")
        number = self.calls + 1
        self._record(
            dict(
                event="RESERVED",
                attempt=number,
                input_bound=inputs,
                output_bound=self.limits.output_per_call,
                cost_bound=str(cost),
                retry=retry,
            )
        )
        self.calls = number
        self.retries += int(retry)
        self.tokens += tokens
        self.cost += cost
        self.active = number, tokens, cost
        return number

    def settle(
        self, inputs: int | None, outputs: int | None, *, retries: int = 0
    ) -> None:
        """Validate usage; unproved usage halts without refunding reservation."""
        if self.active is None:
            raise PilotStop("PILOT_NO_ACTIVE_ATTEMPT")
        number, reserved_tokens, reserved_cost = self.active
        self.active = None
        reserved_input = reserved_tokens - self.limits.output_per_call
        if (
            type(inputs) is not int
            or type(outputs) is not int
            or inputs < 0
            or outputs < 0
            or inputs > reserved_input
            or outputs > self.limits.output_per_call
            or retries != 0
        ):
            self.stopped = "PILOT_USAGE_UNPROVEN_OR_LIMIT_BREACH"
            self._record(dict(event="STOP", attempt=number, reason=self.stopped))
            raise PilotStop(self.stopped)
        actual_cost = self._price(inputs, outputs)
        self._record(
            dict(
                event="SETTLED",
                attempt=number,
                input_tokens=inputs,
                output_tokens=outputs,
                cost=str(actual_cost),
            )
        )
        self.tokens -= reserved_tokens - inputs - outputs
        self.cost -= reserved_cost - actual_cost
        if self.clock() - self.started >= self.limits.seconds:
            self.stopped = "PILOT_TIME_EXHAUSTED"
            raise PilotStop(self.stopped)

    def fail(self, reason: str) -> None:
        """Retain charged unknown usage and halt; recovery needs reviewed policy."""
        self.stopped = reason
        self._record(dict(event="STOP", reason=reason, attempt=self.calls))
        self.active = None


class RehearsalBudgetGateway:
    """Wrap the actual Gateway with simulated metering; real providers are denied."""

    supports_structured_repair = False

    def __init__(
        self,
        gateway: LLMGateway,
        meter: PilotMeter,
        count_request: Callable[[str, JsonObject, type[BaseModel] | None], int],
        *,
        model: str,
    ) -> None:
        """Only the existing Fake provider may cross this rehearsal boundary."""
        if type(gateway._provider) is not FakeLLMProvider:
            raise PilotStop("REAL_LLM_ACTIVATION_DISABLED")
        self.gateway, self.meter, self.count_request, self.model = (
            gateway,
            meter,
            count_request,
            model,
        )

    def invoke_json_with_metadata(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
        *,
        prompt_version: str,
        schema_version: str,
        response_model: type[BaseModel] | None = None,
    ) -> LLMRunResult:
        """Meter complete request before invoking the unchanged production Gateway."""
        if model != self.model:
            raise PilotStop("PILOT_MODEL_BINDING")
        self.meter.reserve(
            self.count_request(system_prompt, input_payload, response_model)
        )
        try:
            result = self.gateway.invoke_json_with_metadata(
                model,
                system_prompt,
                input_payload,
                prompt_version=prompt_version,
                schema_version=schema_version,
                response_model=response_model,
            )
        except Exception:
            self.meter.fail("PILOT_GATEWAY_FAILURE_USAGE_UNKNOWN")
            raise
        self.meter.settle(
            result.metadata.input_tokens,
            result.metadata.output_tokens,
            retries=result.metadata.retry_count,
        )
        return result

    def invoke_json(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
        *,
        prompt_version: str,
        schema_version: str,
        response_model: type[BaseModel] | None = None,
    ) -> JsonObject:
        """Expose the existing Agent Gateway protocol without a second runtime."""
        return self.invoke_json_with_metadata(
            model,
            system_prompt,
            input_payload,
            prompt_version=prompt_version,
            schema_version=schema_version,
            response_model=response_model,
        ).content
