"""Claim-first Sector research synthesis over deterministic Phase 4 state."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Protocol, cast

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from src.agents.evidence import numeric_literals
from src.models.compliance import infer_claim_intent, prohibited_claim_intent
from src.models.enums import (
    AgentStatus,
    EventSeverity,
    MemoryLevel,
    SectorAnomalyStatus,
    SectorCapabilityStatus,
)
from src.models.protocols import MemoryServiceProtocol
from src.models.types import DomainModel, JsonObject
from src.schemas.agents import RejectedClaim, RoleEvidenceManifestEntry
from src.schemas.common import ErrorInfo, SourceReference
from src.schemas.llm import LLMRunMetadata
from src.schemas.memory import MemoryWriteRequest, MemoryWriteResult
from src.schemas.sector_research import (
    SectorClaimCategory,
    SectorCycleAssessment,
    SectorEvidenceKind,
    SectorResearchDraftResponse,
    SectorResearchEvidence,
    SectorResearchExecutionResult,
    SectorResearchInput,
    SectorResearchOutput,
    SectorValidatedClaim,
)
from src.schemas.sectors import CoveredSectorMetric
from src.services.llm_gateway import LLMCacheError, LLMSchemaValidationError
from src.services.llm_provider import LLMProviderError

SECTOR_RESEARCH_PROMPT_VERSION = "sector_research_prompt_v1"
SECTOR_RESEARCH_MODEL_VERSION = "sector_research_agent_v1"
SECTOR_RESEARCH_SCHEMA_VERSION = "sector_research_output_v1"
_MINIMUM_VALID_CLAIMS = 3
_CAUSAL_LANGUAGE = re.compile(
    r"\b(cause[sd]?|causing|drives?|driven by|leads? to|results? in|because of)\b",
    re.IGNORECASE,
)
_CANDIDATE_CERTAINTY = re.compile(
    r"\b(will|certain(?:ly)?|confirmed impact|guarantees?|must benefit)\b",
    re.IGNORECASE,
)
_DEGRADATION_LANGUAGE = re.compile(
    r"\b(partial|proxy|limited|insufficient|incomplete|uncertain)\b",
    re.IGNORECASE,
)


class SectorResearchPrompt(DomainModel):
    """Versioned prompt contract kept outside the Phase 3 AgentName enum."""

    name: str
    version: str
    system_prompt: str


class SectorResearchPromptLoader:
    """Load the dedicated Day35 prompt without changing the eight-Agent registry."""

    def __init__(self, prompt_root: Path) -> None:
        """Bind one explicit prompt directory."""

        self._prompt_root = prompt_root

    def load(self) -> SectorResearchPrompt:
        """Load and validate the centrally managed Sector prompt."""

        path = self._prompt_root / "sector_research_agent.yaml"
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            prompt = SectorResearchPrompt.model_validate(raw)
        except (OSError, UnicodeError, yaml.YAMLError, ValidationError):
            raise ValueError("Sector research prompt is unavailable") from None
        if prompt.name != "sector_research_agent":
            raise ValueError("Sector research prompt name is invalid")
        if prompt.version != SECTOR_RESEARCH_PROMPT_VERSION:
            raise ValueError("Sector research prompt version is unsupported")
        return prompt


class SectorResearchGateway(Protocol):
    """Narrow existing structured Gateway surface used by Day35."""

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
        """Return one schema-constrained JSON object."""


class _MetadataRun(Protocol):
    content: JsonObject
    metadata: LLMRunMetadata


class SectorResearchAgent:
    """Interpret Sector state without computing metrics or joining the eight Agents."""

    def __init__(
        self,
        gateway: SectorResearchGateway,
        prompt_loader: SectorResearchPromptLoader,
        memory: MemoryServiceProtocol | None = None,
    ) -> None:
        """Inject only public LLM, Prompt, and optional Memory write boundaries."""

        self._gateway = gateway
        self._prompt_loader = prompt_loader
        self._memory = memory

    def run(
        self,
        *,
        run_id: str,
        model_name: str,
        research_input: SectorResearchInput,
    ) -> SectorResearchExecutionResult:
        """Produce validated Sector Claims from compact direct-upstream Evidence."""

        prompt = self._prompt_loader.load()
        evidence = build_sector_research_evidence(research_input)
        payload = _compact_prompt_payload(research_input, evidence)
        metadata: LLMRunMetadata | None = None
        try:
            raw, metadata = _invoke_gateway(
                self._gateway,
                model_name=model_name,
                prompt=prompt,
                payload=payload,
            )
            draft = SectorResearchDraftResponse.model_validate(raw)
            output = _promote_output(
                research_input=research_input,
                evidence=evidence,
                draft=draft,
                model_name=model_name,
                prompt_version=prompt.version,
            )
            memory_results = self._persist_memory(output)
            return SectorResearchExecutionResult(
                run_id=run_id,
                status=AgentStatus.OK,
                output=output,
                llm_run_metadata=metadata,
                diagnostics={
                    "valid_claims": len(output.claims),
                    "rejected_claims": len(output.rejected_claims),
                    "numeric_claims": sum(
                        bool(item.numeric_literals) for item in output.claims
                    ),
                    "memory_writes": len(memory_results),
                },
            )
        except LLMCacheError:
            return SectorResearchExecutionResult(
                run_id=run_id,
                status=AgentStatus.ERROR,
                error=ErrorInfo(
                    code="cache_error",
                    message="LLM cache failed during Sector research.",
                    retryable=True,
                ),
                llm_run_metadata=metadata,
            )
        except LLMProviderError as exc:
            details: JsonObject | None = None
            if isinstance(exc, LLMSchemaValidationError):
                details = {
                    "schema_name": exc.schema_name,
                    "schema_version": exc.schema_version,
                    "validation_errors": [
                        {"path": path, "error_type": error_type}
                        for path, error_type in exc.validation_errors
                    ],
                }
            return SectorResearchExecutionResult(
                run_id=run_id,
                status=AgentStatus.ERROR,
                error=ErrorInfo(
                    code=exc.code,
                    message="LLM provider request failed during Sector research.",
                    retryable=exc.code in {"connection", "rate_limit", "remote_error"},
                    details=details,
                ),
                llm_run_metadata=metadata,
            )
        except (ValidationError, ValueError) as exc:
            return SectorResearchExecutionResult(
                run_id=run_id,
                status=AgentStatus.ERROR,
                error=ErrorInfo(
                    code="sector_research_validation",
                    message=str(exc),
                    retryable=False,
                ),
                llm_run_metadata=metadata,
            )

    def _persist_memory(
        self,
        output: SectorResearchOutput,
    ) -> tuple[MemoryWriteResult, ...]:
        """Persist selected accepted Claims, never an undifferentiated narrative."""

        if self._memory is None:
            return ()
        evidence = {item.entry.evidence_id: item for item in output.evidence_manifest}
        results: list[MemoryWriteResult] = []
        for claim in output.claims:
            if claim.category not in {
                SectorClaimCategory.CATALYSTS,
                SectorClaimCategory.RISKS,
                SectorClaimCategory.CYCLE,
                SectorClaimCategory.ANOMALIES,
                SectorClaimCategory.INDUSTRY_CHAINS,
            }:
                continue
            bound = [evidence[item] for item in claim.evidence_ids]
            chain_ids = tuple(
                dict.fromkeys(chain for item in bound for chain in item.chain_ids)
            )
            source_event_ids = tuple(
                dict.fromkeys(
                    event_id for item in bound for event_id in item.source_event_ids
                )
            )
            namespaces: tuple[str, ...] = (output.sector_scope_id,)
            if chain_ids:
                namespaces = (*namespaces, *(f"CHAIN:{item}" for item in chain_ids))
            source = bound[0].entry.source
            for namespace in dict.fromkeys(namespaces):
                results.append(
                    self._memory.write(
                        MemoryWriteRequest(
                            memory_level=MemoryLevel.L3,
                            namespace_key=namespace,
                            effective_ts=output.research_as_of,
                            summary_text=_memory_summary(
                                output=output,
                                claim=claim,
                                chain_ids=chain_ids,
                                source_event_ids=source_event_ids,
                            ),
                            memory_type=f"sector_research_{claim.category.value}",
                            importance_score=claim.confidence or 0.5,
                            source_ref_json=SourceReference(
                                document_id=source.document_id or claim.evidence_ids[0],
                                excerpt_ref=claim.claim_id,
                                provider=(
                                    f"sector_research_agent:{output.model_version}:"
                                    f"{output.prompt_version}"
                                ),
                            ),
                            created_by=SECTOR_RESEARCH_MODEL_VERSION,
                        )
                    )
                )
        return tuple(results)


def build_sector_research_evidence(
    research_input: SectorResearchInput,
) -> tuple[SectorResearchEvidence, ...]:
    """Project Phase 4 objects into compact, exact-literal Evidence entries."""

    values: list[SectorResearchEvidence] = []
    snapshot = research_input.sector_snapshot
    as_of = research_input.research_as_of
    for kind, prefix, state in (
        (SectorEvidenceKind.MARKET_STATE, "market", snapshot.market_state),
        (SectorEvidenceKind.BREADTH_STATE, "breadth", snapshot.breadth_state),
        (
            SectorEvidenceKind.FUNDAMENTAL_STATE,
            "fundamental",
            snapshot.fundamental_state,
        ),
        (SectorEvidenceKind.VALUATION_STATE, "valuation", snapshot.valuation_state),
    ):
        for field_name in type(state).model_fields:
            metric = cast(CoveredSectorMetric, getattr(state, field_name))
            evidence_id = f"{snapshot.snapshot_id}:{prefix}:{field_name}"
            description = _metric_description(field_name, metric)
            values.append(
                _evidence(
                    evidence_id=evidence_id,
                    kind=kind,
                    provider="sector_state_operator",
                    document_id=snapshot.snapshot_id,
                    as_of=as_of,
                    description=description,
                    status=metric.status,
                    requires_degradation=(
                        metric.status is not SectorCapabilityStatus.AVAILABLE
                    ),
                )
            )

    mapping = research_input.benchmark_mapping
    mapping_status = (
        SectorCapabilityStatus.MISSING if mapping is None else mapping.status
    )
    benchmark_ids = (
        () if mapping is None else tuple(str(item) for item in mapping.benchmark_ids)
    )
    values.append(
        _evidence(
            evidence_id=f"{research_input.universe_snapshot.snapshot_id}:coverage",
            kind=SectorEvidenceKind.COVERAGE,
            provider="sector_universe_service",
            document_id=research_input.universe_snapshot.snapshot_id,
            as_of=as_of,
            description=(
                f"Sector universe status={snapshot.status.value}; "
                f"constituents={snapshot.coverage.universe_count}; "
                f"market_coverage={snapshot.coverage.market_coverage_count}; "
                f"fundamental_coverage={snapshot.coverage.fundamental_coverage_count}; "
                f"benchmark_status={mapping_status.value}; "
                f"benchmark_ids={','.join(benchmark_ids) or 'none'}"
            ),
            status=snapshot.status,
            requires_degradation=(
                snapshot.status is not SectorCapabilityStatus.AVAILABLE
                or mapping_status is not SectorCapabilityStatus.AVAILABLE
            ),
        )
    )

    macro = research_input.macro_snapshot
    for dimension_name in (
        "rates",
        "inflation",
        "labor",
        "growth",
        "financial_stress",
    ):
        dimension = getattr(macro.cycle_state, dimension_name)
        for signal in dimension.signals:
            evidence_id = (
                f"{macro.snapshot_id}:macro:{dimension_name}:{signal.series_id}"
            )
            values.append(
                _evidence(
                    evidence_id=evidence_id,
                    kind=SectorEvidenceKind.MACRO_STATE,
                    provider="sector_macro_operator",
                    document_id=macro.snapshot_id,
                    as_of=as_of,
                    description=(
                        f"{dimension_name} series={signal.series_id}; "
                        f"direction={signal.direction.value}; "
                        f"latest_value={signal.latest_value}; "
                        f"change_3m={signal.change_3m}; "
                        f"change_12m={signal.change_12m}; "
                        f"status={dimension.status.value}"
                    ),
                    status=dimension.status,
                    requires_degradation=(
                        dimension.status is not SectorCapabilityStatus.AVAILABLE
                    ),
                )
            )
    for estimate in macro.macro_sensitivity.estimates:
        evidence_id = f"{macro.snapshot_id}:sensitivity:{estimate.series_id}"
        values.append(
            _evidence(
                evidence_id=evidence_id,
                kind=SectorEvidenceKind.MACRO_SENSITIVITY,
                provider="sector_macro_operator",
                document_id=macro.snapshot_id,
                as_of=as_of,
                description=(
                    f"Historical association series={estimate.series_id}; "
                    f"beta={estimate.beta}; correlation={estimate.correlation}; "
                    f"observations={estimate.observation_count}; "
                    f"required={estimate.required_count}; "
                    f"status={estimate.status.value}"
                ),
                status=estimate.status,
                association_only=True,
                requires_degradation=(
                    estimate.status is not SectorCapabilityStatus.AVAILABLE
                ),
            )
        )

    for event in research_input.anomaly_events:
        evidence_id = f"event:{event.event_id}"
        candidate = event.status is SectorAnomalyStatus.PROPAGATION_CANDIDATE
        description = (
            f"Radar event type={event.event_type.value}; "
            f"severity={event.severity.value}; "
            f"direction={event.direction.value}; status={event.status.value}; "
            f"confidence={event.confidence}; summary={event.summary}"
        )
        if event.propagation_hypothesis:
            description += f"; candidate_hypothesis={event.propagation_hypothesis}"
        values.append(
            _evidence(
                evidence_id=evidence_id,
                kind=SectorEvidenceKind.ANOMALY_EVENT,
                provider="sector_anomaly_radar",
                document_id=event.event_id,
                as_of=event.available_at,
                description=description,
                chain_ids=event.chain_ids,
                source_event_ids=(event.event_id,),
                candidate_only=candidate,
                requires_degradation=candidate,
            )
        )

    for chain in research_input.industry_chains:
        values.append(
            _evidence(
                evidence_id=f"chain:{chain.chain_id}:{chain.version}",
                kind=SectorEvidenceKind.INDUSTRY_CHAIN,
                provider="sector_ontology",
                document_id=chain.chain_id,
                as_of=as_of,
                description=(
                    f"Industry Chain {chain.chain_id} name={chain.name}; "
                    f"status={chain.status.value}; description={chain.description}"
                ),
                chain_ids=(chain.chain_id,),
            )
        )
    for membership in research_input.memberships:
        values.append(
            _evidence(
                evidence_id=(
                    f"membership:{membership.asset_id}:{membership.sector_id.value}:"
                    f"{membership.version}"
                ),
                kind=SectorEvidenceKind.MEMBERSHIP,
                provider=membership.source,
                document_id=str(membership.asset_id),
                as_of=as_of,
                description=(
                    f"Asset {membership.asset_id} has role={membership.role.value}; "
                    f"chain_ids={','.join(membership.chain_ids) or 'none'}"
                ),
                chain_ids=membership.chain_ids,
            )
        )
    node_ids = {node.node_id for node in research_input.graph_nodes}
    for edge in research_input.graph_edges:
        if edge.source_node_id not in node_ids or edge.target_node_id not in node_ids:
            continue
        values.append(
            _evidence(
                evidence_id=f"edge:{edge.edge_id}:{edge.version}",
                kind=SectorEvidenceKind.GRAPH_RELATION,
                provider=edge.source,
                document_id=edge.edge_id,
                as_of=as_of,
                description=(
                    f"Graph relation {edge.source_node_id} {edge.edge_type.value} "
                    f"{edge.target_node_id}; confidence={edge.confidence}"
                ),
            )
        )

    for section in type(research_input.memory_context).model_fields:
        if section in {"schema_version", "retrieval_metadata", "missing_context"}:
            continue
        items = getattr(research_input.memory_context, section)
        if not isinstance(items, list):
            continue
        for item in items:
            values.append(
                SectorResearchEvidence(
                    entry=RoleEvidenceManifestEntry(
                        evidence_id=item.memory_id,
                        evidence_type="memory",
                        source=item.source,
                        as_of=item.effective_ts,
                        short_description=item.summary_text,
                        numeric_tokens=numeric_literals(item.summary_text),
                    ),
                    kind=SectorEvidenceKind.MEMORY,
                    chain_ids=(
                        (item.namespace_key.removeprefix("CHAIN:"),)
                        if item.namespace_key.startswith("CHAIN:")
                        else ()
                    ),
                )
            )
    unique = {item.entry.evidence_id: item for item in values}
    if len(unique) != len(values):
        raise ValueError("Sector Evidence IDs are not unique")
    return tuple(unique[key] for key in sorted(unique))


def _promote_output(
    *,
    research_input: SectorResearchInput,
    evidence: tuple[SectorResearchEvidence, ...],
    draft: SectorResearchDraftResponse,
    model_name: str,
    prompt_version: str,
) -> SectorResearchOutput:
    evidence_index = {item.entry.evidence_id: item for item in evidence}
    accepted: list[SectorValidatedClaim] = []
    rejected: list[RejectedClaim] = []
    path_to_id: dict[str, str] = {}
    for item in draft.claims:
        rejection = _claim_rejection(item.model_dump(mode="json"), evidence_index)
        if rejection is not None:
            rejected.append(rejection)
            continue
        claim_id = f"sector:{research_input.sector_id.value}:claim:{len(accepted)}"
        source_references = tuple(
            evidence_index[evidence_id].entry.source
            for evidence_id in item.evidence_ids
        )
        claim = SectorValidatedClaim(
            claim_id=claim_id,
            claim_path=f"claims[{len(accepted)}]",
            claim_text=item.claim_text,
            category=item.category,
            numeric_literals=numeric_literals(item.claim_text),
            evidence_ids=item.evidence_ids,
            source_references=source_references,
            derivation_type="direct_evidence",
            claim_type=(
                "factual"
                if item.category
                in {
                    SectorClaimCategory.TREND,
                    SectorClaimCategory.BREADTH,
                    SectorClaimCategory.FUNDAMENTALS,
                    SectorClaimCategory.VALUATION,
                    SectorClaimCategory.ANOMALIES,
                    SectorClaimCategory.LEADERS_LAGGARDS,
                }
                else "analytical"
            ),
            claim_intent=infer_claim_intent(item.claim_text, analytical=True),
            confidence=item.confidence,
        )
        accepted.append(claim)
        path_to_id[item.claim_path] = claim_id
    if len(accepted) < _MINIMUM_VALID_CLAIMS:
        raise ValueError(
            f"Sector research retained {len(accepted)} valid Claims; "
            f"minimum is {_MINIMUM_VALID_CLAIMS}"
        )
    _validate_required_event_coverage(research_input, accepted)
    supporting_ids = tuple(
        path_to_id[path]
        for path in draft.cycle_assessment.supporting_claim_paths
        if path in path_to_id
    )
    if not supporting_ids:
        raise ValueError("Sector cycle has no accepted supporting Claim")
    missing_data = _missing_data(research_input)
    uncertainties = tuple(dict.fromkeys((*draft.uncertainties, *missing_data)))
    if _input_requires_degradation(evidence) and not uncertainties:
        raise ValueError("PARTIAL or MISSING Sector input requires uncertainty")
    return SectorResearchOutput(
        sector_id=research_input.sector_id,
        sector_scope_id=research_input.sector_scope_id,
        research_as_of=research_input.research_as_of,
        claims=tuple(accepted),
        cycle_assessment=SectorCycleAssessment(
            phase=draft.cycle_assessment.phase,
            confidence=draft.cycle_assessment.confidence,
            supporting_claim_ids=tuple(dict.fromkeys(supporting_ids)),
            uncertainty=draft.cycle_assessment.uncertainty,
        ),
        uncertainties=uncertainties,
        missing_data=missing_data,
        rejected_claims=tuple(rejected),
        evidence_manifest=evidence,
        model_version=model_name,
        prompt_version=prompt_version,
    )


def _claim_rejection(
    raw: JsonObject,
    evidence: dict[str, SectorResearchEvidence],
) -> RejectedClaim | None:
    text = raw.get("claim_text")
    path = raw.get("claim_path")
    ids = raw.get("evidence_ids")
    claim_text = text if isinstance(text, str) and text else "<invalid claim>"
    claim_path = path if isinstance(path, str) and path else "<unknown>"
    evidence_ids = (
        tuple(item for item in ids if isinstance(item, str))
        if isinstance(ids, list)
        else ()
    )

    def rejected(reason: str) -> RejectedClaim:
        return RejectedClaim(
            claim_path=claim_path,
            claim_text=claim_text,
            reason=reason,
            evidence_ids=evidence_ids,
            numeric_literals=numeric_literals(claim_text),
        )

    if not evidence_ids:
        return rejected("missing_direct_upstream_evidence")
    if any(item not in evidence for item in evidence_ids):
        return rejected("unknown_direct_upstream_evidence")
    if prohibited_claim_intent(claim_text) is not None:
        return rejected("prohibited_claim_intent")
    bound = [evidence[item] for item in evidence_ids]
    for literal in numeric_literals(claim_text):
        if not any(literal in item.entry.numeric_tokens for item in bound):
            return rejected(f"numeric_literal_not_grounded:{literal}")
    if any(item.association_only for item in bound) and _CAUSAL_LANGUAGE.search(
        claim_text
    ):
        return rejected("historical_association_misstated_as_causality")
    if any(item.candidate_only for item in bound) and _CANDIDATE_CERTAINTY.search(
        claim_text
    ):
        return rejected("propagation_candidate_misstated_as_fact")
    if any(
        item.requires_degradation for item in bound
    ) and not _DEGRADATION_LANGUAGE.search(claim_text):
        return rejected("partial_or_candidate_evidence_not_disclosed")
    category = raw.get("category")
    if category == SectorClaimCategory.CATALYSTS.value and not any(
        item.kind is SectorEvidenceKind.ANOMALY_EVENT for item in bound
    ):
        return rejected("catalyst_requires_upstream_event")
    return None


def _validate_required_event_coverage(
    research_input: SectorResearchInput,
    claims: list[SectorValidatedClaim],
) -> None:
    high_ids = {
        f"event:{event.event_id}"
        for event in research_input.anomaly_events
        if event.severity in {EventSeverity.HIGH, EventSeverity.CRITICAL}
    }
    cited = {item for claim in claims for item in claim.evidence_ids}
    missing = high_ids - cited
    if missing:
        raise ValueError("HIGH Sector Radar event was omitted from accepted Claims")


def _compact_prompt_payload(
    research_input: SectorResearchInput,
    evidence: tuple[SectorResearchEvidence, ...],
) -> JsonObject:
    return {
        "sector_id": research_input.sector_id.value,
        "sector_name": research_input.sector_name,
        "research_as_of": research_input.research_as_of.isoformat(),
        "evidence_manifest": [
            {
                "evidence_id": item.entry.evidence_id,
                "kind": item.kind.value,
                "description": item.entry.short_description,
                "numeric_tokens": list(item.entry.numeric_tokens),
                "status": None if item.status is None else item.status.value,
                "chain_ids": list(item.chain_ids),
                "association_only": item.association_only,
                "candidate_only": item.candidate_only,
                "requires_degradation": item.requires_degradation,
            }
            for item in evidence
        ],
        "required_categories": [item.value for item in SectorClaimCategory],
        "available_anomaly_count": len(research_input.anomaly_events),
    }


def _invoke_gateway(
    gateway: SectorResearchGateway,
    *,
    model_name: str,
    prompt: SectorResearchPrompt,
    payload: JsonObject,
) -> tuple[JsonObject, LLMRunMetadata | None]:
    metadata_call = getattr(gateway, "invoke_json_with_metadata", None)
    if callable(metadata_call):
        result = cast(
            _MetadataRun,
            metadata_call(
                model_name,
                prompt.system_prompt,
                payload,
                prompt_version=prompt.version,
                schema_version=SECTOR_RESEARCH_SCHEMA_VERSION,
                response_model=SectorResearchDraftResponse,
            ),
        )
        return result.content, result.metadata
    return (
        gateway.invoke_json(
            model_name,
            prompt.system_prompt,
            payload,
            prompt_version=prompt.version,
            schema_version=SECTOR_RESEARCH_SCHEMA_VERSION,
            response_model=SectorResearchDraftResponse,
        ),
        None,
    )


def _evidence(
    *,
    evidence_id: str,
    kind: SectorEvidenceKind,
    provider: str,
    document_id: str,
    as_of: datetime,
    description: str,
    status: SectorCapabilityStatus | None = None,
    chain_ids: tuple[str, ...] = (),
    source_event_ids: tuple[str, ...] = (),
    association_only: bool = False,
    candidate_only: bool = False,
    requires_degradation: bool = False,
) -> SectorResearchEvidence:
    return SectorResearchEvidence(
        entry=RoleEvidenceManifestEntry(
            evidence_id=evidence_id,
            evidence_type="structured_direct",
            source=SourceReference(
                document_id=document_id,
                excerpt_ref=evidence_id,
                provider=provider,
            ),
            as_of=as_of,
            short_description=description,
            numeric_tokens=numeric_literals(description),
        ),
        kind=kind,
        status=status,
        chain_ids=chain_ids,
        source_event_ids=source_event_ids,
        association_only=association_only,
        candidate_only=candidate_only,
        requires_degradation=requires_degradation,
    )


def _metric_description(name: str, metric: CoveredSectorMetric) -> str:
    return (
        f"{name}: value={metric.value}; status={metric.status.value}; "
        f"coverage={metric.coverage_count}/{metric.universe_count}"
    )


def _missing_data(research_input: SectorResearchInput) -> tuple[str, ...]:
    values: list[str] = []
    snapshot = research_input.sector_snapshot
    for group_name, state in (
        ("market", snapshot.market_state),
        ("breadth", snapshot.breadth_state),
        ("fundamental", snapshot.fundamental_state),
        ("valuation", snapshot.valuation_state),
    ):
        for field_name in type(state).model_fields:
            metric = cast(CoveredSectorMetric, getattr(state, field_name))
            if metric.status is not SectorCapabilityStatus.AVAILABLE:
                values.append(f"{group_name}.{field_name}:{metric.status.value}")
    if research_input.benchmark_mapping is None:
        values.append("benchmark_mapping:missing")
    elif (
        research_input.benchmark_mapping.status is not SectorCapabilityStatus.AVAILABLE
    ):
        values.append(
            f"benchmark_mapping:{research_input.benchmark_mapping.status.value}"
        )
    if not research_input.anomaly_events:
        values.append("radar_events:none_detected")
    if research_input.memory_context.retrieval_metadata.no_relevant_memory:
        values.append("sector_memory:no_relevant_memory")
    return tuple(values)


def _input_requires_degradation(
    evidence: Iterable[SectorResearchEvidence],
) -> bool:
    return any(item.requires_degradation for item in evidence)


def _memory_summary(
    *,
    output: SectorResearchOutput,
    claim: SectorValidatedClaim,
    chain_ids: tuple[str, ...],
    source_event_ids: tuple[str, ...],
) -> str:
    metadata = {
        "sector_id": output.sector_id.value,
        "chain_ids": list(chain_ids),
        "as_of": output.research_as_of.isoformat(),
        "source_claim_ids": [claim.claim_id],
        "source_event_ids": list(source_event_ids),
        "model_version": output.model_version,
        "prompt_version": output.prompt_version,
    }
    return f"{json.dumps(metadata, sort_keys=True)}\n{claim.claim_text}"
