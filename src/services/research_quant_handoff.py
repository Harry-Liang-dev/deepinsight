"""Deterministic Research-to-Quant handoff construction and export."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import cast

from src.models.types import DomainModel, JsonValue
from src.schemas.research_data import DataQualityStatus
from src.schemas.research_episode import ResearchEpisodeVersionReference
from src.schemas.research_quant_handoff import (
    HandoffSatelliteReference,
    ResearchQuantHandoffBatchManifest,
    ResearchQuantHandoffBuildInput,
    ResearchQuantHandoffBundle,
    ResearchQuantHandoffCoverageCount,
    ResearchQuantHandoffProvenance,
    ResearchQuantHandoffVersionManifest,
)
from src.schemas.research_state import ResearchStateSectionName
from src.schemas.satellite_alpha import (
    SatelliteAlphaCoverageStatus,
    SatelliteAlphaObservation,
    SatelliteAlphaUsage,
)
from src.schemas.temporal import (
    TemporalMetadata,
    require_utc_aware,
    validate_temporal_access,
)

_BUILD_VERSION = "research_quant_handoff_build_v1"


class ResearchQuantHandoffBuildError(ValueError):
    """Raised when frozen Research artifacts cannot form a safe handoff."""


class ResearchQuantHandoffExportError(ValueError):
    """Raised when a handoff export is structurally ambiguous."""


class ResearchQuantHandoffBuilder:
    """Build one reference-only handoff without LLM or Provider calls."""

    def build(
        self, inputs: ResearchQuantHandoffBuildInput
    ) -> ResearchQuantHandoffBundle:
        """Validate frozen inputs and produce one deterministic Bundle."""

        self._validate(inputs)
        state = inputs.research_state
        episode = inputs.research_episode
        selection = tuple(
            sorted(
                (_satellite_reference(item) for item in inputs.selection_observations),
                key=lambda item: item.observation_id,
            )
        )
        timing = tuple(
            sorted(
                (_satellite_reference(item) for item in inputs.timing_observations),
                key=lambda item: item.observation_id,
            )
        )
        observations = (*inputs.selection_observations, *inputs.timing_observations)
        candidate = inputs.opportunity_candidate
        transition = inputs.research_state_transition
        sector_ids = {
            item.sector_id for item in observations if item.sector_id is not None
        }
        if candidate is not None and candidate.sector_id is not None:
            sector_ids.add(candidate.sector_id)
        if len(sector_ids) > 1:
            raise ResearchQuantHandoffBuildError(
                "handoff sources disagree on canonical Sector"
            )
        sector_id = next(iter(sector_ids)) if sector_ids else None
        chain_ids = tuple(
            sorted(
                {
                    *(
                        scope.removeprefix("CHAIN:")
                        for scope in state.hierarchy.industry_chain_scope_ids
                    ),
                    *(chain for item in observations for chain in item.chain_ids),
                    *(candidate.chain_ids if candidate is not None else ()),
                }
            )
        )
        coverage, missing = _coverage(inputs)
        provenance = _provenance(inputs)
        versions = _versions(inputs)
        payload = {
            "asset_id": str(state.asset_id),
            "market": state.asset_id.market.value,
            "research_as_of": state.research_as_of.isoformat(),
            "sector_id": sector_id.value if sector_id is not None else None,
            "chain_ids": chain_ids,
            "opportunity_candidate_id": (
                None if candidate is None else candidate.candidate_id
            ),
            "opportunity_candidate_status": (
                None if candidate is None else candidate.status.value
            ),
            "research_state_id": state.research_state_id,
            "research_episode_id": episode.episode_id,
            "research_state_transition_id": (
                None if transition is None else transition.transition_id
            ),
            "selection_satellite_observations": [
                item.model_dump(mode="json") for item in selection
            ],
            "timing_satellite_observations": [
                item.model_dump(mode="json") for item in timing
            ],
            "catalyst_refs": (
                () if candidate is None else tuple(sorted(candidate.catalyst_refs))
            ),
            "risk_refs": (
                () if candidate is None else tuple(sorted(candidate.risk_refs))
            ),
            "invalidator_refs": (
                () if candidate is None else tuple(sorted(candidate.invalidator_refs))
            ),
            "expected_horizon": (
                None
                if candidate is None or candidate.expected_horizon is None
                else candidate.expected_horizon.value
            ),
            "coverage_status": coverage.value,
            "data_quality": _quality(inputs).value,
            "missing_reasons": missing,
            "data_snapshot_id": episode.data_snapshot_id,
            "source_run_id": state.lineage.source_run_id,
            "versions": versions.model_dump(mode="json"),
            "provenance": provenance.model_dump(mode="json"),
            "schema_version": "research_quant_handoff_bundle_v1",
        }
        bundle_id = "research_quant_handoff_" + _digest(payload)
        return ResearchQuantHandoffBundle(
            bundle_id=bundle_id,
            asset_id=state.asset_id,
            market=state.asset_id.market,
            research_as_of=state.research_as_of,
            sector_id=sector_id,
            chain_ids=chain_ids,
            opportunity_candidate_id=(
                None if candidate is None else candidate.candidate_id
            ),
            opportunity_candidate_status=(
                None if candidate is None else candidate.status
            ),
            research_state_id=state.research_state_id,
            research_episode_id=episode.episode_id,
            research_state_transition_id=(
                None if transition is None else transition.transition_id
            ),
            selection_satellite_observations=selection,
            timing_satellite_observations=timing,
            catalyst_refs=(
                () if candidate is None else tuple(sorted(candidate.catalyst_refs))
            ),
            risk_refs=() if candidate is None else tuple(sorted(candidate.risk_refs)),
            invalidator_refs=(
                () if candidate is None else tuple(sorted(candidate.invalidator_refs))
            ),
            expected_horizon=None if candidate is None else candidate.expected_horizon,
            coverage_status=coverage,
            data_quality=_quality(inputs),
            missing_reasons=missing,
            data_snapshot_id=episode.data_snapshot_id,
            source_run_id=state.lineage.source_run_id,
            versions=versions,
            provenance=provenance,
            created_at=inputs.created_at,
        )

    @staticmethod
    def _validate(inputs: ResearchQuantHandoffBuildInput) -> None:
        state = inputs.research_state
        episode = inputs.research_episode
        if (
            episode.asset_id != state.asset_id
            or episode.market is not state.asset_id.market
            or episode.research_as_of != state.research_as_of
            or episode.research_state_id != state.research_state_id
        ):
            raise ResearchQuantHandoffBuildError(
                "ResearchEpisode does not match the handoff ResearchState"
            )
        state_snapshot = state.lineage.data_snapshot_id or state.lineage.data_bundle_id
        if episode.data_snapshot_id != state_snapshot:
            raise ResearchQuantHandoffBuildError(
                "ResearchEpisode data snapshot differs from ResearchState"
            )
        if episode.created_at > inputs.created_at:
            raise ResearchQuantHandoffBuildError(
                "handoff cannot consume a future ResearchEpisode"
            )
        _validate_materialized_at(
            episode.created_at,
            episode.created_at,
            inputs.created_at,
        )

        observations = (*inputs.selection_observations, *inputs.timing_observations)
        ids = tuple(item.observation_id for item in observations)
        if not observations:
            raise ResearchQuantHandoffBuildError(
                "handoff requires at least one Satellite observation"
            )
        if len(ids) != len(set(ids)):
            raise ResearchQuantHandoffBuildError(
                "handoff Satellite observation identities must be unique"
            )
        for item in inputs.selection_observations:
            if item.usage not in {
                SatelliteAlphaUsage.SELECTION,
                SatelliteAlphaUsage.BOTH,
            }:
                raise ResearchQuantHandoffBuildError(
                    "selection branch contains a Timing-only observation"
                )
        for item in inputs.timing_observations:
            if item.usage not in {
                SatelliteAlphaUsage.TIMING,
                SatelliteAlphaUsage.BOTH,
            }:
                raise ResearchQuantHandoffBuildError(
                    "timing branch contains a Selection-only observation"
                )
        for observation in observations:
            if (
                observation.asset_id != state.asset_id
                or observation.market is not state.asset_id.market
                or observation.research_as_of != state.research_as_of
                or observation.source_research_state_id != state.research_state_id
            ):
                raise ResearchQuantHandoffBuildError(
                    "Satellite observation does not match handoff ResearchState"
                )
            if observation.source_episode_id not in {None, episode.episode_id}:
                raise ResearchQuantHandoffBuildError(
                    "Satellite observation references a different Episode"
                )
            _validate_materialized_at(
                observation.available_at,
                observation.created_at,
                inputs.created_at,
            )
            _validate_feature_references(observation, inputs)

        candidate = inputs.opportunity_candidate
        if candidate is not None:
            if (
                candidate.asset_id != state.asset_id
                or candidate.market is not state.asset_id.market
                or candidate.research_as_of != state.research_as_of
                or candidate.source_research_state_id != state.research_state_id
                or candidate.source_episode_id not in {None, episode.episode_id}
            ):
                raise ResearchQuantHandoffBuildError(
                    "OpportunityCandidate does not match handoff State/Episode"
                )
            selection_ids = {
                item.observation_id for item in inputs.selection_observations
            }
            if not set(candidate.satellite_observation_ids) <= selection_ids:
                raise ResearchQuantHandoffBuildError(
                    "OpportunityCandidate references an unknown Selection observation"
                )
            _validate_materialized_at(
                candidate.available_at,
                candidate.created_at,
                inputs.created_at,
            )

        transition = inputs.research_state_transition
        if transition is not None:
            if (
                transition.asset_id != state.asset_id
                or transition.current_state_id != state.research_state_id
                or transition.current_as_of != state.research_as_of
                or transition.previous_as_of >= transition.current_as_of
                or transition.current_episode_id not in {None, episode.episode_id}
            ):
                raise ResearchQuantHandoffBuildError(
                    "ResearchStateTransition does not terminate at handoff State"
                )
            _validate_materialized_at(
                transition.available_at,
                transition.created_at,
                inputs.created_at,
            )
        transition_id = None if transition is None else transition.transition_id
        if any(
            item.source_transition_id not in {None, transition_id}
            for item in inputs.timing_observations
        ):
            raise ResearchQuantHandoffBuildError(
                "Timing observation references a different State transition"
            )
        if transition is None and any(
            item.source_transition_id is not None for item in inputs.timing_observations
        ):
            raise ResearchQuantHandoffBuildError(
                "handoff omitted a referenced State transition"
            )


class ResearchQuantHandoffExporter:
    """Write canonical JSON and mixed-coverage JSONL artifacts."""

    @staticmethod
    def serialize(bundle: ResearchQuantHandoffBundle) -> str:
        """Return stable canonical JSON for one Bundle."""

        return _canonical(bundle)

    def export_bundle(
        self,
        bundle: ResearchQuantHandoffBundle,
        path: Path,
    ) -> Path:
        """Write one canonical Bundle JSON artifact."""

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.serialize(bundle) + "\n", encoding="utf-8")
        return path

    def export_batch(
        self,
        bundles: tuple[ResearchQuantHandoffBundle, ...],
        output_dir: Path,
        *,
        generated_at: datetime,
    ) -> ResearchQuantHandoffBatchManifest:
        """Write canonical Bundle JSONL plus a credential-free manifest."""

        generated_at = require_utc_aware(generated_at)
        if not bundles:
            raise ResearchQuantHandoffExportError("batch export requires Bundles")
        if len({item.bundle_id for item in bundles}) != len(bundles):
            raise ResearchQuantHandoffExportError(
                "batch export contains duplicate Bundle identities"
            )
        seen_join_keys: set[tuple[str, datetime]] = set()
        for item in bundles:
            join_key = (str(item.asset_id), item.research_as_of)
            if join_key in seen_join_keys:
                raise ResearchQuantHandoffExportError(
                    "batch export contains duplicate asset/cutoff join key: "
                    f"asset_id={join_key[0]} research_as_of={join_key[1].isoformat()}"
                )
            seen_join_keys.add(join_key)
        if any(item.created_at > generated_at for item in bundles):
            raise ResearchQuantHandoffExportError(
                "batch manifest cannot predate a Bundle"
            )
        ordered = tuple(sorted(bundles, key=lambda item: item.bundle_id))
        bundle_ids = tuple(item.bundle_id for item in ordered)
        source_runs = tuple(sorted({item.source_run_id for item in ordered}))
        counts = Counter(item.coverage_status for item in ordered)
        coverage = tuple(
            ResearchQuantHandoffCoverageCount(status=status, count=count)
            for status, count in sorted(counts.items(), key=lambda item: item[0].value)
        )
        cutoffs = tuple(sorted({item.research_as_of for item in bundles}))
        export_payload = {
            "research_as_of_values": tuple(item.isoformat() for item in cutoffs),
            "bundle_ids": bundle_ids,
            "source_run_ids": source_runs,
            "coverage": [(item.status.value, item.count) for item in coverage],
            "manifest_version": "research_quant_handoff_manifest_v1",
        }
        export_id = "research_quant_export_" + _digest(export_payload)
        artifact_name = f"{export_id}.jsonl"
        manifest = ResearchQuantHandoffBatchManifest(
            export_id=export_id,
            research_as_of=cutoffs[0] if len(cutoffs) == 1 else None,
            research_as_of_values=cutoffs,
            asset_count=len({str(item.asset_id) for item in ordered}),
            bundle_count=len(ordered),
            bundle_ids=bundle_ids,
            source_run_ids=source_runs,
            coverage_summary=coverage,
            artifact_path=artifact_name,
            generated_at=generated_at,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        jsonl = "".join(self.serialize(item) + "\n" for item in ordered)
        (output_dir / artifact_name).write_text(jsonl, encoding="utf-8")
        (output_dir / f"{export_id}.manifest.json").write_text(
            _canonical(manifest) + "\n",
            encoding="utf-8",
        )
        return manifest


def _satellite_reference(item: SatelliteAlphaObservation) -> HandoffSatelliteReference:
    return HandoffSatelliteReference(
        observation_id=item.observation_id,
        satellite_alpha_id=item.satellite_alpha_id,
        family=item.satellite_alpha_id,
        usage=item.usage,
        comparison_scope=item.comparison_scope,
        coverage_status=item.coverage_status,
        value=item.value,
        value_components=item.value_components,
        quality=item.quality,
        confidence=item.confidence,
        missing_reasons=tuple(sorted(item.missing_reasons)),
        definition_version=item.definition_version,
        transform_version=item.transform_version,
        available_at=item.available_at,
    )


def _validate_materialized_at(
    available_at: datetime,
    created_at: datetime,
    export_created_at: datetime,
) -> None:
    validate_temporal_access(
        TemporalMetadata(available_at=available_at, ingested_at=created_at),
        export_created_at,
    )


def _validate_feature_references(
    observation: SatelliteAlphaObservation,
    inputs: ResearchQuantHandoffBuildInput,
) -> None:
    state = inputs.research_state
    available = {
        f"{section.section_name.value}::{feature.feature_name}"
        for name in ResearchStateSectionName
        for section in (getattr(state, name.value),)
        for feature in section.features
    }
    transition = inputs.research_state_transition
    if transition is not None:
        available.update(
            ref
            for change in (
                *transition.expectation_changes,
                *transition.risk_changes,
                *transition.catalyst_changes,
                *transition.evidence_changes,
            )
            for ref in change.source_state_feature_refs
        )
    unknown = set(observation.source_state_feature_refs) - available
    if unknown:
        raise ResearchQuantHandoffBuildError(
            "Satellite observation references an unknown State feature"
        )


def _coverage(
    inputs: ResearchQuantHandoffBuildInput,
) -> tuple[SatelliteAlphaCoverageStatus, tuple[str, ...]]:
    observations = (*inputs.selection_observations, *inputs.timing_observations)
    statuses = [item.coverage_status for item in observations]
    candidate = inputs.opportunity_candidate
    if candidate is not None:
        statuses.append(candidate.coverage_status)
    unique = set(statuses)
    if unique == {SatelliteAlphaCoverageStatus.AVAILABLE}:
        return SatelliteAlphaCoverageStatus.AVAILABLE, ()
    missing = tuple(
        sorted(
            {
                f"{item.satellite_alpha_id.value}:{item.coverage_status.value}"
                for item in observations
                if item.coverage_status is not SatelliteAlphaCoverageStatus.AVAILABLE
            }
            | (
                set()
                if candidate is None
                or candidate.coverage_status is SatelliteAlphaCoverageStatus.AVAILABLE
                else {f"opportunity_candidate:{candidate.coverage_status.value}"}
            )
        )
    )
    if len(unique) == 1:
        return next(iter(unique)), missing
    return SatelliteAlphaCoverageStatus.PARTIAL, tuple(
        sorted((*missing, "mixed_source_coverage"))
    )


def _quality(inputs: ResearchQuantHandoffBuildInput) -> DataQualityStatus:
    values = [
        item.quality
        for item in (*inputs.selection_observations, *inputs.timing_observations)
    ]
    if inputs.opportunity_candidate is not None:
        values.append(inputs.opportunity_candidate.quality)
    order = (
        DataQualityStatus.FAIL,
        DataQualityStatus.CONFLICT,
        DataQualityStatus.WARNING,
        DataQualityStatus.UNKNOWN,
        DataQualityStatus.PASS,
    )
    return next(item for item in order if item in values)


def _versions(
    inputs: ResearchQuantHandoffBuildInput,
) -> ResearchQuantHandoffVersionManifest:
    observations = (*inputs.selection_observations, *inputs.timing_observations)
    definitions = tuple(
        ResearchEpisodeVersionReference(name=family, version=version)
        for family, version in sorted(
            {
                (item.satellite_alpha_id.value, item.definition_version)
                for item in observations
            }
        )
    )
    candidate = inputs.opportunity_candidate
    transition = inputs.research_state_transition
    return ResearchQuantHandoffVersionManifest(
        research_state_schema_version=inputs.research_state.schema_version,
        research_state_version=inputs.research_state.research_state_version,
        research_episode_schema_version=inputs.research_episode.schema_version,
        satellite_observation_schema_version=observations[0].schema_version,
        satellite_definition_versions=definitions,
        candidate_version=None if candidate is None else candidate.candidate_version,
        transition_version=(
            None if transition is None else transition.transition_version
        ),
    )


def _provenance(
    inputs: ResearchQuantHandoffBuildInput,
) -> ResearchQuantHandoffProvenance:
    observations = (*inputs.selection_observations, *inputs.timing_observations)
    candidate = inputs.opportunity_candidate
    transition = inputs.research_state_transition
    return ResearchQuantHandoffProvenance(
        source_claim_ids=tuple(
            sorted(
                {ref for item in observations for ref in item.source_claim_ids}
                | (set() if candidate is None else set(candidate.source_claim_ids))
                | (set() if candidate is None else set(candidate.risk_refs))
                | (set() if candidate is None else set(candidate.invalidator_refs))
                | (set() if transition is None else set(transition.source_claim_ids))
            )
        ),
        source_evidence_ids=tuple(
            sorted(
                {ref for item in observations for ref in item.source_evidence_ids}
                | (set() if transition is None else set(transition.source_evidence_ids))
            )
        ),
        source_event_ids=tuple(
            sorted(
                {ref for item in observations for ref in item.source_event_ids}
                | (set() if candidate is None else set(candidate.source_event_ids))
                | (set() if candidate is None else set(candidate.catalyst_refs))
                | (set() if transition is None else set(transition.source_event_ids))
            )
        ),
        source_sector_claim_ids=tuple(
            sorted(
                {ref for item in observations for ref in item.source_sector_claim_ids}
                | (
                    set()
                    if candidate is None
                    else set(candidate.source_sector_claim_ids)
                )
            )
        ),
        source_artifact_ids=tuple(
            sorted(
                {
                    inputs.research_state.research_state_id,
                    inputs.research_episode.episode_id,
                    *(item.observation_id for item in observations),
                    *(ref for item in observations for ref in item.source_artifact_ids),
                    *(() if candidate is None else (candidate.candidate_id,)),
                    *(() if transition is None else (transition.transition_id,)),
                    *(() if transition is None else transition.source_artifact_ids),
                }
            )
        ),
    )


def _canonical(model: DomainModel) -> str:
    payload = cast(JsonValue, model.model_dump(mode="json"))
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()[:24]
