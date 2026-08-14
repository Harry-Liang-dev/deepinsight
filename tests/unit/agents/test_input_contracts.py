"""Offline tests for the versioned eight-Agent input contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from src.agents.coordinator import _context_for_contract
from src.agents.input_contracts import (
    AGENT_INPUT_MATRIX,
    AGENT_INPUT_SCHEMA_VERSION,
    AGENT_OUTPUT_SCHEMA_VERSION,
    AgentInputProjectionError,
    AgentInputProjector,
    BearManagerInputV1,
    BullManagerInputV1,
    ResearchManagerInputV1,
    RiskManagerInputV1,
    VersionedUpstreamOutputV1,
)
from src.memory.contracts import (
    ResearchContextBundle,
    ResearchContextMemory,
    ResearchContextSection,
    RetrievalMetadata,
    RetrievalStatus,
)
from src.models.enums import (
    AgentName,
    AgentStatus,
    Market,
    MarketScope,
    MemoryLevel,
    ReportMarketScope,
)
from src.models.identifiers import AssetId
from src.schemas.agents import AgentContext
from src.schemas.common import SourceReference
from src.schemas.documents import RetrievedDocument
from src.schemas.research_data import (
    DataAvailabilityStatus,
    DataCapability,
    DataFreshness,
    DataQuality,
    DataQualityStatus,
    DataSourceReference,
    FreshnessStatus,
    MissingData,
    MissingDataReason,
    ResearchDataBundle,
    ResearchDataSection,
    ResearchEvidenceItem,
)

AS_OF = datetime(2026, 8, 7, 20, 0, tzinfo=UTC)
ASSET = AssetId("US:AAPL")


def _data_bundle() -> ResearchDataBundle:
    sections = {
        capability.value: _present_section(capability, index)
        for index, capability in enumerate(DataCapability, start=1)
    }
    return ResearchDataBundle.model_validate(
        {
            "bundle_id": f"rdb_{1:024x}",
            "input_fingerprint": f"{1:064x}",
            "asset_id": ASSET,
            "as_of": AS_OF,
            "window_start": date(2026, 5, 8),
            "window_end": date(2026, 8, 7),
            "dataset_version": "agent-contract-fixture-v1",
            "snapshot_id": "data-snapshot-v1",
            **sections,
        }
    )


def _present_section(
    capability: DataCapability,
    index: int,
) -> ResearchDataSection:
    evidence = ResearchEvidenceItem(
        evidence_id=f"ev_{index:024x}",
        subject_id=str(ASSET),
        field_path=f"{capability.value}.fixture_value",
        effective_at=AS_OF - timedelta(days=1),
        observed_at=AS_OF - timedelta(hours=1),
        value=index,
        unit="fixture_unit",
        source=DataSourceReference(
            provider_name="fixture_provider",
            normalized_record_type=capability.value,
            normalized_record_key=f"fixture-{index}",
            provider_locator=f"fixture://{capability.value}/{index}",
        ),
        content_hash=f"{index:064x}",
    )
    return ResearchDataSection(
        capability=capability,
        status=DataAvailabilityStatus.PRESENT,
        as_of=AS_OF,
        freshness=DataFreshness(
            status=FreshnessStatus.FRESH,
            evaluated_at=AS_OF,
            policy_name="fixture",
            policy_version="v1",
            latest_effective_at=evidence.effective_at,
            age_days=1,
            maximum_age_days=2,
        ),
        quality=DataQuality(
            status=DataQualityStatus.PASS,
            observation_count=1,
            source_count=1,
            completeness_ratio=1.0,
            validity_ratio=1.0,
            lineage_coverage_ratio=1.0,
            temporal_coverage_ratio=1.0,
        ),
        requested_field_count=1,
        available_field_count=1,
        items=(evidence,),
    )


def _missing_section(capability: DataCapability) -> ResearchDataSection:
    missing = MissingData(
        capability=capability,
        field_path=f"{capability.value}.sample",
        status=DataAvailabilityStatus.MISSING,
        reason_code=MissingDataReason.NO_OBSERVATION,
        reason="No attributable fixture sample was supplied.",
        required=True,
        as_of=AS_OF,
        providers_checked=("fixture_provider",),
        impact="The role cannot characterize this evidence channel.",
    )
    return ResearchDataSection(
        capability=capability,
        status=DataAvailabilityStatus.MISSING,
        as_of=AS_OF,
        freshness=DataFreshness(
            status=FreshnessStatus.UNKNOWN,
            evaluated_at=AS_OF,
            policy_name="fixture",
            policy_version="v1",
            reason="No observation was available.",
        ),
        quality=DataQuality(
            status=DataQualityStatus.UNKNOWN,
            observation_count=0,
            source_count=0,
            reason="No observation was available.",
        ),
        requested_field_count=1,
        available_field_count=0,
        missing_data=(missing,),
    )


def _memory_bundle() -> ResearchContextBundle:
    levels = {
        ResearchContextSection.CURRENT_SNAPSHOT: MemoryLevel.L0,
        ResearchContextSection.MACRO_EVENTS: MemoryLevel.L1,
        ResearchContextSection.ASSET_EVENTS: MemoryLevel.L2,
        ResearchContextSection.PRIOR_RESEARCH: MemoryLevel.L3,
        ResearchContextSection.PRIOR_RISK: MemoryLevel.L3,
        ResearchContextSection.HISTORICAL_ANALOGS: MemoryLevel.L4,
        ResearchContextSection.REGIME_CONTEXT: MemoryLevel.L4,
    }
    items = {
        section: ResearchContextMemory(
            memory_id=f"memory-{section.value}",
            section=section,
            memory_level=level,
            namespace_key="ASSET:US:AAPL",
            asset_id=ASSET,
            market=MarketScope.US,
            memory_type=section.value,
            summary_text=f"Attributable {section.value} fixture.",
            effective_ts=AS_OF - timedelta(days=1),
            importance_score=0.8,
            retrieval_score=0.9,
            retrieval_reason="fixture semantic relevance",
            source=SourceReference(
                document_id=f"document-{section.value}",
                excerpt_ref="chunk-1",
            ),
            created_by="fixture",
        )
        for section, level in levels.items()
    }
    metadata = RetrievalMetadata(
        query_id="query-agent-contract-v1",
        query_text="fixed Agent contract fixture",
        as_of=AS_OF,
        market=Market.US,
        asset_id=ASSET,
        namespace_keys=["ASSET:US:AAPL"],
        requested_levels=list(MemoryLevel),
        min_importance_score=0.0,
        top_k_per_section=4,
        snapshot_id="memory-snapshot-v1",
        candidate_count=len(items),
        eligible_count=len(items),
        result_count=len(items),
        excluded_future_count=0,
        excluded_namespace_count=0,
        excluded_asset_count=0,
        excluded_market_count=0,
        excluded_importance_count=0,
        excluded_expired_count=0,
        excluded_current_report_count=0,
        section_counts={section: 1 for section in ResearchContextSection},
        status=RetrievalStatus.COMPLETE,
        no_relevant_memory=False,
    )
    return ResearchContextBundle(
        current_snapshot=[items[ResearchContextSection.CURRENT_SNAPSHOT]],
        macro_events=[items[ResearchContextSection.MACRO_EVENTS]],
        asset_events=[items[ResearchContextSection.ASSET_EVENTS]],
        prior_research=[items[ResearchContextSection.PRIOR_RESEARCH]],
        prior_risk=[items[ResearchContextSection.PRIOR_RISK]],
        historical_analogs=[items[ResearchContextSection.HISTORICAL_ANALOGS]],
        regime_context=[items[ResearchContextSection.REGIME_CONTEXT]],
        retrieval_metadata=metadata,
        missing_context=[],
    )


def _analyst_outputs(
    *,
    missing: AgentName | None = None,
) -> tuple[VersionedUpstreamOutputV1, ...]:
    roles = (
        AgentName.FUNDAMENTAL_ANALYST,
        AgentName.TECHNICAL_TEXT_ANALYST,
        AgentName.SENTIMENT_ANALYST,
        AgentName.NEWS_EVENT_ANALYST,
    )
    return tuple(
        VersionedUpstreamOutputV1(
            agent_name=role,
            status=AgentStatus.ERROR if role is missing else AgentStatus.OK,
            output=None if role is missing else {"analysis": {"facts": []}},
            evidence_ids=() if role is missing else (f"evidence-{role.value}",),
            uncertainties=("Role unavailable.",) if role is missing else (),
            error_code="schema_validation" if role is missing else None,
        )
        for role in roles
    )


def _success(role: AgentName) -> VersionedUpstreamOutputV1:
    return VersionedUpstreamOutputV1(
        agent_name=role,
        status=AgentStatus.OK,
        output={"role": role.value},
        evidence_ids=("ev-upstream",),
    )


def _analyst_outputs_with_evidence(
    evidence_id: str,
) -> tuple[VersionedUpstreamOutputV1, ...]:
    roles = (
        AgentName.FUNDAMENTAL_ANALYST,
        AgentName.TECHNICAL_TEXT_ANALYST,
        AgentName.SENTIMENT_ANALYST,
        AgentName.NEWS_EVENT_ANALYST,
    )
    return tuple(
        VersionedUpstreamOutputV1(
            agent_name=role,
            status=(
                AgentStatus.OK
                if role is AgentName.FUNDAMENTAL_ANALYST
                else AgentStatus.ERROR
            ),
            output=(
                {"analysis": {"facts": ["Validated upstream fact."]}}
                if role is AgentName.FUNDAMENTAL_ANALYST
                else None
            ),
            evidence_ids=(
                (evidence_id,) if role is AgentName.FUNDAMENTAL_ANALYST else ()
            ),
            error_code=(
                None if role is AgentName.FUNDAMENTAL_ANALYST else "evidence_validation"
            ),
        )
        for role in roles
    )


def test_input_matrix_contains_exactly_the_fixed_eight_roles() -> None:
    """The contract matrix cannot silently add, remove, or duplicate an Agent."""

    assert len(AGENT_INPUT_MATRIX) == 8
    assert {item.agent for item in AGENT_INPUT_MATRIX} == set(AgentName)


def test_structured_evidence_has_one_canonical_citation_mapping() -> None:
    """Data lineage should map to the existing report citation identity."""

    evidence = _present_section(DataCapability.FUNDAMENTALS, 41).items[0]

    citation = evidence.to_source_reference()

    assert citation.document_id == "fixture-41"
    assert citation.excerpt_ref == evidence.evidence_id
    assert citation.provider == "fixture_provider"
    risk = next(
        item for item in AGENT_INPUT_MATRIX if item.agent is AgentName.RISK_MANAGER
    )
    assert AgentName.RESEARCH_MANAGER in risk.required_upstream_outputs
    assert AgentName.BULL_MANAGER in risk.required_upstream_outputs
    assert AgentName.BEAR_MANAGER in risk.required_upstream_outputs


def test_agent_projection_bounds_history_without_mutating_canonical_bundle() -> None:
    """Long histories stay in Data while Agent input remains field-balanced."""

    base = _present_section(DataCapability.MACRO_INDICATORS, 91)
    items = tuple(
        ResearchEvidenceItem(
            evidence_id=f"ev_{index + 1000:024x}",
            subject_id="US",
            field_path=f"macro_indicators.series_{index % 12:02d}",
            effective_at=AS_OF - timedelta(hours=index + 1),
            observed_at=AS_OF - timedelta(minutes=index + 1),
            value=index,
            unit="fixture_unit",
            source=DataSourceReference(
                provider_name="fixture_provider",
                normalized_record_type="MacroObservationRecord",
                normalized_record_key=f"macro-{index}",
                provider_locator=f"fixture://macro/{index}",
            ),
            content_hash=f"{index + 1000:064x}",
        )
        for index in range(120)
    )
    macro = base.model_copy(
        update={
            "items": items,
            "requested_field_count": 12,
            "available_field_count": 12,
        }
    )
    bundle = _data_bundle().model_copy(update={"macro_indicators": macro})

    projected = AgentInputProjector.analyst(
        bundle,
        _memory_bundle(),
        AgentName.FUNDAMENTAL_ANALYST,
    )
    projected_items = projected.data.section(DataCapability.MACRO_INDICATORS).items

    assert len(bundle.macro_indicators.items) == 120
    assert len(projected_items) == 36
    assert {item.field_path for item in projected_items} == {
        f"macro_indicators.series_{index:02d}" for index in range(12)
    }
    for field_path in {item.field_path for item in projected_items}:
        expected_latest = max(
            item.effective_at for item in items if item.field_path == field_path
        )
        assert any(
            item.field_path == field_path and item.effective_at == expected_latest
            for item in projected_items
        )


def test_role_context_projects_only_documents_owned_by_that_role() -> None:
    """Analysts cannot re-read unrelated documents outside their Data contract."""

    bundle = _data_bundle()
    filing_key = bundle.filings.items[0].source.normalized_record_key
    news_key = bundle.news_evidence.items[0].source.normalized_record_key
    context = AgentContext(
        report_date=AS_OF.date(),
        market_scope=ReportMarketScope.US,
        asset_id=ASSET,
        structured_features={"fixture": True},
        retrieved_documents=[
            RetrievedDocument(
                document_id=filing_key,
                chunk_id="filing-chunk",
                title="Filing",
                chunk_text="Attributable filing text.",
            ),
            RetrievedDocument(
                document_id=f"news-{news_key}",
                chunk_id="news-chunk",
                title="News",
                chunk_text="Attributable news text.",
            ),
        ],
    )
    fundamental = AgentInputProjector.analyst(
        bundle, _memory_bundle(), AgentName.FUNDAMENTAL_ANALYST
    )
    technical = AgentInputProjector.analyst(
        bundle, _memory_bundle(), AgentName.TECHNICAL_TEXT_ANALYST
    )
    news = AgentInputProjector.analyst(
        bundle, _memory_bundle(), AgentName.NEWS_EVENT_ANALYST
    )

    assert [
        item.document_id
        for item in _context_for_contract(context, fundamental).retrieved_documents
    ] == [filing_key]
    assert not _context_for_contract(context, technical).retrieved_documents
    assert {
        item.document_id
        for item in _context_for_contract(context, news).retrieved_documents
    } == {filing_key, f"news-{news_key}"}


@pytest.mark.parametrize(
    ("role", "visible", "hidden", "memory_visible", "memory_hidden"),
    [
        (
            AgentName.FUNDAMENTAL_ANALYST,
            DataCapability.FUNDAMENTALS,
            DataCapability.OHLCV,
            ResearchContextSection.PRIOR_RESEARCH,
            ResearchContextSection.REGIME_CONTEXT,
        ),
        (
            AgentName.TECHNICAL_TEXT_ANALYST,
            DataCapability.TECHNICAL_FEATURES,
            DataCapability.FUNDAMENTALS,
            ResearchContextSection.REGIME_CONTEXT,
            ResearchContextSection.PRIOR_RESEARCH,
        ),
        (
            AgentName.SENTIMENT_ANALYST,
            DataCapability.SENTIMENT_EVIDENCE,
            DataCapability.FUNDAMENTALS,
            ResearchContextSection.MACRO_EVENTS,
            ResearchContextSection.PRIOR_RISK,
        ),
        (
            AgentName.NEWS_EVENT_ANALYST,
            DataCapability.CORPORATE_EVENTS,
            DataCapability.TECHNICAL_FEATURES,
            ResearchContextSection.ASSET_EVENTS,
            ResearchContextSection.HISTORICAL_ANALOGS,
        ),
    ],
)
def test_analyst_projection_is_versioned_and_least_privilege(
    role: AgentName,
    visible: DataCapability,
    hidden: DataCapability,
    memory_visible: ResearchContextSection,
    memory_hidden: ResearchContextSection,
) -> None:
    """Each Analyst sees only its matrix fields through an attributable index."""

    projected = AgentInputProjector.analyst(_data_bundle(), _memory_bundle(), role)

    assert projected.schema_version == AGENT_INPUT_SCHEMA_VERSION
    assert projected.expected_output_schema_version == AGENT_OUTPUT_SCHEMA_VERSION
    assert projected.data.section(visible).capability is visible
    with pytest.raises(KeyError):
        projected.data.section(hidden)
    assert memory_visible in projected.memory.allowed_sections
    assert memory_hidden not in projected.memory.allowed_sections
    assert projected.epistemic_policy.external_access_allowed is False
    assert projected.epistemic_policy.llm_ratio_calculation_allowed is False
    assert projected.epistemic_policy.unsupported_unit_conversion_allowed is False
    assert (
        projected.epistemic_policy.absence_of_evidence_is_evidence_of_absence is False
    )
    evidence = next(iter(projected.data_evidence_index.values()))
    assert projected.resolve_data_evidence(evidence.evidence_id) == evidence
    with pytest.raises(KeyError):
        projected.resolve_data_evidence("ev_not-visible")


def test_missing_data_is_preserved_in_sentiment_context() -> None:
    """An absent sample remains explicit and is never converted into a negative fact."""

    bundle = _data_bundle().model_copy(
        update={
            "sentiment_evidence": _missing_section(DataCapability.SENTIMENT_EVIDENCE)
        }
    )

    projected = AgentInputProjector.analyst(
        bundle,
        _memory_bundle(),
        AgentName.SENTIMENT_ANALYST,
    )

    assert (
        projected.data.section(DataCapability.SENTIMENT_EVIDENCE).status
        is DataAvailabilityStatus.MISSING
    )
    assert len(projected.coverage.missing_data) == 1
    assert projected.coverage.missing_data[0].impact
    assert (
        projected.epistemic_policy.absence_of_evidence_is_evidence_of_absence is False
    )


def test_projection_rejects_cross_snapshot_identity_and_future_evidence() -> None:
    """Asset/as-of drift and forward-looking evidence fail before LLM invocation."""

    memory = _memory_bundle()
    mismatched_metadata = memory.retrieval_metadata.model_copy(
        update={"as_of": AS_OF - timedelta(seconds=1)}
    )
    mismatched_memory = memory.model_copy(
        update={"retrieval_metadata": mismatched_metadata}
    )
    with pytest.raises(AgentInputProjectionError, match="as_of"):
        AgentInputProjector.analyst(
            _data_bundle(),
            mismatched_memory,
            AgentName.FUNDAMENTAL_ANALYST,
        )

    bundle = _data_bundle()
    section = bundle.fundamentals
    future = section.items[0].model_copy(
        update={"effective_at": AS_OF + timedelta(seconds=1)}
    )
    future_section = section.model_copy(update={"items": (future,)})
    future_bundle = bundle.model_copy(update={"fundamentals": future_section})
    with pytest.raises(ValidationError, match="future structured evidence"):
        AgentInputProjector.analyst(
            future_bundle,
            _memory_bundle(),
            AgentName.FUNDAMENTAL_ANALYST,
        )


def test_manager_context_requires_all_analyst_slots_and_preserves_failure() -> None:
    """A degraded Analyst remains visible instead of disappearing in synthesis."""

    outputs = _analyst_outputs(missing=AgentName.SENTIMENT_ANALYST)
    context = AgentInputProjector.manager_context(
        _data_bundle(),
        _memory_bundle(),
        AgentName.RESEARCH_MANAGER,
        outputs,
    )
    request = ResearchManagerInputV1(context=context)

    assert request.context.coverage.unavailable_upstream_outputs == (
        AgentName.SENTIMENT_ANALYST,
    )
    assert len(request.context.analyst_outputs) == 4
    with pytest.raises(ValidationError, match="at least 4 items|all four Analyst"):
        AgentInputProjector.manager_context(
            _data_bundle(),
            _memory_bundle(),
            AgentName.RESEARCH_MANAGER,
            outputs[:-1],
        )


def test_research_manager_receives_no_raw_evidence_manifest() -> None:
    """Research Manager consumes upstream Claims, not a raw Evidence namespace."""

    data = _data_bundle()
    evidence_id = data.fundamentals.items[0].evidence_id
    analysts = _analyst_outputs_with_evidence(evidence_id)
    manager_context = AgentInputProjector.manager_context(
        data,
        _memory_bundle(),
        AgentName.RESEARCH_MANAGER,
        analysts,
    )
    request = ResearchManagerInputV1(context=manager_context)
    projected = _context_for_contract(
        AgentContext(
            report_date=AS_OF.date(),
            market_scope=ReportMarketScope.US,
            asset_id=ASSET,
            structured_features={"fixture": True},
        ),
        request,
    )

    assert evidence_id
    assert projected.role_evidence_manifest is None
    assert projected.structured_evidence == []
    assert projected.retrieved_documents == []


@pytest.mark.parametrize(
    ("agent_name", "request_model"),
    [
        (AgentName.BULL_MANAGER, BullManagerInputV1),
        (AgentName.BEAR_MANAGER, BearManagerInputV1),
    ],
)
def test_bull_and_bear_receive_no_raw_evidence_manifest(
    agent_name: AgentName,
    request_model: type[BullManagerInputV1] | type[BearManagerInputV1],
) -> None:
    """Debate roles inherit Claims and do not regain raw Evidence."""

    data = _data_bundle()
    evidence_id = data.fundamentals.items[0].evidence_id
    analysts = _analyst_outputs_with_evidence(evidence_id)
    manager_context = AgentInputProjector.manager_context(
        data,
        _memory_bundle(),
        agent_name,
        analysts,
    )
    research_output = VersionedUpstreamOutputV1(
        agent_name=AgentName.RESEARCH_MANAGER,
        status=AgentStatus.OK,
        output={"analysis": {"summary_points": ["Validated synthesis."]}},
        evidence_ids=(evidence_id,),
    )
    request = request_model(
        context=manager_context,
        research_output=research_output,
    )
    projected = _context_for_contract(
        AgentContext(
            report_date=AS_OF.date(),
            market_scope=ReportMarketScope.US,
            asset_id=ASSET,
            structured_features={"fixture": True},
        ),
        request,
    )

    assert evidence_id
    assert projected.role_evidence_manifest is None
    assert projected.structured_evidence == []


def test_bull_bear_and_risk_require_the_ordered_research_chain() -> None:
    """Manager schemas reject role substitution and unsuccessful hard gates."""

    data = _data_bundle()
    memory = _memory_bundle()
    analysts = _analyst_outputs()
    research = _success(AgentName.RESEARCH_MANAGER)
    bull_context = AgentInputProjector.manager_context(
        data, memory, AgentName.BULL_MANAGER, analysts
    )
    bear_context = AgentInputProjector.manager_context(
        data, memory, AgentName.BEAR_MANAGER, analysts
    )
    risk_context = AgentInputProjector.manager_context(
        data, memory, AgentName.RISK_MANAGER, analysts
    )

    BullManagerInputV1(context=bull_context, research_output=research)
    BearManagerInputV1(context=bear_context, research_output=research)
    RiskManagerInputV1(
        context=risk_context,
        research_output=research,
        bull_output=_success(AgentName.BULL_MANAGER),
        bear_output=_success(AgentName.BEAR_MANAGER),
    )

    failed_research = VersionedUpstreamOutputV1(
        agent_name=AgentName.RESEARCH_MANAGER,
        status=AgentStatus.ERROR,
        error_code="schema_validation",
    )
    with pytest.raises(ValidationError, match="successful research_manager"):
        BullManagerInputV1(
            context=bull_context,
            research_output=failed_research,
        )
    with pytest.raises(ValidationError, match="successful bull_manager"):
        RiskManagerInputV1(
            context=risk_context,
            research_output=research,
            bull_output=_success(AgentName.BEAR_MANAGER),
            bear_output=_success(AgentName.BEAR_MANAGER),
        )


def test_upstream_output_schema_version_and_status_are_strict() -> None:
    """Version drift and ambiguous success/failure payloads are rejected."""

    output = _success(AgentName.RESEARCH_MANAGER)
    assert output.schema_version == AGENT_OUTPUT_SCHEMA_VERSION
    with pytest.raises(ValidationError):
        VersionedUpstreamOutputV1.model_validate(
            {
                "schema_version": "agent_output_v3",
                "agent_name": AgentName.RESEARCH_MANAGER,
                "status": AgentStatus.OK,
                "output": {},
            }
        )
    with pytest.raises(ValidationError, match="requires output only"):
        VersionedUpstreamOutputV1(
            agent_name=AgentName.RESEARCH_MANAGER,
            status=AgentStatus.OK,
            output={},
            error_code="unexpected",
        )
