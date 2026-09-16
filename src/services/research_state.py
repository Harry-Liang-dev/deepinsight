"""Pure ResearchStateSnapshot construction from frozen structured artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime

from src.models.enums import AgentName
from src.schemas.agents import ClaimEvidenceBinding
from src.schemas.research_data import (
    DataAvailabilityStatus,
    DataQualityStatus,
    ResearchDataBundle,
    ResearchDataSection,
    ResearchEvidenceItem,
)
from src.schemas.research_state import (
    NormalizedResearchFeatureInput,
    ResearchStateBuildInput,
    ResearchStateClaimInput,
    ResearchStateFeature,
    ResearchStateFeatureType,
    ResearchStateHierarchy,
    ResearchStateLineage,
    ResearchStateSection,
    ResearchStateSectionName,
    ResearchStateSectionStatus,
    ResearchStateSnapshot,
)

_FEATURE_VERSION = "research_state_feature_v1"


class ResearchStateBuildError(ValueError):
    """Raised when frozen inputs cannot form a safe State snapshot."""


class ResearchStateBuilder:
    """Build immutable machine state without LLM, Provider, or report access."""

    def build(self, inputs: ResearchStateBuildInput) -> ResearchStateSnapshot:
        """Build one deterministic snapshot from already frozen artifacts.

        Args:
            inputs: Typed Data, Sector, Claim, Memory, and version references.

        Returns:
            An immutable, PIT-safe ResearchState snapshot.

        Raises:
            ResearchStateBuildError: If inputs disagree or Claim lineage is open.
        """

        bundle = inputs.research_data_bundle
        research_as_of = bundle.as_of
        if inputs.sector_context is not None:
            if inputs.sector_context.asset_id != bundle.asset_id:
                raise ResearchStateBuildError(
                    "Sector context asset does not match Data"
                )
            if inputs.sector_context.research_as_of != research_as_of:
                raise ResearchStateBuildError("Sector context has a different as_of")
        if inputs.memory_context is not None:
            if inputs.memory_context.as_of != research_as_of:
                raise ResearchStateBuildError("Memory context has a different as_of")

        claim_inputs = tuple(inputs.accepted_claims)
        claim_index = self._validate_claim_graph(inputs)
        section_features: dict[ResearchStateSectionName, list[ResearchStateFeature]] = {
            name: [] for name in ResearchStateSectionName
        }

        self._project_data(bundle, section_features)
        self._project_claims(claim_inputs, section_features, research_as_of)
        self._project_sector(inputs, section_features)
        self._project_normalized(
            inputs.normalized_features,
            claim_index,
            section_features,
        )
        self._project_data_quality(bundle.bundle_id, bundle, section_features)
        self._project_memory(inputs, section_features)

        fingerprint = self._fingerprint(inputs)
        hierarchy = ResearchStateHierarchy(
            macro_scope_ids=(
                ("MACRO:US",) if str(bundle.asset_id).startswith("US:") else ()
            ),
            sector_scope_id=(
                inputs.sector_context.sector_scope_id
                if inputs.sector_context is not None
                else None
            ),
            industry_chain_scope_ids=(
                tuple(
                    f"CHAIN:{item}" for item in inputs.sector_context.active_chain_ids
                )
                if inputs.sector_context is not None
                else ()
            ),
            asset_scope_id=f"ASSET:{bundle.asset_id}",
        )
        lineage = ResearchStateLineage(
            source_run_id=inputs.source_run_id,
            data_bundle_id=bundle.bundle_id,
            data_snapshot_id=bundle.snapshot_id,
            dataset_version=bundle.dataset_version,
            sector_context_id=(
                inputs.sector_context.context_id
                if inputs.sector_context is not None
                else None
            ),
            memory_context_id=(
                inputs.memory_context.snapshot_id
                if inputs.memory_context is not None
                else None
            ),
            agent_run_ids=tuple(
                dict.fromkeys(item.agent_run_id for item in claim_inputs)
            ),
            versions=tuple((*inputs.prompt_versions, *inputs.model_versions)),
            input_fingerprint=fingerprint,
        )
        reasons = self._section_reasons(inputs)
        sections = {
            name: self._make_section(name, section_features[name], reasons.get(name))
            for name in ResearchStateSectionName
        }
        return ResearchStateSnapshot(
            research_state_id=f"research_state_{fingerprint[:24]}",
            asset_id=bundle.asset_id,
            research_as_of=research_as_of,
            hierarchy=hierarchy,
            identity=sections[ResearchStateSectionName.IDENTITY],
            macro_state=sections[ResearchStateSectionName.MACRO],
            sector_state=sections[ResearchStateSectionName.SECTOR],
            industry_chain_state=sections[ResearchStateSectionName.INDUSTRY_CHAIN],
            fundamental_state=sections[ResearchStateSectionName.FUNDAMENTAL],
            valuation_state=sections[ResearchStateSectionName.VALUATION],
            technical_state=sections[ResearchStateSectionName.TECHNICAL],
            sentiment_state=sections[ResearchStateSectionName.SENTIMENT],
            event_state=sections[ResearchStateSectionName.EVENT],
            market_context_state=sections[ResearchStateSectionName.MARKET_CONTEXT],
            debate_state=sections[ResearchStateSectionName.DEBATE],
            risk_state=sections[ResearchStateSectionName.RISK],
            thesis_state=sections[ResearchStateSectionName.THESIS],
            data_quality_state=sections[ResearchStateSectionName.DATA_QUALITY],
            memory_context_state=sections[ResearchStateSectionName.MEMORY_CONTEXT],
            lineage=lineage,
        )

    @staticmethod
    def _fingerprint(inputs: ResearchStateBuildInput) -> str:
        payload = inputs.model_dump(mode="json", exclude_none=True)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()

    @staticmethod
    def _validate_claim_graph(
        inputs: ResearchStateBuildInput,
    ) -> dict[str, ClaimEvidenceBinding]:
        claims = [item.claim for item in inputs.accepted_claims]
        if inputs.sector_context is not None:
            claims.extend(inputs.sector_context.accepted_claims)
        claim_index: dict[str, ClaimEvidenceBinding] = {}
        for claim in claims:
            if claim.claim_id is None:
                raise ResearchStateBuildError("State input Claim has no stable ID")
            if claim.claim_id in claim_index:
                raise ResearchStateBuildError(
                    "State input contains duplicate Claim IDs"
                )
            claim_index[claim.claim_id] = claim
            if claim.evidence_ids and not claim.source_references:
                raise ResearchStateBuildError(
                    f"direct Claim {claim.claim_id} lacks source references"
                )
        for claim in claims:
            unknown = set(claim.upstream_claim_ids) - set(claim_index)
            if unknown:
                raise ResearchStateBuildError(
                    "Claim "
                    f"{claim.claim_id} has unknown upstream IDs: {sorted(unknown)}"
                )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(claim_id: str) -> None:
            if claim_id in visiting:
                raise ResearchStateBuildError("Claim provenance contains a cycle")
            if claim_id in visited:
                return
            visiting.add(claim_id)
            for parent_id in claim_index[claim_id].upstream_claim_ids:
                visit(parent_id)
            visiting.remove(claim_id)
            visited.add(claim_id)

        for claim_id in claim_index:
            visit(claim_id)
        return claim_index

    def _project_data(
        self,
        bundle: ResearchDataBundle,
        target: dict[ResearchStateSectionName, list[ResearchStateFeature]],
    ) -> None:
        mapping = (
            (ResearchStateSectionName.IDENTITY, bundle.asset_identity),
            (ResearchStateSectionName.MACRO, bundle.macro_indicators),
            (ResearchStateSectionName.FUNDAMENTAL, bundle.fundamentals),
            (ResearchStateSectionName.VALUATION, bundle.valuation),
            (ResearchStateSectionName.TECHNICAL, bundle.technical_features),
            (ResearchStateSectionName.SENTIMENT, bundle.sentiment_evidence),
            (ResearchStateSectionName.MARKET_CONTEXT, bundle.market_context),
            (
                ResearchStateSectionName.MARKET_CONTEXT,
                bundle.industry_sector_context,
            ),
        )
        for section_name, section in mapping:
            for item in self._latest_by_field(section.items):
                target[section_name].append(self._feature_from_evidence(item))

    @staticmethod
    def _latest_by_field(
        items: Iterable[ResearchEvidenceItem],
    ) -> tuple[ResearchEvidenceItem, ...]:
        latest: dict[str, ResearchEvidenceItem] = {}
        for item in items:
            prior = latest.get(item.field_path)
            if prior is None or (
                item.observed_at,
                item.effective_at,
                item.evidence_id,
            ) > (prior.observed_at, prior.effective_at, prior.evidence_id):
                latest[item.field_path] = item
        return tuple(latest[key] for key in sorted(latest))

    @staticmethod
    def _feature_from_evidence(item: ResearchEvidenceItem) -> ResearchStateFeature:
        value = item.value
        feature_type = (
            ResearchStateFeatureType.DETERMINISTIC_NUMERIC
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            else ResearchStateFeatureType.SEMANTIC_CATEGORICAL
        )
        return ResearchStateFeature(
            feature_name=item.field_path,
            value=value,
            feature_type=feature_type,
            as_of=item.effective_at,
            available_at=item.observed_at,
            quality=item.quality,
            source_evidence_ids=(item.evidence_id,),
            feature_version=_FEATURE_VERSION,
        )

    @staticmethod
    def _project_claims(
        claims: tuple[ResearchStateClaimInput, ...],
        target: dict[ResearchStateSectionName, list[ResearchStateFeature]],
        research_as_of: datetime,
    ) -> None:
        role_sections = {
            AgentName.FUNDAMENTAL_ANALYST: ResearchStateSectionName.FUNDAMENTAL,
            AgentName.TECHNICAL_TEXT_ANALYST: ResearchStateSectionName.TECHNICAL,
            AgentName.SENTIMENT_ANALYST: ResearchStateSectionName.SENTIMENT,
            AgentName.NEWS_EVENT_ANALYST: ResearchStateSectionName.EVENT,
            AgentName.RESEARCH_MANAGER: ResearchStateSectionName.THESIS,
            AgentName.BULL_MANAGER: ResearchStateSectionName.DEBATE,
            AgentName.BEAR_MANAGER: ResearchStateSectionName.DEBATE,
            AgentName.RISK_MANAGER: ResearchStateSectionName.RISK,
        }
        for item in claims:
            claim = item.claim
            assert claim.claim_id is not None
            target[role_sections[item.agent_role]].append(
                ResearchStateFeature(
                    feature_name=f"claim.{claim.claim_id}",
                    value=claim.claim_text,
                    feature_type=ResearchStateFeatureType.SEMANTIC_CATEGORICAL,
                    as_of=research_as_of,
                    confidence=claim.confidence,
                    quality=DataQualityStatus.PASS,
                    source_claim_ids=(claim.claim_id,),
                    feature_version=_FEATURE_VERSION,
                )
            )

    @staticmethod
    def _project_sector(
        inputs: ResearchStateBuildInput,
        target: dict[ResearchStateSectionName, list[ResearchStateFeature]],
    ) -> None:
        context = inputs.sector_context
        if context is None:
            return
        for claim in context.accepted_claims:
            assert claim.claim_id is not None
            section_name = (
                ResearchStateSectionName.MACRO
                if claim.claim_id in context.macro_claim_ids
                else ResearchStateSectionName.SECTOR
            )
            target[section_name].append(
                ResearchStateFeature(
                    feature_name=f"sector_claim.{claim.claim_id}",
                    value=claim.claim_text,
                    feature_type=ResearchStateFeatureType.SEMANTIC_CATEGORICAL,
                    as_of=context.research_as_of,
                    confidence=claim.confidence,
                    quality=DataQualityStatus.PASS,
                    source_claim_ids=(claim.claim_id,),
                    feature_version=_FEATURE_VERSION,
                )
            )
        target[ResearchStateSectionName.SECTOR].append(
            ResearchStateFeature(
                feature_name="sector_cycle",
                value=context.cycle_phase,
                feature_type=ResearchStateFeatureType.SEMANTIC_CATEGORICAL,
                as_of=context.research_as_of,
                confidence=context.cycle_confidence,
                quality=DataQualityStatus.PASS,
                source_claim_ids=context.cycle_supporting_claim_ids,
                feature_version=_FEATURE_VERSION,
            )
        )
        for chain_id in context.active_chain_ids:
            target[ResearchStateSectionName.INDUSTRY_CHAIN].append(
                ResearchStateFeature(
                    feature_name=f"active_chain.{chain_id}",
                    value=chain_id,
                    feature_type=ResearchStateFeatureType.SEMANTIC_CATEGORICAL,
                    as_of=context.research_as_of,
                    quality=DataQualityStatus.PASS,
                    source_artifact_ids=(context.context_id,),
                    feature_version=_FEATURE_VERSION,
                )
            )

    @staticmethod
    def _project_normalized(
        features: tuple[NormalizedResearchFeatureInput, ...],
        claim_index: dict[str, ClaimEvidenceBinding],
        target: dict[ResearchStateSectionName, list[ResearchStateFeature]],
    ) -> None:
        for item in features:
            unknown = set(item.source_claim_ids) - set(claim_index)
            if unknown:
                raise ResearchStateBuildError(
                    f"normalized feature has unknown Claim IDs: {sorted(unknown)}"
                )
            if not item.source_claim_ids and not item.source_evidence_ids:
                raise ResearchStateBuildError("normalized feature requires provenance")
            target[item.section_name].append(
                ResearchStateFeature(
                    feature_name=item.feature_name,
                    value=item.value,
                    feature_type=ResearchStateFeatureType.NORMALIZED_RESEARCH_STATE,
                    as_of=item.as_of,
                    confidence=item.confidence,
                    quality=item.quality,
                    source_claim_ids=item.source_claim_ids,
                    source_evidence_ids=item.source_evidence_ids,
                    feature_version=_FEATURE_VERSION,
                    transform_name=item.transform_name,
                    transform_version=item.transform_version,
                )
            )

    @staticmethod
    def _project_data_quality(
        bundle_id: str,
        bundle: ResearchDataBundle,
        target: dict[ResearchStateSectionName, list[ResearchStateFeature]],
    ) -> None:
        names = (
            "asset_identity",
            "market_context",
            "ohlcv",
            "technical_features",
            "fundamentals",
            "valuation",
            "corporate_events",
            "filings",
            "macro_indicators",
            "industry_sector_context",
            "news_evidence",
            "sentiment_evidence",
        )
        for name in names:
            section = getattr(bundle, name)
            target[ResearchStateSectionName.DATA_QUALITY].append(
                ResearchStateFeature(
                    feature_name=f"capability.{name}",
                    value=section.status.value,
                    feature_type=ResearchStateFeatureType.SEMANTIC_CATEGORICAL,
                    as_of=bundle.as_of,
                    quality=section.quality.status,
                    source_artifact_ids=(bundle_id,),
                    feature_version=_FEATURE_VERSION,
                )
            )

    @staticmethod
    def _project_memory(
        inputs: ResearchStateBuildInput,
        target: dict[ResearchStateSectionName, list[ResearchStateFeature]],
    ) -> None:
        context = inputs.memory_context
        if context is None:
            return
        for name, value in (
            ("retrieval_status", context.status),
            ("result_count", context.result_count),
        ):
            target[ResearchStateSectionName.MEMORY_CONTEXT].append(
                ResearchStateFeature(
                    feature_name=name,
                    value=value,
                    feature_type=(
                        ResearchStateFeatureType.DETERMINISTIC_NUMERIC
                        if isinstance(value, int)
                        else ResearchStateFeatureType.SEMANTIC_CATEGORICAL
                    ),
                    as_of=context.as_of,
                    quality=DataQualityStatus.PASS,
                    source_artifact_ids=(context.snapshot_id,),
                    feature_version=_FEATURE_VERSION,
                )
            )

    @staticmethod
    def _make_section(
        name: ResearchStateSectionName,
        features: list[ResearchStateFeature],
        reason: tuple[ResearchStateSectionStatus, str] | None,
    ) -> ResearchStateSection:
        if features:
            missing_reason = reason[1] if reason is not None else None
            status = (
                ResearchStateSectionStatus.PARTIAL
                if missing_reason
                else ResearchStateSectionStatus.PRESENT
            )
            return ResearchStateSection(
                section_name=name,
                status=status,
                features=tuple(sorted(features, key=lambda item: item.feature_name)),
                missing_reason=missing_reason,
            )
        status, missing_reason = reason or (
            ResearchStateSectionStatus.MISSING,
            "No attributable structured input was available at the source cutoff.",
        )
        return ResearchStateSection(
            section_name=name,
            status=status,
            missing_reason=missing_reason,
        )

    @staticmethod
    def _section_reasons(
        inputs: ResearchStateBuildInput,
    ) -> dict[ResearchStateSectionName, tuple[ResearchStateSectionStatus, str]]:
        bundle = inputs.research_data_bundle
        mapping: tuple[tuple[ResearchStateSectionName, ResearchDataSection], ...] = (
            (ResearchStateSectionName.IDENTITY, bundle.asset_identity),
            (ResearchStateSectionName.MACRO, bundle.macro_indicators),
            (ResearchStateSectionName.FUNDAMENTAL, bundle.fundamentals),
            (ResearchStateSectionName.VALUATION, bundle.valuation),
            (ResearchStateSectionName.TECHNICAL, bundle.technical_features),
            (ResearchStateSectionName.SENTIMENT, bundle.sentiment_evidence),
            (ResearchStateSectionName.EVENT, bundle.corporate_events),
            (ResearchStateSectionName.MARKET_CONTEXT, bundle.market_context),
        )
        reasons: dict[
            ResearchStateSectionName, tuple[ResearchStateSectionStatus, str]
        ] = {}
        for name, section in mapping:
            if section.status is DataAvailabilityStatus.PRESENT:
                continue
            details = "; ".join(item.reason for item in section.missing_data)
            reasons[name] = (
                (
                    ResearchStateSectionStatus.PARTIAL
                    if section.items
                    else ResearchStateSectionStatus.MISSING
                ),
                details or f"Source capability status: {section.status.value}.",
            )
        if inputs.sector_context is None:
            source_missing = (
                ResearchStateSectionStatus.NOT_AVAILABLE_AT_SOURCE_RUN,
                "Sector context was not persisted by the source research run.",
            )
            reasons[ResearchStateSectionName.SECTOR] = source_missing
            reasons[ResearchStateSectionName.INDUSTRY_CHAIN] = source_missing
        if not inputs.accepted_claims:
            source_missing = (
                ResearchStateSectionStatus.NOT_AVAILABLE_AT_SOURCE_RUN,
                "Accepted Agent Claims were not persisted by the source run.",
            )
            reasons[ResearchStateSectionName.DEBATE] = source_missing
            reasons[ResearchStateSectionName.RISK] = source_missing
            reasons[ResearchStateSectionName.THESIS] = source_missing
            if not bundle.corporate_events.items:
                reasons[ResearchStateSectionName.EVENT] = source_missing
        if inputs.memory_context is None:
            reasons[ResearchStateSectionName.MEMORY_CONTEXT] = (
                ResearchStateSectionStatus.NOT_AVAILABLE_AT_SOURCE_RUN,
                "Structured Memory retrieval context was not persisted by the "
                "source run.",
            )
        return reasons
