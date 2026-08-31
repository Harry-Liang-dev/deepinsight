"""Sector Ontology v1 construction, validation, and seed installation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from src.models.enums import (
    OntologyStatus,
    ResearchScopeType,
    SectorEdgeType,
    SectorId,
    SectorMembershipRole,
    SectorNodeType,
)
from src.models.identifiers import AssetId
from src.repositories.sectors import SectorOntologyRepository
from src.schemas.sectors import (
    IndustryChainDefinition,
    ResearchScopeDefinition,
    SectorDefinition,
    SectorEdge,
    SectorMembership,
    SectorNode,
    SectorOntology,
    SectorOntologySeed,
)

_ONTOLOGY_VERSION = "sector_ontology_v1"
_SEED_VERSION = "phase4_day30_seed_v1"
_VALID_FROM = date(2026, 1, 1)
_SECTOR_NAMES = (
    (SectorId.SEMICONDUCTORS_AI_COMPUTE, "Semiconductors & AI Compute"),
    (SectorId.MEMORY_STORAGE, "Memory & Storage"),
    (
        SectorId.CONSUMER_ELECTRONICS_HARDWARE,
        "Consumer Electronics & Hardware",
    ),
    (SectorId.CLOUD_SOFTWARE_AI_APPLICATIONS, "Cloud / Software / AI Applications"),
    (
        SectorId.DATA_CENTER_NETWORKING_OPTICAL,
        "Data Center / Networking / Optical",
    ),
    (SectorId.INTERNET_DIGITAL_PLATFORMS, "Internet & Digital Platforms"),
    (
        SectorId.ROBOTICS_INDUSTRIAL_AUTOMATION,
        "Robotics & Industrial Automation",
    ),
    (SectorId.AUTOMOTIVE_EV_BATTERIES, "Automotive / EV / Batteries"),
    (
        SectorId.CONSUMER_DISCRETIONARY_RETAIL_BRANDS,
        "Consumer Discretionary / Retail / Brands",
    ),
    (
        SectorId.CONSUMER_STAPLES_FOOD_BEVERAGE,
        "Consumer Staples / Food & Beverage",
    ),
    (SectorId.INNOVATIVE_PHARMA_BIOTECH, "Innovative Pharma & Biotech"),
    (
        SectorId.MEDICAL_DEVICES_HEALTHCARE_SERVICES,
        "Medical Devices & Healthcare Services",
    ),
    (SectorId.FINANCIALS, "Financials"),
    (
        SectorId.ENERGY_POWER_UTILITIES_STORAGE,
        "Energy / Power / Utilities / Energy Storage",
    ),
    (SectorId.MATERIALS_CHEMICALS_METALS, "Materials / Chemicals / Metals"),
    (SectorId.AEROSPACE_DEFENSE, "Aerospace & Defense"),
    (SectorId.TRANSPORTATION_LOGISTICS, "Transportation & Logistics"),
    (SectorId.REAL_ESTATE_INFRASTRUCTURE, "Real Estate & Infrastructure"),
)
_ALLOWED_PARENTS = {
    ResearchScopeType.MACRO: {ResearchScopeType.GLOBAL},
    ResearchScopeType.SECTOR: {ResearchScopeType.MACRO},
    ResearchScopeType.INDUSTRY_CHAIN: {ResearchScopeType.SECTOR},
    ResearchScopeType.ASSET: {
        ResearchScopeType.SECTOR,
        ResearchScopeType.INDUSTRY_CHAIN,
    },
    ResearchScopeType.RESEARCH_EPISODE: {ResearchScopeType.ASSET},
}


class SectorOntologyValidationError(ValueError):
    """Raised when cross-object ontology invariants are invalid."""


class SectorOntologyService:
    """Install and validate the small, non-exhaustive Day30 ontology seed."""

    def __init__(self, repository: SectorOntologyRepository) -> None:
        """Bind the service to the existing DuckDB Repository boundary."""

        self._repository = repository

    def install_v1_seed(self) -> SectorOntologySeed:
        """Validate and idempotently persist the Day30 seed."""

        seed = build_sector_ontology_seed_v1()
        validate_sector_ontology_seed(seed)
        self._repository.install_seed(seed)
        return seed


def build_sector_ontology_v1() -> SectorOntology:
    """Return the stable, complete list of 18 first-level research Sectors."""

    return SectorOntology(
        version=_ONTOLOGY_VERSION,
        sectors=tuple(
            SectorDefinition(
                sector_id=sector_id,
                name=name,
                version=_ONTOLOGY_VERSION,
            )
            for sector_id, name in _SECTOR_NAMES
        ),
    )


def build_sector_ontology_seed_v1() -> SectorOntologySeed:
    """Return a small test seed, not a complete production security universe."""

    chains = _seed_chains()
    memberships = _seed_memberships()
    scopes = _seed_scopes()
    nodes = _seed_nodes()
    edges = _seed_edges()
    seed = SectorOntologySeed(
        ontology=build_sector_ontology_v1(),
        chains=chains,
        memberships=memberships,
        scopes=scopes,
        nodes=nodes,
        edges=edges,
    )
    validate_sector_ontology_seed(seed)
    return seed


def validate_sector_ontology_seed(seed: SectorOntologySeed) -> None:
    """Validate cross-object Sector, Chain, graph, and scope references."""

    expected_sectors = set(SectorId)
    actual_sectors = {item.sector_id for item in seed.ontology.sectors}
    if actual_sectors != expected_sectors or len(seed.ontology.sectors) != 18:
        raise SectorOntologyValidationError(
            "Sector Ontology v1 must contain exactly the stable 18 sectors"
        )
    chain_by_id = _unique_by(
        seed.chains,
        lambda item: item.chain_id,
        label="chain_id",
    )
    for chain in seed.chains:
        if chain.sector_id not in actual_sectors:
            raise SectorOntologyValidationError(
                "Industry Chain references unknown Sector"
            )
    for membership in seed.memberships:
        if membership.sector_id not in actual_sectors:
            raise SectorOntologyValidationError("membership references unknown Sector")
        for chain_id in membership.chain_ids:
            matched_chain = chain_by_id.get(chain_id)
            if matched_chain is None:
                raise SectorOntologyValidationError(
                    "membership references unknown Industry Chain"
                )
            if matched_chain.sector_id is not membership.sector_id:
                raise SectorOntologyValidationError(
                    "membership Industry Chain belongs to a different Sector"
                )
            if not _contains_interval(matched_chain, membership):
                raise SectorOntologyValidationError(
                    "membership validity exceeds its Industry Chain"
                )
    node_by_id = _unique_by(
        seed.nodes,
        lambda item: item.node_id,
        label="node_id",
    )
    _unique_by(seed.edges, lambda item: item.edge_id, label="edge_id")
    for edge in seed.edges:
        if (
            edge.source_node_id not in node_by_id
            or edge.target_node_id not in node_by_id
        ):
            raise SectorOntologyValidationError("edge references unknown Sector node")
        if not _contains_interval(node_by_id[edge.source_node_id], edge) or not (
            _contains_interval(node_by_id[edge.target_node_id], edge)
        ):
            raise SectorOntologyValidationError("edge validity exceeds an endpoint")
    validate_scope_hierarchy(seed.scopes)


def validate_scope_hierarchy(scopes: tuple[ResearchScopeDefinition, ...]) -> None:
    """Validate one rooted, acyclic, type-safe hierarchical scope set."""

    by_id = _unique_by(scopes, lambda item: item.scope_id, label="scope_id")
    roots = [item for item in scopes if item.scope_type is ResearchScopeType.GLOBAL]
    if len(roots) != 1:
        raise SectorOntologyValidationError("scope hierarchy requires one GLOBAL root")
    for scope in scopes:
        if scope.scope_type is ResearchScopeType.GLOBAL:
            continue
        assert scope.parent_scope_id is not None
        parent = by_id.get(scope.parent_scope_id)
        if parent is None:
            raise SectorOntologyValidationError("scope references unknown parent")
    for scope in scopes:
        visited: set[str] = set()
        current: ResearchScopeDefinition | None = scope
        while current is not None:
            if current.scope_id in visited:
                raise SectorOntologyValidationError("scope hierarchy contains a cycle")
            visited.add(current.scope_id)
            parent_id = current.parent_scope_id
            current = by_id.get(parent_id) if parent_id is not None else None
    for scope in scopes:
        if scope.scope_type is ResearchScopeType.GLOBAL:
            continue
        assert scope.parent_scope_id is not None
        parent = by_id[scope.parent_scope_id]
        if parent.scope_type not in _ALLOWED_PARENTS[scope.scope_type]:
            raise SectorOntologyValidationError("invalid parent-child scope types")
        if not _contains_interval(parent, scope):
            raise SectorOntologyValidationError("scope validity exceeds its parent")


def _unique_by[ItemT](
    items: tuple[ItemT, ...],
    key: Callable[[ItemT], str],
    *,
    label: str,
) -> dict[str, ItemT]:
    result: dict[str, ItemT] = {}
    for item in items:
        value = key(item)
        if value in result:
            raise SectorOntologyValidationError(f"duplicate {label}")
        result[value] = item
    return result


def _contains_interval(
    parent: IndustryChainDefinition | SectorNode | ResearchScopeDefinition,
    child: SectorMembership | SectorEdge | ResearchScopeDefinition,
) -> bool:
    """Return whether a child half-open interval is contained by its parent."""

    if child.valid_from < parent.valid_from:
        return False
    if parent.valid_to is None:
        return True
    return child.valid_to is not None and child.valid_to <= parent.valid_to


def _seed_chains() -> tuple[IndustryChainDefinition, ...]:
    return (
        IndustryChainDefinition(
            chain_id="APPLE_CHAIN",
            name="Apple Chain",
            sector_id=SectorId.CONSUMER_ELECTRONICS_HARDWARE,
            description="Test-only Apple hardware and supplier research chain.",
            status=OntologyStatus.ACTIVE,
            valid_from=_VALID_FROM,
            version=_SEED_VERSION,
        ),
        IndustryChainDefinition(
            chain_id="NVIDIA_AI_INFRA",
            name="NVIDIA AI Infrastructure",
            sector_id=SectorId.SEMICONDUCTORS_AI_COMPUTE,
            description="Test-only AI compute infrastructure research chain.",
            status=OntologyStatus.ACTIVE,
            valid_from=_VALID_FROM,
            version=_SEED_VERSION,
        ),
        IndustryChainDefinition(
            chain_id="HBM",
            name="High Bandwidth Memory",
            sector_id=SectorId.MEMORY_STORAGE,
            description="Test-only high-bandwidth-memory research chain.",
            status=OntologyStatus.ACTIVE,
            valid_from=_VALID_FROM,
            version=_SEED_VERSION,
        ),
    )


def _seed_memberships() -> tuple[SectorMembership, ...]:
    values = (
        (
            "US:AAPL",
            SectorId.CONSUMER_ELECTRONICS_HARDWARE,
            "APPLE_CHAIN",
            SectorMembershipRole.CORE,
        ),
        (
            "US:NVDA",
            SectorId.SEMICONDUCTORS_AI_COMPUTE,
            "NVIDIA_AI_INFRA",
            SectorMembershipRole.CORE,
        ),
        (
            "US:AMD",
            SectorId.SEMICONDUCTORS_AI_COMPUTE,
            "NVIDIA_AI_INFRA",
            SectorMembershipRole.COMPETITOR,
        ),
        (
            "US:TSM",
            SectorId.SEMICONDUCTORS_AI_COMPUTE,
            "NVIDIA_AI_INFRA",
            SectorMembershipRole.SUPPLIER,
        ),
        ("US:MU", SectorId.MEMORY_STORAGE, "HBM", SectorMembershipRole.CORE),
    )
    return tuple(
        SectorMembership(
            asset_id=AssetId(asset_id),
            sector_id=sector_id,
            chain_ids=(chain_id,),
            role=role,
            valid_from=_VALID_FROM,
            weight=1.0,
            confidence=0.8,
            source="phase4_day30_test_seed",
            version=_SEED_VERSION,
        )
        for asset_id, sector_id, chain_id, role in values
    )


def _seed_scopes() -> tuple[ResearchScopeDefinition, ...]:
    values = (
        (ResearchScopeType.GLOBAL, "GLOBAL:GLOBAL", None, "Global Research"),
        (ResearchScopeType.MACRO, "MACRO:US", "GLOBAL:GLOBAL", "US Macro"),
        (
            ResearchScopeType.SECTOR,
            "SECTOR:SEMICONDUCTORS_AI",
            "MACRO:US",
            "Semiconductors & AI Compute",
        ),
        (
            ResearchScopeType.SECTOR,
            "SECTOR:MEMORY_STORAGE",
            "MACRO:US",
            "Memory & Storage",
        ),
        (
            ResearchScopeType.SECTOR,
            "SECTOR:CONSUMER_ELECTRONICS",
            "MACRO:US",
            "Consumer Electronics & Hardware",
        ),
        (
            ResearchScopeType.INDUSTRY_CHAIN,
            "CHAIN:NVIDIA_AI_INFRA",
            "SECTOR:SEMICONDUCTORS_AI",
            "NVIDIA AI Infrastructure",
        ),
        (ResearchScopeType.INDUSTRY_CHAIN, "CHAIN:HBM", "SECTOR:MEMORY_STORAGE", "HBM"),
        (
            ResearchScopeType.INDUSTRY_CHAIN,
            "CHAIN:APPLE_CHAIN",
            "SECTOR:CONSUMER_ELECTRONICS",
            "Apple Chain",
        ),
        (ResearchScopeType.ASSET, "ASSET:AAPL", "CHAIN:APPLE_CHAIN", "AAPL"),
        (ResearchScopeType.ASSET, "ASSET:NVDA", "CHAIN:NVIDIA_AI_INFRA", "NVDA"),
        (ResearchScopeType.ASSET, "ASSET:AMD", "CHAIN:NVIDIA_AI_INFRA", "AMD"),
        (ResearchScopeType.ASSET, "ASSET:TSM", "CHAIN:NVIDIA_AI_INFRA", "TSM"),
        (ResearchScopeType.ASSET, "ASSET:MU", "CHAIN:HBM", "MU"),
        (
            ResearchScopeType.RESEARCH_EPISODE,
            "EPISODE:AAPL_DAY30",
            "ASSET:AAPL",
            "AAPL Day30 Research Episode",
        ),
    )
    return tuple(
        ResearchScopeDefinition(
            scope_type=scope_type,
            scope_id=scope_id,
            parent_scope_id=parent_id,
            name=name,
            valid_from=_VALID_FROM,
            version=_SEED_VERSION,
        )
        for scope_type, scope_id, parent_id, name in values
    )


def _seed_nodes() -> tuple[SectorNode, ...]:
    nodes = [
        SectorNode(
            node_id=f"SECTOR:{sector_id.value}",
            node_type=SectorNodeType.SECTOR,
            name=name,
            sector_id=sector_id,
            valid_from=_VALID_FROM,
            source="phase4_day30_test_seed",
            version=_SEED_VERSION,
        )
        for sector_id, name in _SECTOR_NAMES
    ]
    for chain in _seed_chains():
        nodes.append(
            SectorNode(
                node_id=f"CHAIN:{chain.chain_id}",
                node_type=SectorNodeType.INDUSTRY_CHAIN,
                name=chain.name,
                sector_id=chain.sector_id,
                chain_id=chain.chain_id,
                description=chain.description,
                valid_from=chain.valid_from,
                source="phase4_day30_test_seed",
                version=_SEED_VERSION,
            )
        )
    for membership in _seed_memberships():
        ticker = str(membership.asset_id).split(":", maxsplit=1)[1]
        nodes.append(
            SectorNode(
                node_id=f"ASSET:{ticker}",
                node_type=SectorNodeType.ASSET,
                name=ticker,
                sector_id=membership.sector_id,
                asset_id=membership.asset_id,
                valid_from=membership.valid_from,
                source="phase4_day30_test_seed",
                version=_SEED_VERSION,
            )
        )
    return tuple(nodes)


def _seed_edges() -> tuple[SectorEdge, ...]:
    values = (
        (
            "chain-apple-sector",
            "CHAIN:APPLE_CHAIN",
            "SECTOR:S03",
            SectorEdgeType.BELONGS_TO,
        ),
        (
            "chain-nvidia-sector",
            "CHAIN:NVIDIA_AI_INFRA",
            "SECTOR:S01",
            SectorEdgeType.BELONGS_TO,
        ),
        (
            "chain-hbm-sector",
            "CHAIN:HBM",
            "SECTOR:S02",
            SectorEdgeType.BELONGS_TO,
        ),
        (
            "aapl-apple-chain",
            "ASSET:AAPL",
            "CHAIN:APPLE_CHAIN",
            SectorEdgeType.BELONGS_TO,
        ),
        (
            "nvda-nvidia-chain",
            "ASSET:NVDA",
            "CHAIN:NVIDIA_AI_INFRA",
            SectorEdgeType.BELONGS_TO,
        ),
        (
            "amd-nvidia-chain",
            "ASSET:AMD",
            "CHAIN:NVIDIA_AI_INFRA",
            SectorEdgeType.COMPETES_WITH,
        ),
        (
            "tsm-nvidia-chain",
            "ASSET:TSM",
            "CHAIN:NVIDIA_AI_INFRA",
            SectorEdgeType.SUPPLIES,
        ),
        ("mu-hbm-chain", "ASSET:MU", "CHAIN:HBM", SectorEdgeType.BELONGS_TO),
        (
            "hbm-nvidia-chain",
            "CHAIN:HBM",
            "CHAIN:NVIDIA_AI_INFRA",
            SectorEdgeType.SUPPLIES,
        ),
    )
    return tuple(
        SectorEdge(
            edge_id=edge_id,
            source_node_id=source_id,
            target_node_id=target_id,
            edge_type=edge_type,
            confidence=0.8,
            source="phase4_day30_test_seed",
            valid_from=_VALID_FROM,
            version=_SEED_VERSION,
        )
        for edge_id, source_id, target_id, edge_type in values
    )
