"""Closed SEC target configurations; a target or plan is never execution approval."""

from __future__ import annotations

from typing import Literal

from src.schemas.research_v2_shared import Frozen, Text, canonical

TargetID = Literal["G43_AAPL", "G50_AAPL", "G50_MSFT", "G55_MSFT_2026", "G55_MSFT_2025"]


class SECSourceTarget(Frozen):
    """Exact reviewed/proposed file identity, no wildcard or discovery fallback."""

    key: TargetID
    owner: Text
    cik: Text
    accession: Text
    primary_document: Text
    period_end: Text
    form: Literal["10-Q", "10-K"] = "10-Q"

    @property
    def urls(self) -> tuple[str, str]:
        """Return exactly the two ordered official endpoints."""
        return (
            f"https://data.sec.gov/submissions/CIK{self.cik}.json",
            f"https://www.sec.gov/Archives/edgar/data/{int(self.cik)}/"
            f"{self.accession.replace('-', '')}/{self.primary_document}",
        )


TARGETS = (
    SECSourceTarget(
        key="G43_AAPL",
        owner="US:AAPL",
        cik="0000320193",
        accession="0000320193-26-000020",
        primary_document="aapl-20260627.htm",
        period_end="2026-06-27",
    ),
    SECSourceTarget(
        key="G50_AAPL",
        owner="US:AAPL",
        cik="0000320193",
        accession="0000320193-26-000013",
        primary_document="aapl-20260328.htm",
        period_end="2026-03-28",
    ),
    SECSourceTarget(
        key="G50_MSFT",
        owner="US:MSFT",
        cik="0000789019",
        accession="0001193125-26-191507",
        primary_document="msft-20260331.htm",
        period_end="2026-03-31",
    ),
    SECSourceTarget(
        key="G55_MSFT_2026",
        owner="US:MSFT",
        cik="0000789019",
        accession="0001193125-26-323660",
        primary_document="msft-20260630.htm",
        period_end="2026-06-30",
        form="10-K",
    ),
    SECSourceTarget(
        key="G55_MSFT_2025",
        owner="US:MSFT",
        cik="0000789019",
        accession="0000950170-25-100235",
        primary_document="msft-20250630.htm",
        period_end="2025-06-30",
        form="10-K",
    ),
)


def source_target(key: str = "G43_AAPL") -> SECSourceTarget:
    """Resolve only a closed target key, never accept caller-defined fields."""
    for target in TARGETS:
        if target.key == key:
            return target
    raise ValueError("SEC_UNREGISTERED_TARGET_CONFIG")


def target_plan(key: str, source_run: str) -> bytes:
    """Create an inactive G50 per-run proposal, not a Grant or approval record."""
    target = source_target(key)
    annual = target.key.startswith("G55_")
    if annual:
        if (
            source_run
            != f"g55-sec-native-msft-{target.period_end.replace('-', '')}-annual-v1"
        ):
            raise ValueError("SEC_G55_EXACT_SOURCE_RUN_REQUIRED")
    elif target.key == "G43_AAPL" or not source_run.startswith("g50-"):
        raise ValueError("SEC_G50_NEW_SCOPE_AND_RUN_REQUIRED")
    return canonical(
        dict(
            version="G55_SEC_SOURCE_PLAN_V1" if annual else "G50_SEC_SOURCE_PLAN_V1",
            target=target,
            source_run=source_run,
            urls=target.urls,
            method="GET",
            maximum_requests=2,
            concurrency=1,
            minimum_dispatch_spacing_seconds=1,
            timeout_seconds=30,
            session_timeout_seconds=120,
            retries=0,
            redirects=0,
            maximum_entity_bytes=20_000_000,
            execution_authorization="PENDING",
            actual_response_identity_required=True,
        )
    )
