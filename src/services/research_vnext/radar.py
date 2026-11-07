"""Selectable cards over existing Sector Radar events, never new trades."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from src.memory.vnext import content_sha256
from src.memory.vnext_contracts import (
    ArtifactRef,
    Envelope,
    Frozen,
    ResearchMandate,
    Role,
    Scope,
    Text,
)
from src.models.enums import Market, ResearchScopeType, SectorAnomalyType
from src.models.identifiers import AssetId
from src.operators.sector_radar import SectorAnomalyRadar
from src.schemas.sector_context import SectorContextBundle
from src.schemas.sectors import SectorAnomalyEvent, SectorMembership
from src.services.research_vnext.contracts import (
    Coverage,
    MarketDatum,
    RetainedReader,
    artifact,
    resolve,
)

CandidateKind = Literal[
    "INDUSTRY_CATALYST",
    "COMPANY_EVENT",
    "PRICE_VOLUME_FLOW_ANOMALY",
    "VALUATION_OPPORTUNITY",
]
Selection = Literal["SELECT_FOR_RESEARCH", "WATCH", "DEFER", "REJECT"]


class RadarDataInput(Envelope):
    """Separate Radar input using existing typed events and native receipts."""

    schema_version: Literal["g86_radar_data_input_v1"] = "g86_radar_data_input_v1"
    events: tuple[SectorAnomalyEvent, ...]
    event_refs: tuple[ArtifactRef, ...]
    measurement_refs: tuple[ArtifactRef, ...] = ()
    memberships: tuple[SectorMembership, ...] = ()
    membership_refs: tuple[ArtifactRef, ...] = ()
    strategy_priority: Literal["P0", "P1", "P2"] = "P0"
    include_relative_value_candidates: bool = False

    @model_validator(mode="after")
    def population(self) -> Self:
        """No silent event dropping or inference from unbound catalog rows."""
        if len(self.memberships) != len(self.membership_refs):
            raise ValueError("MEMBERSHIP_POPULATION_MISMATCH")
        for member, ref in zip(self.memberships, self.membership_refs, strict=True):
            if ref.sha256_digest != content_sha256(member):
                raise ValueError("MEMBERSHIP_IDENTITY_MISMATCH")
            ref.require_recorded_by(self.research_as_of)
        if len(self.events) != len(self.event_refs):
            raise ValueError("RADAR_EVENT_POPULATION_MISMATCH")
        if len({e.event_id for e in self.events}) != len(self.events):
            raise ValueError("DUPLICATE_RADAR_EVENT")
        for event, ref in zip(self.events, self.event_refs, strict=True):
            if ref.artifact_id != event.event_id or (
                ref.sha256_digest != content_sha256(event)
            ):
                raise ValueError("RADAR_EVENT_IDENTITY_MISMATCH")
            if event.as_of != self.research_as_of:
                raise ValueError("RADAR_CUTOFF_MISMATCH")
            ref.require_recorded_by(self.research_as_of)
        return self


class OpportunityCard(Envelope):
    """Human-selectable view of an existing event, not another registry."""

    schema_version: Literal["g86_opportunity_card_v1"] = "g86_opportunity_card_v1"
    opportunity_kind: CandidateKind
    strategy_priority: Literal["P0", "P1"]
    market: Market
    sector_id: Text | None
    chain_ids: tuple[str, ...]
    asset_ids: tuple[AssetId, ...] = Field(min_length=1)
    trigger: SectorAnomalyEvent
    trigger_ref: ArtifactRef
    price_volume: Coverage
    fund_flow: Coverage
    relative_value: Coverage
    liquidity: Coverage
    capacity: Coverage
    limit_up_down: Coverage
    consecutive_limits: Coverage
    research_priority: Literal["HIGH", "NORMAL"]
    data_quality: Literal["AVAILABLE", "PARTIAL"]
    review_status: Literal["UNREVIEWED"] = "UNREVIEWED"
    membership_is_benefit: Literal[False] = False


class SelectionEvent(Frozen):
    """Externally retained human decision or preauthorized research Mandate."""

    schema_version: Literal["g86_selection_event_v1"] = "g86_selection_event_v1"
    opportunity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    actor_id: Text
    selected_at: datetime
    selection: Selection
    authority_kind: Literal["HUMAN_SELECTION", "PREAUTHORIZED_MANDATE"]
    scopes: tuple[Scope, ...] = Field(min_length=1)
    roles: tuple[Role, ...] = Field(min_length=1)
    expires_at: datetime


def require_mandate(
    mandate: ResearchMandate,
    *,
    role: Role,
    scope: Scope,
    at: datetime,
    reader: RetainedReader,
) -> None:
    """Resolve actual external authority, including WATCH/REJECT and expiry."""
    decision = SelectionEvent.model_validate_json(
        resolve(mandate.authorization, reader)
    )
    if (
        decision.selection != "SELECT_FOR_RESEARCH"
        or decision.authority_kind != mandate.selection
        or decision.actor_id != mandate.authorization.owner
        or decision.opportunity_sha256 != mandate.opportunity.sha256_digest
        or decision.scopes != mandate.allowed_scopes
        or decision.roles != mandate.allowed_roles
        or decision.expires_at != mandate.expires_at
        or decision.selected_at != mandate.authorization.available_at
        or decision.selected_at > mandate.created_at
        or mandate.created_at > at
        or mandate.expires_at <= at
        or role not in mandate.allowed_roles
        or scope not in mandate.allowed_scopes
    ):
        raise ValueError("UNRESOLVED_RESEARCH_MANDATE")
    resolve(mandate.opportunity, reader)
    mandate.authorization.require_recorded_by(at)


def selected_mandate(
    card: OpportunityCard,
    selection: ArtifactRef,
    *,
    at: datetime,
    reader: RetainedReader,
    member_contexts: tuple[ArtifactRef, ...] = (),
) -> ResearchMandate:
    """Create a research-only Mandate after a real external selection resolves."""
    event = SelectionEvent.model_validate_json(resolve(selection, reader))
    card_ref = artifact(card)
    resolve(card_ref, reader)
    permitted_scopes = [card.scope]
    if member_contexts and card.scope.scope_type.value != "industry_chain":
        raise ValueError("CHAIN_SELECTION_REQUIRED_FOR_MEMBER_SCOPES")
    for context_ref in member_contexts:
        context_ref.require_recorded_by(at)
        context = SectorContextBundle.model_validate_json(resolve(context_ref, reader))
        if (
            card.scope.scope_id.removeprefix("CHAIN:") not in context.active_chain_ids
            or context.research_as_of != card.research_as_of
        ):
            raise ValueError("SELECTED_CHAIN_MEMBERSHIP_UNPROVEN")
        permitted_scopes.append(
            Scope(
                scope_type=ResearchScopeType.ASSET,
                scope_id="ASSET:" + str(context.asset_id),
            )
        )
    if len(set(s.sha256 for s in permitted_scopes)) != len(permitted_scopes):
        raise ValueError("DUPLICATE_SELECTION_SCOPE")
    if (
        event.opportunity_sha256 != card.sha256
        or event.selection != "SELECT_FOR_RESEARCH"
        or event.actor_id != selection.owner
        or event.selected_at != selection.available_at
        or event.selected_at < card.created_at
        or event.selected_at > at
        or event.expires_at <= at
        or event.scopes != tuple(permitted_scopes)
    ):
        raise ValueError("OPPORTUNITY_NOT_SELECTED")
    return ResearchMandate(
        owner=event.actor_id,
        record_id="mandate:" + selection.sha256,
        revision=1,
        created_at=at,
        research_as_of=at,
        scope=card.scope,
        source_refs=(card_ref, selection, *member_contexts),
        opportunity=card_ref,
        authorization=selection,
        selection=event.authority_kind,
        allowed_scopes=event.scopes,
        allowed_roles=event.roles,
        expires_at=event.expires_at,
    )


class VNextSectorRadar(SectorAnomalyRadar):
    """Reuse detect unchanged; project its retained events into opt-in cards."""

    def opportunity_cards(
        self,
        data: RadarDataInput,
        *,
        reader: RetainedReader,
        validate_measurement: Callable[[MarketDatum], None] | None = None,
    ) -> tuple[OpportunityCard, ...]:
        """Validate all supplied bytes first, then project a bounded population."""
        data = RadarDataInput.model_validate_json(data.model_dump_json())
        if data.strategy_priority == "P2":
            raise ValueError("COMMODITY_SPREAD_RESERVED_NOT_EQUITY_EXECUTION")
        for ref in (*data.source_refs, *data.event_refs, *data.membership_refs):
            resolve(ref, reader)
        measurements = []
        for ref in data.measurement_refs:
            ref.require_recorded_by(data.research_as_of)
            value = MarketDatum.model_validate_json(resolve(ref, reader))
            for source in (value.source_receipt, value.operator):
                if source is not None:
                    source.require_recorded_by(data.research_as_of)
                    resolve(source, reader)
            if validate_measurement is None:
                raise ValueError("MARKET_CAPABILITY_RESOLVER_REQUIRED")
            validate_measurement(value)
            measurements.append(value)
        if data.strategy_priority == "P1" and not any(
            m.category == "TREND_VALIDATION" for m in measurements
        ):
            raise ValueError("TREND_INDEPENDENT_VALIDATION_MISSING")
        all_assets = {
            str(a)
            for event in data.events
            for a in (*event.source_asset_ids, *event.affected_asset_ids)
        }
        if any(str(m.asset_id) not in all_assets for m in measurements):
            raise ValueError("UNBOUND_MEASUREMENT_ASSET")
        cards = []
        for event, event_ref in zip(data.events, data.event_refs, strict=True):
            if event.sector_id is None and data.scope.scope_type.value != "asset":
                raise ValueError("UNVERIFIED_SECTOR_REQUIRES_ASSET_SCOPE")
            if not set(event.source_evidence_ids) <= {
                ref.artifact_id for ref in data.source_refs
            }:
                raise ValueError("RADAR_NATIVE_SOURCE_MISSING")
            assets = tuple(
                {
                    str(a): a
                    for a in (*event.source_asset_ids, *event.affected_asset_ids)
                }.values()
            )
            if not assets:
                assets = tuple(
                    {
                        str(m.asset_id): m.asset_id
                        for m in data.memberships
                        if m.sector_id == event.sector_id
                        and m.is_effective(data.research_as_of.date())
                        and (
                            data.scope.scope_type.value != "asset"
                            or data.scope.scope_id
                            in {
                                "ASSET:" + str(m.asset_id),
                                "ASSET:" + str(m.asset_id).split(":", 1)[1],
                            }
                        )
                    }.values()
                )
            if not assets:
                raise ValueError("RADAR_RESEARCH_POPULATION_MISSING")
            markets = {asset.market for asset in assets}
            if len(markets) != 1:
                raise ValueError("MIXED_MARKET_CARD_REQUIRES_EXPLICIT_SPLIT")
            market = assets[0].market
            if data.scope.scope_type.value == "asset" and data.scope.scope_id not in {
                name
                for a in assets
                for name in ("ASSET:" + str(a), "ASSET:" + str(a).split(":", 1)[1])
            }:
                raise ValueError("CARD_ASSET_SCOPE_MISMATCH")
            if (
                data.scope.scope_type.value == "industry_chain"
                and data.scope.scope_id.removeprefix("CHAIN:") not in event.chain_ids
            ):
                raise ValueError("CARD_CHAIN_SCOPE_MISMATCH")

            def coverage(category: str) -> Coverage:
                selected = tuple(
                    m
                    for m in measurements
                    if m.category == category and m.asset_id in assets
                )
                if (
                    category in {"LIMIT_UP_DOWN", "CONSECUTIVE_LIMITS"}
                    and market != Market.CN
                ):
                    return Coverage(
                        status="NOT_APPLICABLE",
                        reason="Non-CN market; no assumed limit regime",
                    )
                return Coverage(
                    status="AVAILABLE" if selected else "MISSING",
                    measurements=selected,
                    reason=(
                        "Resolved native/Quant receipts"
                        if selected
                        else "No qualifying source; never inferred from OHLCV"
                    ),
                )

            kind: CandidateKind
            if event.event_type == SectorAnomalyType.PRICE_VOLUME:
                kind = "PRICE_VOLUME_FLOW_ANOMALY"
            elif event.event_type in {
                SectorAnomalyType.EARNINGS,
                SectorAnomalyType.NEWS_EVENT,
            }:
                kind = "COMPANY_EVENT"
            else:
                kind = "INDUSTRY_CATALYST"
            kinds: list[CandidateKind] = [kind]
            if (
                data.include_relative_value_candidates
                and coverage("RELATIVE_VALUE").status == "AVAILABLE"
            ):
                kinds.append("VALUATION_OPPORTUNITY")
            for candidate_kind in kinds:
                cards.append(
                    OpportunityCard(
                        owner="sector_radar",
                        record_id=f"card:{event.event_id}:{candidate_kind}",
                        revision=1,
                        created_at=data.created_at,
                        research_as_of=data.research_as_of,
                        scope=data.scope,
                        source_refs=tuple(
                            dict.fromkeys(
                                (
                                    *data.source_refs,
                                    *data.event_refs,
                                    *data.measurement_refs,
                                )
                            )
                        ),
                        opportunity_kind=candidate_kind,
                        strategy_priority=data.strategy_priority,
                        market=market,
                        sector_id=(event.sector_id.value if event.sector_id else None),
                        chain_ids=event.chain_ids,
                        asset_ids=assets,
                        trigger=event,
                        trigger_ref=event_ref,
                        price_volume=coverage("PRICE_VOLUME"),
                        fund_flow=coverage("FUND_FLOW"),
                        relative_value=coverage("RELATIVE_VALUE"),
                        liquidity=coverage("LIQUIDITY"),
                        capacity=coverage("CAPACITY"),
                        limit_up_down=coverage("LIMIT_UP_DOWN"),
                        consecutive_limits=coverage("CONSECUTIVE_LIMITS"),
                        research_priority=(
                            "HIGH"
                            if event.severity.value in {"high", "critical"}
                            else "NORMAL"
                        ),
                        data_quality=(
                            "PARTIAL"
                            if any(
                                coverage(c).status == "MISSING"
                                for c in (
                                    "PRICE_VOLUME",
                                    "FUND_FLOW",
                                    "RELATIVE_VALUE",
                                    "LIQUIDITY",
                                    "CAPACITY",
                                )
                            )
                            else "AVAILABLE"
                        ),
                    )
                )
        return tuple(cards)
