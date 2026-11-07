"""G90 exact two-call CapacityMeter and durable request/response hook.

No general authorization service; the user-approved G90 scope is immutable.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from src.schemas.research_v2_shared import canonical
from src.services.llm_provider import LLMProviderCall
from src.services.native_preservation import blob_hash
from src.services.pilot_capacity_budget import MAX_INPUT, CapacityMeter, capacity_limits
from src.services.pilot_model_readiness import BEIJING

SCOPE = dict(
    experiment="G90_REAL_RESEARCH_V2_ADMISSION_AND_MEMORY",
    model="qwen3.7-flash-2026-07-15",
    region="cn-beijing",
    calls=2,
    concurrency=1,
    retries=0,
    fallback="NONE",
    ceiling_cny="2.50",
    input_per_million="1.20",
    output_per_million="4.80",
    output_cap=3072,
    authority="CURRENT_USER_EXPLICIT_G90_INSTRUCTION",
    supplier_bill="UNKNOWN",
)


def durable(path: Path, raw: bytes) -> None:
    """Exclusive immutable artifact write, fsync file and parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class MeteredArchive:
    """Bind actual SDK bytes to the existing meter before any HTTP send."""

    scope = SCOPE

    def __init__(self, path: Path, *, origin: str) -> None:
        if origin not in ("REAL_QWEN", "ENGINEERING_MOCK_SDK"):
            raise ValueError("G90_ORIGIN")
        self.path = path
        self.origin = origin
        self.audit: dict[str, Any] | None = None
        self.dispatches = 0
        self.responses: list[dict[str, Any]] = []
        durable(path / "scope.json", canonical(dict(self.scope, origin=origin)))
        self.meter = CapacityMeter(self.event, scope=self.scope, initial_call_limit=2)
        self.meter.limits = replace(
            capacity_limits(),
            calls=2,
            retries=0,
            input_per_call=MAX_INPUT,
            output_per_call=3072,
            total_tokens=2 * (MAX_INPUT + 3072),
            cost_ceiling=Decimal("2.50"),
            input_per_million=Decimal("1.20"),
            output_per_million=Decimal("4.80"),
            seconds=180,
        )
        self.n = 0
        bound = self.meter._price(MAX_INPUT, 3072)
        if bound * 2 > self.meter.limits.cost_ceiling:
            raise ValueError("G90_TWO_CALL_CAPACITY")
        durable(
            path / "capacity.json",
            canonical(
                dict(
                    per_call=str(bound),
                    two_calls=str(bound * 2),
                    ceiling="2.50",
                    bill="UNKNOWN",
                )
            ),
        )

    def event(self, row: dict[str, Any]) -> None:
        """Append original meter events as independent durable numbered records."""
        durable(self.path / "meter" / f"{self.n:04}.json", canonical(row))
        self.n += 1

    def prepare(self, call: LLMProviderCall) -> dict[str, Any]:
        """Freeze exact real SDK serialization without inference or budget use."""
        if self.audit is not None or self.meter.stopped:
            raise ValueError("G90_ATTEMPT_NOT_AVAILABLE")
        self.audit = self.meter.prepare_request(call, scope=self.scope, output_cap=3072)
        durable(
            self.path / f"request-{self.dispatches+1}.json",
            self.audit["serialized_http_body"].encode(),
        )
        durable(self.path / f"freeze-{self.dispatches+1}.json", canonical(self.audit))
        return self.audit

    def before(self, request: httpx.Request) -> None:
        """Reject mutated body/route and reserve durably before the SDK HTTP write."""
        if (
            self.audit is None
            or self.dispatches >= 2
            or request.method != "POST"
            or str(request.url) != BEIJING + "/responses"
            or blob_hash(request.content) != self.audit["http_body_sha256"]
        ):
            raise ValueError("G90_ACTUAL_REQUEST_MISMATCH")
        self.meter.validate_request(self.audit)
        self.meter.reserve(MAX_INPUT)
        self.dispatches += 1
        self.audit = None
        durable(
            self.path / f"dispatch-{self.dispatches}.json",
            canonical(
                dict(
                    request_sha256=blob_hash(request.content),
                    origin=self.origin,
                    status="DISPATCH_STARTED_RESULT_UNKNOWN",
                )
            ),
        )

    def after(self, response: httpx.Response) -> None:
        """Preserve whole response first; unknown accounting retains reservation."""
        response.read()
        durable(self.path / f"response-{self.dispatches}.raw", response.content)
        row = dict(
            status=response.status_code,
            body_sha256=blob_hash(response.content),
            origin=self.origin,
        )
        self.responses.append(row)
        durable(self.path / f"http-{self.dispatches}.json", canonical(row))
        if response.status_code != 200:
            self.meter.fail("G90_HTTP_NON_200")
            return
        body = json.loads(response.content)
        self.meter.reconcile(
            body,
            request_id=body.get("id", ""),
            persist=lambda r: durable(
                self.path / f"accounting-{self.dispatches}.json", canonical(r)
            ),
        )
