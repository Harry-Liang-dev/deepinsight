"""Run the Day35 Sector Research Agent over fixed Day32-Day34 snapshots."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

from src.agents import (
    SectorResearchAgent,
    SectorResearchPromptLoader,
)
from src.agents.sector_research import SECTOR_RESEARCH_PROMPT_VERSION
from src.core import load_settings
from src.memory.contracts import (
    MissingContext,
    MissingContextReason,
    ResearchContextBundle,
    ResearchContextSection,
    RetrievalMetadata,
    RetrievalStatus,
)
from src.models.enums import (
    AgentStatus,
    EventSeverity,
    Market,
    MemoryLevel,
    OntologyStatus,
    SectorId,
)
from src.models.types import DomainModel, JsonObject
from src.repositories import DuckDBDatabase, SectorOntologyRepository
from src.repositories.records import LLMCacheRecord
from src.schemas.sector_research import (
    SectorClaimCategory,
    SectorResearchDraftResponse,
    SectorResearchExecutionResult,
    SectorResearchInput,
)
from src.services import (
    LLMFailureMetadata,
    LLMGateway,
    build_configured_llm_provider,
    build_sector_ontology_seed_v1,
)
from src.services.research_clock import parse_research_clock

_SECTORS = (
    SectorId.SEMICONDUCTORS_AI_COMPUTE,
    SectorId.MEMORY_STORAGE,
    SectorId.CONSUMER_ELECTRONICS_HARDWARE,
)
_SECTOR_NAMES = {
    SectorId.SEMICONDUCTORS_AI_COMPUTE: "Semiconductors & AI Compute",
    SectorId.MEMORY_STORAGE: "Memory & Storage",
    SectorId.CONSUMER_ELECTRONICS_HARDWARE: ("Consumer Electronics & Hardware"),
}
_SECTOR_SCOPES = {
    SectorId.SEMICONDUCTORS_AI_COMPUTE: "SECTOR:SEMICONDUCTORS_AI",
    SectorId.MEMORY_STORAGE: "SECTOR:MEMORY_STORAGE",
    SectorId.CONSUMER_ELECTRONICS_HARDWARE: "SECTOR:CONSUMER_ELECTRONICS",
}


class _MemoryCache:
    """Process-local cache isolated to one explicit smoke run."""

    def __init__(self) -> None:
        self.records: dict[str, LLMCacheRecord] = {}

    def get(self, cache_key: str) -> LLMCacheRecord | None:
        """Return a response cached in this process only."""

        return self.records.get(cache_key)

    def put(self, record: LLMCacheRecord) -> None:
        """Retain one credential-free cache record."""

        self.records[record.cache_key] = record


class _FailureCollector:
    """Retain credential-free Gateway failures for the smoke manifest."""

    def __init__(self) -> None:
        self.records: list[LLMFailureMetadata] = []

    def record_failure(self, metadata: LLMFailureMetadata) -> None:
        """Append one immutable diagnostic emitted by the Gateway."""

        self.records.append(metadata)


class _FixedSectorGateway:
    """Produce deterministic Claim drafts from the real compact Evidence."""

    def invoke_json(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
        *,
        prompt_version: str,
        schema_version: str,
        response_model: type[DomainModel],
    ) -> JsonObject:
        """Return a stable response without network or metric calculation."""

        del model, system_prompt, prompt_version, schema_version
        assert response_model is SectorResearchDraftResponse
        manifest = cast(list[JsonObject], input_payload["evidence_manifest"])
        selected = _select_fixed_evidence(manifest)
        claims: list[JsonObject] = []
        for evidence in selected:
            kind = cast(str, evidence["kind"])
            description = cast(str, evidence["description"])
            requires_degradation = cast(bool, evidence["requires_degradation"])
            candidate_only = cast(bool, evidence["candidate_only"])
            prefix = ""
            if requires_degradation:
                prefix = "Partial or uncertain upstream Evidence: "
            if candidate_only:
                prefix = "Uncertain propagation candidate Evidence: "
            claims.append(
                {
                    "claim_path": f"claims[{len(claims)}]",
                    "claim_text": f"{prefix}{description}",
                    "category": _category_for_kind(kind),
                    "evidence_ids": [cast(str, evidence["evidence_id"])],
                    "numeric_literals": [],
                    "confidence": 0.7,
                    "claim_intent": "analytical_inference",
                }
            )
        return cast(
            JsonObject,
            {
                "claims": claims,
                "cycle_assessment": {
                    "phase": "uncertain",
                    "confidence": 0.5,
                    "supporting_claim_paths": ["claims[0]", "claims[1]"],
                    "uncertainty": (
                        "Sector and Macro indicators may conflict; the assessment "
                        "does not resolve that conflict into a trading signal."
                    ),
                },
                "uncertainties": [
                    "The fixed smoke preserves every PARTIAL, proxy, and missing input."
                ],
            },
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sector-state-db",
        type=Path,
        default=Path("data/live_sector_state/20260830T034235Z/sector_state.duckdb"),
    )
    parser.add_argument(
        "--sector-macro-db",
        type=Path,
        default=Path("data/live_sector_macro/20260830T051233Z/sector_macro.duckdb"),
    )
    parser.add_argument(
        "--sector-radar-db",
        type=Path,
        default=Path("data/live_sector_radar/20260830T074510Z/sector_radar.duckdb"),
    )
    parser.add_argument("--prompt-root", type=Path, default=Path("config/prompts"))
    parser.add_argument(
        "--output-root", type=Path, default=Path("data/live_sector_research")
    )
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--model")
    parser.add_argument("--as-of", type=parse_research_clock)
    parser.add_argument(
        "--sector",
        choices=[item.value for item in _SECTORS],
        help="Run one Sector only; omitted keeps the three-Sector smoke.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run fixed real-data smoke, optionally through the configured live LLM."""

    args = _parser().parse_args(argv)
    source_paths = (
        args.sector_state_db,
        args.sector_macro_db,
        args.sector_radar_db,
    )
    if any(not path.exists() for path in source_paths):
        print(json.dumps({"status": "configuration_error", "reason": "DB missing"}))
        return 2
    state = SectorOntologyRepository(DuckDBDatabase(args.sector_state_db))
    macro = SectorOntologyRepository(DuckDBDatabase(args.sector_macro_db))
    radar = SectorOntologyRepository(DuckDBDatabase(args.sector_radar_db))
    as_of = _latest_common_as_of(state, macro)
    if as_of is None:
        print(json.dumps({"status": "configuration_error", "reason": "state missing"}))
        return 2
    clock = args.as_of
    if clock is not None and clock.snapshot_date != as_of:
        print(
            json.dumps(
                {
                    "status": "configuration_error",
                    "reason": "as-of instant and source snapshot date differ",
                }
            )
        )
        return 2
    research_as_of = (
        clock.research_as_of
        if clock is not None
        else parse_research_clock(as_of.isoformat()).research_as_of
    )

    provider_name = "fake"
    model_name = args.model or "fixed-sector-smoke-v1"
    gateway: _FixedSectorGateway | LLMGateway = _FixedSectorGateway()
    failure_collector: _FailureCollector | None = None
    if args.live:
        settings = load_settings()
        try:
            configured = build_configured_llm_provider(settings)
        except ValueError:
            print(json.dumps({"status": "not_configured", "provider": "llm"}))
            return 2
        failure_collector = _FailureCollector()
        gateway = LLMGateway(
            _MemoryCache(),
            provider=configured.provider,
            failure_sink=failure_collector,
        )
        provider_name = configured.provider_name.value
        model_name = args.model or configured.model_default

    selected_sectors = _SECTORS if args.sector is None else (SectorId(args.sector),)
    inputs = [
        _build_input(
            sector_id,
            research_as_of=research_as_of,
            state=state,
            macro=macro,
            radar=radar,
        )
        for sector_id in selected_sectors
    ]
    agent = SectorResearchAgent(
        gateway,
        SectorResearchPromptLoader(args.prompt_root),
    )
    results = []
    gateway_failures: list[LLMFailureMetadata | None] = []
    try:
        for research_input in inputs:
            failure_count = (
                0 if failure_collector is None else len(failure_collector.records)
            )
            result = agent.run(
                run_id=f"sector-research-{research_input.sector_id.value}",
                model_name=model_name,
                research_input=research_input,
            )
            results.append(result)
            gateway_failures.append(
                failure_collector.records[-1]
                if failure_collector is not None
                and len(failure_collector.records) > failure_count
                else None
            )
    except Exception as exc:  # pragma: no cover - live provider boundary
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "message": "Sector research Provider execution failed.",
                },
                sort_keys=True,
            )
        )
        return 1

    summaries = [
        _result_summary(
            research_input,
            result,
            provider=provider_name,
            model=model_name,
            gateway_failure=gateway_failure,
        )
        for research_input, result, gateway_failure in zip(
            inputs,
            results,
            gateway_failures,
            strict=True,
        )
    ]
    stamp = datetime.now(UTC)
    run_dir = args.output_root / stamp.strftime("%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, exist_ok=False)
    output_files: dict[str, str] = {}
    validation_files: dict[str, str] = {}
    for research_input, result in zip(inputs, results, strict=True):
        if result.output is None:
            artifact = result.diagnostics.get("validation_artifact")
            if isinstance(artifact, dict):
                validation_path = run_dir / (
                    f"{research_input.sector_id.value}.validation.json"
                )
                validation_path.write_text(
                    json.dumps(artifact, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                validation_files[research_input.sector_id.value] = str(validation_path)
            continue
        output_path = run_dir / f"{research_input.sector_id.value}.output.json"
        output_path.write_text(
            result.output.model_dump_json(indent=2),
            encoding="utf-8",
        )
        output_files[research_input.sector_id.value] = str(output_path)
    manifest = {
        "status": (
            "ok"
            if all(result.status is AgentStatus.OK for result in results)
            else "error"
        ),
        "run_id": run_dir.name,
        "timestamp": stamp.isoformat(),
        "research_as_of": research_as_of.isoformat(),
        "provider": provider_name,
        "provider_real": args.live,
        "model": model_name,
        "prompt_version": SECTOR_RESEARCH_PROMPT_VERSION,
        "schema_version": "sector_research_output_v1",
        "source_databases": [str(path) for path in source_paths],
        "memory_context": "explicit_empty_with_missing_context",
        "output_files": output_files,
        "validation_files": validation_files,
        "gates": _gate_summary(summaries),
        "sectors": summaries,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(manifest, sort_keys=True))
    return 0 if manifest["status"] == "ok" else 1


def _build_input(
    sector_id: SectorId,
    *,
    research_as_of: datetime,
    state: SectorOntologyRepository,
    macro: SectorOntologyRepository,
    radar: SectorOntologyRepository,
) -> SectorResearchInput:
    as_of = research_as_of.date()
    universe = state.get_latest_universe_snapshot(sector_id, as_of=as_of)
    snapshot = state.get_latest_research_snapshot(sector_id, as_of=as_of)
    macro_snapshot = macro.get_latest_macro_snapshot(sector_id, as_of=as_of)
    if universe is None or snapshot is None or macro_snapshot is None:
        raise ValueError(f"aligned Sector snapshot missing for {sector_id.value}")
    seed = build_sector_ontology_seed_v1()
    chains = tuple(
        item
        for item in seed.chains
        if item.sector_id is sector_id
        and item.status is OntologyStatus.ACTIVE
        and item.is_effective(as_of)
    )
    memberships = tuple(
        item
        for item in state.list_sector_memberships(sector_id, as_of=as_of)
        if item.is_effective(as_of)
    )
    all_nodes = tuple(item for item in state.list_nodes(as_of=as_of))
    own_node_ids = {item.node_id for item in all_nodes if item.sector_id is sector_id}
    all_edges = tuple(state.list_edges(as_of=as_of))
    relevant_edges = tuple(
        item
        for item in all_edges
        if item.source_node_id in own_node_ids or item.target_node_id in own_node_ids
    )
    relevant_node_ids = {
        node_id
        for edge in relevant_edges
        for node_id in (edge.source_node_id, edge.target_node_id)
    } | own_node_ids
    nodes = tuple(item for item in all_nodes if item.node_id in relevant_node_ids)
    events = tuple(
        radar.list_anomalies_for_scope(
            _SECTOR_SCOPES[sector_id],
            as_of=research_as_of,
        )
    )
    membership_chain_ids = (
        chain_id for item in memberships for chain_id in item.chain_ids
    )
    event_chain_ids = (chain_id for item in events for chain_id in item.chain_ids)
    chain_ids = tuple(dict.fromkeys((*membership_chain_ids, *event_chain_ids)))
    known_chain_ids = {item.chain_id for item in chains}
    scoped_chain_ids = tuple(
        chain_id for chain_id in chain_ids if chain_id in known_chain_ids
    )
    return SectorResearchInput(
        research_as_of=research_as_of,
        sector_id=sector_id,
        sector_name=_SECTOR_NAMES[sector_id],
        sector_scope_id=_SECTOR_SCOPES[sector_id],
        chain_scope_ids=tuple(f"CHAIN:{item}" for item in scoped_chain_ids),
        universe_snapshot=universe,
        sector_snapshot=snapshot,
        macro_snapshot=macro_snapshot,
        benchmark_mapping=state.get_benchmark_mapping(sector_id, as_of=as_of),
        anomaly_events=events,
        industry_chains=chains,
        memberships=memberships,
        graph_nodes=nodes,
        graph_edges=relevant_edges,
        memory_context=_empty_memory_context(
            research_as_of,
            _SECTOR_SCOPES[sector_id],
            tuple(f"CHAIN:{item}" for item in scoped_chain_ids),
        ),
    )


def _empty_memory_context(
    research_as_of: datetime,
    sector_scope: str,
    chain_scopes: tuple[str, ...],
) -> ResearchContextBundle:
    missing = [
        MissingContext(
            section=section,
            reason=MissingContextReason.NO_RELEVANT_MEMORY,
            detail="No relevant historical Memory was available at this cutoff.",
            requested_levels=list(MemoryLevel),
        )
        for section in ResearchContextSection
    ]
    return ResearchContextBundle(
        current_snapshot=[],
        macro_events=[],
        asset_events=[],
        prior_research=[],
        prior_risk=[],
        historical_analogs=[],
        regime_context=[],
        retrieval_metadata=RetrievalMetadata(
            query_id=f"sector-smoke-{sector_scope}",
            query_text=f"Sector research {sector_scope}",
            as_of=research_as_of,
            market=Market.US,
            namespace_keys=[sector_scope, *chain_scopes],
            requested_levels=list(MemoryLevel),
            min_importance_score=0.0,
            top_k_per_section=3,
            snapshot_id=f"memory-empty-{sector_scope}",
            candidate_count=0,
            eligible_count=0,
            result_count=0,
            excluded_future_count=0,
            excluded_namespace_count=0,
            excluded_asset_count=0,
            excluded_market_count=0,
            excluded_importance_count=0,
            excluded_expired_count=0,
            excluded_current_report_count=0,
            section_counts={section: 0 for section in ResearchContextSection},
            status=RetrievalStatus.EMPTY,
            no_relevant_memory=True,
        ),
        missing_context=missing,
    )


def _select_fixed_evidence(manifest: list[JsonObject]) -> list[JsonObject]:
    selected: list[JsonObject] = []
    for kind in ("market_state", "macro_state", "macro_sensitivity"):
        item = next(value for value in manifest if value["kind"] == kind)
        selected.append(item)
    selected_ids = {cast(str, item["evidence_id"]) for item in selected}
    for item in manifest:
        evidence_id = cast(str, item["evidence_id"])
        if item["kind"] != "anomaly_event" or evidence_id in selected_ids:
            continue
        description = cast(str, item["description"])
        if "severity=high" in description or "severity=critical" in description:
            selected.append(item)
    return selected


def _category_for_kind(kind: str) -> str:
    return {
        "market_state": SectorClaimCategory.TREND.value,
        "macro_state": SectorClaimCategory.MACRO_ENVIRONMENT.value,
        "macro_sensitivity": SectorClaimCategory.MACRO_SENSITIVITY.value,
        "anomaly_event": SectorClaimCategory.ANOMALIES.value,
    }[kind]


def _result_summary(
    research_input: SectorResearchInput,
    result: object,
    *,
    provider: str,
    model: str,
    gateway_failure: LLMFailureMetadata | None = None,
) -> JsonObject:
    typed = cast("SectorResearchExecutionResult", result)
    if typed.output is None:
        return {
            "sector_id": research_input.sector_id.value,
            "status": typed.status.value,
            "error_code": None if typed.error is None else typed.error.code,
            "error_message_safe": (
                gateway_failure.error_message_safe
                if gateway_failure is not None
                else None if typed.error is None else typed.error.message
            ),
            "configuration_stage": (
                None if gateway_failure is None else gateway_failure.configuration_stage
            ),
            "provider": provider,
            "model": model,
            "error_details": None if typed.error is None else typed.error.details,
        }
    output = typed.output
    accepted_ids = {item.entry.evidence_id for item in output.evidence_manifest}
    invalid_citations = sum(
        evidence_id not in accepted_ids
        for claim in output.claims
        for evidence_id in claim.evidence_ids
    )
    high_ids = {
        f"event:{item.event_id}"
        for item in research_input.anomaly_events
        if item.severity in {EventSeverity.HIGH, EventSeverity.CRITICAL}
    }
    cited_ids = {value for claim in output.claims for value in claim.evidence_ids}
    partial_claims = [
        item
        for item in output.claims
        if any(
            evidence.entry.evidence_id in item.evidence_ids
            and evidence.requires_degradation
            for evidence in output.evidence_manifest
        )
    ]
    return {
        "sector_id": research_input.sector_id.value,
        "status": typed.status.value,
        "input_status": research_input.sector_snapshot.status.value,
        "benchmark_status": (
            "missing"
            if research_input.benchmark_mapping is None
            else research_input.benchmark_mapping.status.value
        ),
        "candidate_claims": len(output.claims) + len(output.rejected_claims),
        "accepted_claims": len(output.claims),
        "quarantined_claims": len(output.rejected_claims),
        "valid_claims": len(output.claims),
        "rejected_claims": len(output.rejected_claims),
        "numeric_claims": sum(bool(item.numeric_literals) for item in output.claims),
        "grounded_numeric_claims": sum(
            bool(item.numeric_literals) for item in output.claims
        ),
        "invalid_citations": invalid_citations,
        "high_radar_events": len(high_ids),
        "high_radar_events_cited": len(high_ids & cited_ids),
        "partial_claims_with_disclosure": len(partial_claims),
        "partial_evidence_disclosure_status": "PASS",
        "cycle_assessment_status": output.cycle_assessment.status.value,
        "effective_supporting_claim_ids": list(
            output.cycle_assessment.supporting_claim_ids
        ),
        "dropped_support_claim_paths": list(
            output.cycle_assessment.dropped_support_claim_paths
        ),
        "retry_count": (
            None
            if typed.llm_run_metadata is None
            else typed.llm_run_metadata.retry_count
        ),
        "mandatory_event_coverage_matrix": typed.diagnostics.get(
            "mandatory_event_coverage_matrix",
            [],
        ),
        "future_leakage_count": _future_event_timestamp_count(research_input),
        "missing_data": list(output.missing_data),
    }


def _future_event_timestamp_count(research_input: SectorResearchInput) -> int:
    """Count Radar timestamps beyond the canonical research cutoff."""

    timestamp_fields = (
        "event_time",
        "published_at",
        "available_at",
        "ingested_at",
        "as_of",
    )
    return sum(
        timestamp > research_input.research_as_of
        for event in research_input.anomaly_events
        for field in timestamp_fields
        if isinstance((timestamp := getattr(event, field)), datetime)
    )


def _gate_summary(summaries: list[JsonObject]) -> JsonObject:
    """Separate Gateway initialization from Sector contract validation."""

    error_codes = {item.get("error_code") for item in summaries}
    gateway_failed = bool(
        error_codes.intersection({"configuration_error", "credential_not_configured"})
    )
    return {
        "gateway_initialization": "FAIL" if gateway_failed else "PASS",
        "sector_validation": (
            "NOT_REACHED"
            if gateway_failed
            else "FAIL" if "sector_research_validation" in error_codes else "PASS"
        ),
    }


def _latest_common_as_of(
    state: SectorOntologyRepository,
    macro: SectorOntologyRepository,
) -> date | None:
    dates: list[date] = []
    for sector_id in _SECTORS:
        snapshot = state.get_latest_research_snapshot(sector_id, as_of=date.max)
        macro_snapshot = macro.get_latest_macro_snapshot(sector_id, as_of=date.max)
        if snapshot is None or macro_snapshot is None:
            return None
        dates.extend((snapshot.as_of, macro_snapshot.as_of))
    return min(dates) if dates else None


if __name__ == "__main__":
    raise SystemExit(main())
