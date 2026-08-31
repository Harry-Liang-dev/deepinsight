"""Contract and hierarchy tests for Sector Ontology v1."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from src.models.enums import (
    ResearchScopeType,
    SectorCapabilityStatus,
    SectorId,
    SectorMembershipRole,
)
from src.models.identifiers import AssetId
from src.schemas.research_data import DataQualityStatus
from src.schemas.sectors import (
    ResearchScopeDefinition,
    SectorDefinition,
    SectorMembership,
    SectorOntology,
    SectorUniverseCoverage,
    SectorUniverseSnapshot,
)
from src.services.sector_ontology import (
    SectorOntologyValidationError,
    build_sector_ontology_seed_v1,
    build_sector_ontology_v1,
    validate_scope_hierarchy,
    validate_sector_ontology_seed,
)
from src.services.sector_universe import (
    CURRENT_US_RESEARCH_UNIVERSE_VERSION,
    build_current_us_research_memberships_v1,
    build_us_sector_benchmark_candidates_v1,
    resolve_validated_benchmark_mappings,
)


def test_sector_ontology_v1_contains_exactly_unique_stable_18() -> None:
    """The first-level ontology is fixed to the approved 18 IDs and names."""

    ontology = build_sector_ontology_v1()

    assert len(ontology.sectors) == 18
    assert {item.sector_id for item in ontology.sectors} == set(SectorId)
    assert len({item.name for item in ontology.sectors}) == 18
    assert ontology.sectors[0].name == "Semiconductors & AI Compute"
    assert ontology.sectors[-1].name == "Real Estate & Infrastructure"


def test_sector_ontology_rejects_duplicate_identity() -> None:
    """Duplicate Sector IDs cannot enter one versioned ontology."""

    duplicate = SectorDefinition(
        sector_id=SectorId.SEMICONDUCTORS_AI_COMPUTE,
        name="Duplicate",
    )
    with pytest.raises(ValidationError, match="sector IDs must be unique"):
        SectorOntology(sectors=(duplicate, duplicate.model_copy()))


def test_membership_requires_valid_temporal_interval() -> None:
    """Membership uses a non-empty, half-open validity interval."""

    with pytest.raises(ValidationError, match="valid_to must be later"):
        SectorMembership(
            asset_id=AssetId("US:AAPL"),
            sector_id=SectorId.CONSUMER_ELECTRONICS_HARDWARE,
            chain_ids=("APPLE_CHAIN",),
            role=SectorMembershipRole.CORE,
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 1, 1),
            weight=1.0,
            confidence=1.0,
            source="test",
            version="v1",
        )


def test_seed_maps_industry_chains_to_membership_sectors() -> None:
    """Every seeded membership chain belongs to the same first-level Sector."""

    seed = build_sector_ontology_seed_v1()
    chain_sector = {item.chain_id: item.sector_id for item in seed.chains}

    for membership in seed.memberships:
        assert all(
            chain_sector[chain_id] is membership.sector_id
            for chain_id in membership.chain_ids
        )

    broken = seed.model_copy(
        update={
            "memberships": (
                seed.memberships[0].model_copy(update={"chain_ids": ("HBM",)}),
                *seed.memberships[1:],
            )
        }
    )
    with pytest.raises(
        SectorOntologyValidationError,
        match="different Sector",
    ):
        validate_sector_ontology_seed(broken)


def test_scope_hierarchy_has_expected_parent_chain() -> None:
    """The seed connects Macro, Sector, Chain, Asset, and Episode scopes."""

    scopes = build_sector_ontology_seed_v1().scopes
    by_id = {item.scope_id: item for item in scopes}

    assert by_id["MACRO:US"].parent_scope_id == "GLOBAL:GLOBAL"
    assert by_id["SECTOR:SEMICONDUCTORS_AI"].parent_scope_id == "MACRO:US"
    assert by_id["CHAIN:NVIDIA_AI_INFRA"].parent_scope_id == "SECTOR:SEMICONDUCTORS_AI"
    assert by_id["ASSET:NVDA"].parent_scope_id == "CHAIN:NVIDIA_AI_INFRA"
    assert by_id["EPISODE:AAPL_DAY30"].parent_scope_id == "ASSET:AAPL"


def test_scope_hierarchy_rejects_cycles() -> None:
    """Cross-record validation rejects a circular parent scope."""

    first = ResearchScopeDefinition.model_construct(
        scope_type=ResearchScopeType.ASSET,
        scope_id="ASSET:A",
        parent_scope_id="ASSET:B",
        name="A",
        valid_from=date(2026, 1, 1),
        valid_to=None,
        version="v1",
    )
    second = ResearchScopeDefinition.model_construct(
        scope_type=ResearchScopeType.ASSET,
        scope_id="ASSET:B",
        parent_scope_id="ASSET:A",
        name="B",
        valid_from=date(2026, 1, 1),
        valid_to=None,
        version="v1",
    )
    root = ResearchScopeDefinition(
        scope_type=ResearchScopeType.GLOBAL,
        scope_id="GLOBAL:GLOBAL",
        name="Global",
        valid_from=date(2026, 1, 1),
        version="v1",
    )

    with pytest.raises(SectorOntologyValidationError, match="cycle"):
        validate_scope_hierarchy((root, first, second))


def test_us_benchmark_catalog_covers_exactly_18_sectors() -> None:
    """Every Sector has an explicit optional mapping instead of an implicit ETF."""

    candidates = build_us_sector_benchmark_candidates_v1()

    assert len(candidates) == 18
    assert {item.sector_id for item in candidates} == set(SectorId)
    assert all(item.candidate_ids for item in candidates)


def test_current_research_universe_classification_maps_five_assets() -> None:
    """The live v1 universe has a distinct version and explicit curated source."""

    memberships = build_current_us_research_memberships_v1()

    assert {str(item.asset_id) for item in memberships} == {
        "US:AAPL",
        "US:NVDA",
        "US:AMD",
        "US:TSM",
        "US:MU",
    }
    assert {item.version for item in memberships} == {
        CURRENT_US_RESEARCH_UNIVERSE_VERSION
    }
    assert {item.source for item in memberships} == {
        "phase4_day31_curated_research_universe"
    }


def test_benchmark_mapping_promotes_only_validated_tickers() -> None:
    """An ETF candidate cannot enter a snapshot without real-price validation."""

    candidates = build_us_sector_benchmark_candidates_v1()
    mappings = resolve_validated_benchmark_mappings(
        candidates,
        validated_asset_ids={"US:SOXX", "US:XLK"},
        valid_from=date(2026, 8, 30),
    )
    by_sector = {item.sector_id: item for item in mappings}

    assert by_sector[SectorId.SEMICONDUCTORS_AI_COMPUTE].status is (
        SectorCapabilityStatus.AVAILABLE
    )
    assert by_sector[SectorId.MEMORY_STORAGE].status is SectorCapabilityStatus.PARTIAL
    assert by_sector[SectorId.FINANCIALS].status is SectorCapabilityStatus.MISSING
    assert by_sector[SectorId.FINANCIALS].benchmark_ids == ()


def test_sector_universe_snapshot_rejects_inconsistent_coverage() -> None:
    """Snapshot diagnostics must describe its exact immutable content."""

    with pytest.raises(ValidationError, match="membership count"):
        SectorUniverseSnapshot(
            snapshot_id="sector_universe_0123456789abcdef01234567",
            sector_id=SectorId.SEMICONDUCTORS_AI_COMPUTE,
            as_of=date(2026, 8, 30),
            asset_ids=(AssetId("US:NVDA"),),
            membership_version="v1",
            source="test",
            coverage=SectorUniverseCoverage(
                membership_count=0,
                classified_asset_count=0,
                benchmark_count=0,
                classification_ratio=0.0,
            ),
            quality=DataQualityStatus.PASS,
        )
