"""Point-in-time Sector Universe construction and benchmark validation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import date

from src.models.enums import SectorCapabilityStatus, SectorId
from src.models.identifiers import AssetId
from src.repositories.sectors import SectorOntologyRepository
from src.schemas.research_data import DataQualityStatus
from src.schemas.sectors import (
    SectorBenchmarkCandidate,
    SectorBenchmarkMapping,
    SectorMembership,
    SectorUniverseCoverage,
    SectorUniverseSnapshot,
)
from src.services.sector_ontology import build_sector_ontology_seed_v1

_BENCHMARK_VERSION = "us_sector_benchmarks_v1"
_BENCHMARK_SOURCE = "phase4_day31_candidate_catalog"
CURRENT_US_RESEARCH_UNIVERSE_VERSION = "sector_universe_membership_v1"


class SectorUniverseError(ValueError):
    """Raised when a Sector Universe cannot satisfy its typed contract."""


class SectorUniverseService:
    """Build immutable snapshots from temporal memberships and validated mappings."""

    def __init__(self, repository: SectorOntologyRepository) -> None:
        """Bind the service to the existing Sector Repository."""

        self._repository = repository

    def create_snapshot(
        self,
        *,
        sector_id: SectorId,
        as_of: date,
        membership_version: str,
        source: str,
    ) -> SectorUniverseSnapshot:
        """Build and persist one point-in-time universe without overwriting history."""

        if not isinstance(sector_id, SectorId):
            raise SectorUniverseError("unknown Sector ID")
        memberships = self._repository.list_sector_memberships(
            sector_id,
            as_of=as_of,
            membership_version=membership_version,
        )
        asset_by_id = {str(item.asset_id): item.asset_id for item in memberships}
        asset_ids = tuple(asset_by_id[key] for key in sorted(asset_by_id))
        benchmark_mapping = self._repository.get_benchmark_mapping(
            sector_id,
            as_of=as_of,
        )
        benchmark_ids = (
            () if benchmark_mapping is None else benchmark_mapping.benchmark_ids
        )
        membership_count = len(asset_ids)
        coverage = SectorUniverseCoverage(
            membership_count=membership_count,
            classified_asset_count=membership_count,
            benchmark_count=len(benchmark_ids),
            classification_ratio=1.0 if membership_count else 0.0,
        )
        snapshot = SectorUniverseSnapshot(
            snapshot_id=_snapshot_id(
                sector_id=sector_id,
                as_of=as_of,
                asset_ids=asset_ids,
                benchmark_ids=benchmark_ids,
                membership_version=membership_version,
            ),
            sector_id=sector_id,
            as_of=as_of,
            asset_ids=asset_ids,
            benchmark_ids=benchmark_ids,
            membership_version=membership_version,
            source=source,
            coverage=coverage,
            quality=(
                DataQualityStatus.PASS
                if membership_count
                else DataQualityStatus.WARNING
            ),
        )
        self._repository.save_universe_snapshot(snapshot)
        return snapshot


def build_us_sector_benchmark_candidates_v1() -> tuple[SectorBenchmarkCandidate, ...]:
    """Return 18 optional US ETF candidates; candidates are not yet validated."""

    values: tuple[tuple[SectorId, tuple[str, ...], SectorCapabilityStatus], ...] = (
        (
            SectorId.SEMICONDUCTORS_AI_COMPUTE,
            ("US:SOXX",),
            SectorCapabilityStatus.AVAILABLE,
        ),
        (SectorId.MEMORY_STORAGE, ("US:SOXX",), SectorCapabilityStatus.PARTIAL),
        (
            SectorId.CONSUMER_ELECTRONICS_HARDWARE,
            ("US:XLK",),
            SectorCapabilityStatus.PARTIAL,
        ),
        (
            SectorId.CLOUD_SOFTWARE_AI_APPLICATIONS,
            ("US:IGV",),
            SectorCapabilityStatus.AVAILABLE,
        ),
        (
            SectorId.DATA_CENTER_NETWORKING_OPTICAL,
            ("US:XLK",),
            SectorCapabilityStatus.PARTIAL,
        ),
        (
            SectorId.INTERNET_DIGITAL_PLATFORMS,
            ("US:XLC",),
            SectorCapabilityStatus.AVAILABLE,
        ),
        (
            SectorId.ROBOTICS_INDUSTRIAL_AUTOMATION,
            ("US:BOTZ",),
            SectorCapabilityStatus.AVAILABLE,
        ),
        (
            SectorId.AUTOMOTIVE_EV_BATTERIES,
            ("US:DRIV",),
            SectorCapabilityStatus.PARTIAL,
        ),
        (
            SectorId.CONSUMER_DISCRETIONARY_RETAIL_BRANDS,
            ("US:XLY",),
            SectorCapabilityStatus.AVAILABLE,
        ),
        (
            SectorId.CONSUMER_STAPLES_FOOD_BEVERAGE,
            ("US:XLP",),
            SectorCapabilityStatus.AVAILABLE,
        ),
        (
            SectorId.INNOVATIVE_PHARMA_BIOTECH,
            ("US:XBI",),
            SectorCapabilityStatus.AVAILABLE,
        ),
        (
            SectorId.MEDICAL_DEVICES_HEALTHCARE_SERVICES,
            ("US:XLV",),
            SectorCapabilityStatus.PARTIAL,
        ),
        (SectorId.FINANCIALS, ("US:XLF",), SectorCapabilityStatus.AVAILABLE),
        (
            SectorId.ENERGY_POWER_UTILITIES_STORAGE,
            ("US:XLE", "US:XLU"),
            SectorCapabilityStatus.PARTIAL,
        ),
        (
            SectorId.MATERIALS_CHEMICALS_METALS,
            ("US:XLB",),
            SectorCapabilityStatus.AVAILABLE,
        ),
        (SectorId.AEROSPACE_DEFENSE, ("US:ITA",), SectorCapabilityStatus.AVAILABLE),
        (
            SectorId.TRANSPORTATION_LOGISTICS,
            ("US:IYT",),
            SectorCapabilityStatus.AVAILABLE,
        ),
        (
            SectorId.REAL_ESTATE_INFRASTRUCTURE,
            ("US:XLRE",),
            SectorCapabilityStatus.PARTIAL,
        ),
    )
    return tuple(
        SectorBenchmarkCandidate(
            sector_id=sector_id,
            candidate_ids=tuple(AssetId(item) for item in candidate_ids),
            expected_status=status,
            source=_BENCHMARK_SOURCE,
            version=_BENCHMARK_VERSION,
        )
        for sector_id, candidate_ids, status in values
    )


def build_current_us_research_memberships_v1() -> tuple[SectorMembership, ...]:
    """Promote the approved five-asset mapping into a non-test universe revision."""

    return tuple(
        membership.model_copy(
            update={
                "source": "phase4_day31_curated_research_universe",
                "version": CURRENT_US_RESEARCH_UNIVERSE_VERSION,
            }
        )
        for membership in build_sector_ontology_seed_v1().memberships
    )


def resolve_validated_benchmark_mappings(
    candidates: Iterable[SectorBenchmarkCandidate],
    *,
    validated_asset_ids: set[str],
    valid_from: date,
) -> tuple[SectorBenchmarkMapping, ...]:
    """Promote only tickers with real price observations into mappings."""

    mappings: list[SectorBenchmarkMapping] = []
    for candidate in candidates:
        validated = tuple(
            item for item in candidate.candidate_ids if str(item) in validated_asset_ids
        )
        if not validated:
            status = SectorCapabilityStatus.MISSING
        elif len(validated) < len(candidate.candidate_ids):
            status = SectorCapabilityStatus.PARTIAL
        else:
            status = candidate.expected_status
        mappings.append(
            SectorBenchmarkMapping(
                sector_id=candidate.sector_id,
                benchmark_ids=validated,
                status=status,
                source="alpaca_market_data:eod_bar_validation",
                valid_from=valid_from,
                version=candidate.version,
            )
        )
    return tuple(mappings)


def _snapshot_id(
    *,
    sector_id: SectorId,
    as_of: date,
    asset_ids: tuple[AssetId, ...],
    benchmark_ids: tuple[AssetId, ...],
    membership_version: str,
) -> str:
    payload = json.dumps(
        {
            "sector_id": sector_id.value,
            "as_of": as_of.isoformat(),
            "asset_ids": [str(item) for item in asset_ids],
            "benchmark_ids": [str(item) for item in benchmark_ids],
            "membership_version": membership_version,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"sector_universe_{digest}"
