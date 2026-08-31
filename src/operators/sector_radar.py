"""Deterministic and auditable Sector Anomaly Radar rules."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, time

from src.models.enums import (
    AnomalyDirection,
    EventSeverity,
    SectorAnomalyStatus,
    SectorAnomalyType,
    SectorCapabilityStatus,
    SectorId,
    SectorNodeType,
)
from src.models.identifiers import AssetId
from src.schemas.market_data import (
    CorporateEventRecord,
    EodBarRecord,
    NewsEvidenceRecord,
)
from src.schemas.sectors import (
    SectorAnomalyEvent,
    SectorEdge,
    SectorMacroSnapshot,
    SectorMembership,
    SectorNode,
    SectorResearchSnapshot,
)

_VERSION = "sector_radar_v1"
_PRICE_Z_THRESHOLD = 2.5
_VOLUME_RATIO_THRESHOLD = 2.0
_BREADTH_DIVERGENCE_THRESHOLD = 0.35
_DISPERSION_THRESHOLD = 0.08
_MACRO_RELATIVE_CHANGE_THRESHOLD = 0.10
_MACRO_CORRELATION_THRESHOLD = 0.20
_MATERIAL_NEWS_TERMS = (
    "acquisition",
    "earnings",
    "guidance",
    "investigation",
    "lawsuit",
    "merger",
    "recall",
    "restructuring",
)


class SectorRadarInputError(ValueError):
    """Raised when Radar input violates identity or point-in-time safety."""


class SectorAnomalyRadar:
    """Detect simple Sector anomalies without LLM or investment judgment."""

    version = _VERSION

    def detect(
        self,
        *,
        sector_state: SectorResearchSnapshot,
        macro_state: SectorMacroSnapshot,
        bars_by_asset: Mapping[str, Sequence[EodBarRecord]],
        corporate_events: Sequence[CorporateEventRecord] = (),
        news: Sequence[NewsEvidenceRecord] = (),
        memberships: Sequence[SectorMembership] = (),
        nodes: Sequence[SectorNode] = (),
        edges: Sequence[SectorEdge] = (),
    ) -> tuple[SectorAnomalyEvent, ...]:
        """Return stable anomaly events known by the Sector snapshot cutoff."""

        as_of = datetime.combine(sector_state.as_of, time.max, tzinfo=UTC)
        _validate_inputs(
            sector_state=sector_state,
            macro_state=macro_state,
            bars_by_asset=bars_by_asset,
            corporate_events=corporate_events,
            news=news,
            memberships=memberships,
            as_of=as_of,
        )
        events: list[SectorAnomalyEvent] = []
        events.extend(
            _price_volume_events(
                sector_state.sector_id,
                bars_by_asset,
                memberships,
                as_of,
            )
        )
        breadth = _breadth_event(sector_state, as_of)
        if breadth is not None:
            events.append(breadth)
        events.extend(
            _corporate_events(
                sector_state.sector_id,
                corporate_events,
                memberships,
                as_of,
            )
        )
        events.extend(_news_events(sector_state.sector_id, news, memberships, as_of))
        events.extend(_macro_events(macro_state, as_of))
        base_events = tuple(events)
        events.extend(
            _propagation_candidates(
                base_events,
                memberships=memberships,
                nodes=nodes,
                edges=edges,
                as_of=as_of,
            )
        )
        return tuple(sorted(events, key=lambda item: (item.event_time, item.event_id)))


def _price_volume_events(
    sector_id: SectorId,
    bars_by_asset: Mapping[str, Sequence[EodBarRecord]],
    memberships: Sequence[SectorMembership],
    as_of: datetime,
) -> list[SectorAnomalyEvent]:
    output: list[SectorAnomalyEvent] = []
    for asset_key, raw_bars in sorted(bars_by_asset.items()):
        bars = sorted(raw_bars, key=lambda item: item.trade_date)
        if not bars:
            continue
        asset_id = bars[0].asset_id
        closes = [
            item.adj_close if item.adj_close is not None else item.close
            for item in bars
        ]
        if len(bars) < 22 or any(value is None for value in closes[-62:]):
            continue
        values = [float(value) for value in closes if value is not None]
        returns = [
            values[index] / values[index - 1] - 1.0 for index in range(1, len(values))
        ]
        history = returns[-61:-1]
        latest_return = returns[-1]
        price_z = _zscore(latest_return, history)
        previous_volumes = [
            float(item.volume)
            for item in bars[-21:-1]
            if item.volume is not None and item.volume > 0
        ]
        volume_ratio = None
        if bars[-1].volume is not None and previous_volumes:
            volume_ratio = float(bars[-1].volume) / statistics.median(previous_volumes)
        if abs(price_z) < _PRICE_Z_THRESHOLD and (
            volume_ratio is None or volume_ratio < _VOLUME_RATIO_THRESHOLD
        ):
            continue
        severity = (
            EventSeverity.HIGH
            if abs(price_z) >= 4.0 or (volume_ratio or 0.0) >= 3.0
            else EventSeverity.MEDIUM
        )
        chains = _asset_chains(asset_id, memberships)
        evidence_id = f"eod_bar:{asset_id}:{bars[-1].trade_date.isoformat()}"
        available_at = _as_utc(bars[-1].ingestion_ts)
        summary = (
            f"{asset_id} price/volume anomaly: daily_return={latest_return:.8f}, "
            f"return_z={price_z:.4f}, volume_ratio="
            f"{('missing' if volume_ratio is None else f'{volume_ratio:.4f}')}"
        )
        output.append(
            _event(
                event_type=SectorAnomalyType.PRICE_VOLUME,
                sector_id=sector_id,
                chain_ids=chains,
                source_assets=(asset_id,),
                affected_assets=(asset_id,),
                direction=(
                    AnomalyDirection.POSITIVE
                    if latest_return > 0
                    else AnomalyDirection.NEGATIVE
                ),
                severity=severity,
                confidence=min(
                    1.0, max(abs(price_z) / 5.0, (volume_ratio or 0.0) / 4.0)
                ),
                event_time=datetime.combine(bars[-1].trade_date, time.min, tzinfo=UTC),
                published_at=datetime.combine(
                    bars[-1].trade_date, time.min, tzinfo=UTC
                ),
                available_at=available_at,
                ingested_at=available_at,
                as_of=as_of,
                evidence_ids=(evidence_id,),
                summary=summary,
            )
        )
    return output


def _breadth_event(
    state: SectorResearchSnapshot,
    as_of: datetime,
) -> SectorAnomalyEvent | None:
    breadth = state.breadth_state
    pairs = (
        (breadth.pct_above_sma20.value, breadth.pct_above_sma60.value),
        (breadth.pct_positive_5d.value, breadth.pct_positive_20d.value),
    )
    divergences = [
        abs(left - right)
        for left, right in pairs
        if left is not None and right is not None
    ]
    dispersion = breadth.return_dispersion_20d.value
    if max(divergences, default=0.0) < _BREADTH_DIVERGENCE_THRESHOLD and (
        dispersion is None or dispersion < _DISPERSION_THRESHOLD
    ):
        return None
    return _event(
        event_type=SectorAnomalyType.BREADTH,
        sector_id=state.sector_id,
        direction=AnomalyDirection.MIXED,
        severity=EventSeverity.MEDIUM,
        confidence=min(1.0, max(max(divergences, default=0.0), dispersion or 0.0)),
        event_time=as_of,
        published_at=as_of,
        available_at=as_of,
        ingested_at=as_of,
        as_of=as_of,
        evidence_ids=(state.snapshot_id,),
        summary=(
            "Sector breadth divergence detected from deterministic breadth state; "
            f"max_divergence={max(divergences, default=0.0):.4f}, "
            "return_dispersion_20d="
            f"{('missing' if dispersion is None else f'{dispersion:.4f}')}"
        ),
    )


def _corporate_events(
    sector_id: SectorId,
    records: Sequence[CorporateEventRecord],
    memberships: Sequence[SectorMembership],
    as_of: datetime,
) -> list[SectorAnomalyEvent]:
    output: list[SectorAnomalyEvent] = []
    for record in records:
        if record.asset_id is None:
            continue
        tags = record.tags_json or {}
        actual = _number(tags.get("actual_eps"))
        expected = _number(tags.get("expected_eps"))
        is_earnings = "earning" in record.event_type.casefold()
        if (
            is_earnings
            and actual is not None
            and expected is not None
            and expected != 0.0
        ):
            surprise = (actual - expected) / abs(expected)
            if abs(surprise) < 0.05:
                continue
            event_type = SectorAnomalyType.EARNINGS
            direction = (
                AnomalyDirection.POSITIVE if surprise > 0 else AnomalyDirection.NEGATIVE
            )
            summary = (
                f"{record.asset_id} earnings anomaly: actual_eps={actual:.8f}, "
                f"expected_eps={expected:.8f}, surprise={surprise:.8f}"
            )
        elif record.severity in {EventSeverity.HIGH, EventSeverity.CRITICAL}:
            event_type = SectorAnomalyType.NEWS_EVENT
            direction = AnomalyDirection.UNKNOWN
            summary = f"Material company event for {record.asset_id}: {record.title}"
        else:
            continue
        output.append(
            _event(
                event_type=event_type,
                sector_id=sector_id,
                chain_ids=_asset_chains(record.asset_id, memberships),
                source_assets=(record.asset_id,),
                affected_assets=(record.asset_id,),
                direction=direction,
                severity=record.severity,
                confidence=0.9 if event_type is SectorAnomalyType.EARNINGS else 0.75,
                event_time=_as_utc(record.event_date),
                published_at=_as_utc(record.event_date),
                available_at=_as_utc(record.event_date),
                ingested_at=_as_utc(record.event_date),
                as_of=as_of,
                evidence_ids=(
                    record.source_document_id or f"corporate_event:{record.event_id}",
                ),
                summary=summary,
            )
        )
    return output


def _news_events(
    sector_id: SectorId,
    records: Sequence[NewsEvidenceRecord],
    memberships: Sequence[SectorMembership],
    as_of: datetime,
) -> list[SectorAnomalyEvent]:
    output: list[SectorAnomalyEvent] = []
    for record in records:
        normalized = f"{record.headline} {record.summary or ''}".casefold()
        if not any(term in normalized for term in _MATERIAL_NEWS_TERMS):
            continue
        available_at = max(_as_utc(record.created_at), _as_utc(record.ingestion_ts))
        output.append(
            _event(
                event_type=SectorAnomalyType.NEWS_EVENT,
                sector_id=sector_id,
                chain_ids=_asset_chains(record.asset_id, memberships),
                source_assets=(record.asset_id,),
                affected_assets=(record.asset_id,),
                direction=AnomalyDirection.UNKNOWN,
                severity=EventSeverity.MEDIUM,
                confidence=0.65,
                event_time=_as_utc(record.created_at),
                published_at=_as_utc(record.created_at),
                available_at=available_at,
                ingested_at=_as_utc(record.ingestion_ts),
                as_of=as_of,
                evidence_ids=(f"news:{record.news_id}",),
                summary=(
                    f"Material news candidate for {record.asset_id}: "
                    f"{record.headline}"
                ),
            )
        )
    return output


def _macro_events(
    state: SectorMacroSnapshot, as_of: datetime
) -> list[SectorAnomalyEvent]:
    signals = {
        signal.series_id: signal
        for dimension in (
            state.cycle_state.rates,
            state.cycle_state.inflation,
            state.cycle_state.labor,
            state.cycle_state.growth,
            state.cycle_state.financial_stress,
        )
        for signal in dimension.signals
    }
    output: list[SectorAnomalyEvent] = []
    for estimate in state.macro_sensitivity.estimates:
        signal = signals.get(estimate.series_id)
        if (
            signal is None
            or signal.change_3m is None
            or estimate.status is not SectorCapabilityStatus.AVAILABLE
            or estimate.beta is None
            or estimate.correlation is None
        ):
            continue
        relative_change = signal.change_3m / max(abs(signal.latest_value), 1.0)
        if (
            abs(relative_change) < _MACRO_RELATIVE_CHANGE_THRESHOLD
            or abs(estimate.correlation) < _MACRO_CORRELATION_THRESHOLD
        ):
            continue
        propagated = estimate.beta * signal.change_3m
        direction = (
            AnomalyDirection.POSITIVE if propagated > 0 else AnomalyDirection.NEGATIVE
        )
        event_time = datetime.combine(
            signal.latest_observation_date, time.min, tzinfo=UTC
        )
        output.append(
            _event(
                event_type=SectorAnomalyType.MACRO_SHOCK,
                sector_id=state.sector_id,
                direction=direction,
                severity=(
                    EventSeverity.HIGH
                    if abs(relative_change) >= 0.25
                    else EventSeverity.MEDIUM
                ),
                confidence=min(1.0, abs(estimate.correlation)),
                event_time=event_time,
                published_at=event_time,
                available_at=as_of,
                ingested_at=as_of,
                as_of=as_of,
                evidence_ids=(
                    state.snapshot_id,
                    f"macro:{estimate.series_id}:{signal.latest_observation_date.isoformat()}",
                ),
                summary=(
                    f"Macro-to-sector anomaly candidate: series={estimate.series_id}, "
                    f"change_3m={signal.change_3m:.8f}, beta={estimate.beta:.8f}, "
                    f"correlation={estimate.correlation:.8f}"
                ),
            )
        )
    return output


def _propagation_candidates(
    events: Sequence[SectorAnomalyEvent],
    *,
    memberships: Sequence[SectorMembership],
    nodes: Sequence[SectorNode],
    edges: Sequence[SectorEdge],
    as_of: datetime,
) -> list[SectorAnomalyEvent]:
    node_by_id = {item.node_id: item for item in nodes}
    connected_chains: dict[str, set[str]] = {}
    for edge in edges:
        source = node_by_id.get(edge.source_node_id)
        target = node_by_id.get(edge.target_node_id)
        if source is None or target is None:
            continue
        asset_node = source if source.node_type is SectorNodeType.ASSET else target
        chain_node = (
            target if target.node_type is SectorNodeType.INDUSTRY_CHAIN else source
        )
        if asset_node.asset_id is not None and chain_node.chain_id is not None:
            connected_chains.setdefault(str(asset_node.asset_id), set()).add(
                chain_node.chain_id
            )
    output: list[SectorAnomalyEvent] = []
    for source_event in events:
        if source_event.event_type is SectorAnomalyType.SUPPLY_CHAIN_PROPAGATION:
            continue
        chains = set(source_event.chain_ids)
        for asset_id in source_event.source_asset_ids:
            chains.update(connected_chains.get(str(asset_id), set()))
        if not chains:
            continue
        source_ids = {str(item) for item in source_event.source_asset_ids}
        affected = {
            str(item.asset_id): item.asset_id
            for item in memberships
            if set(item.chain_ids) & chains and str(item.asset_id) not in source_ids
        }
        for asset_key, asset_chains in connected_chains.items():
            if asset_chains & chains and asset_key not in source_ids:
                affected.setdefault(asset_key, AssetId(asset_key))
        if not affected:
            continue
        ordered_chains = tuple(sorted(chains))
        output.append(
            _event(
                event_type=SectorAnomalyType.SUPPLY_CHAIN_PROPAGATION,
                sector_id=source_event.sector_id,
                chain_ids=ordered_chains,
                source_assets=source_event.source_asset_ids,
                affected_assets=tuple(affected[key] for key in sorted(affected)),
                direction=AnomalyDirection.UNKNOWN,
                severity=source_event.severity,
                confidence=min(source_event.confidence, 0.8),
                event_time=source_event.event_time,
                published_at=source_event.published_at,
                available_at=source_event.available_at,
                ingested_at=source_event.ingested_at,
                as_of=as_of,
                evidence_ids=source_event.source_evidence_ids,
                summary=(
                    f"Supply-chain propagation candidate from {source_event.event_id} "
                    f"through {', '.join(ordered_chains)}"
                ),
                propagation_hypothesis=(
                    "Ontology membership or graph edges identify potentially affected "
                    "assets; impact direction requires subsequent research."
                ),
                status=SectorAnomalyStatus.PROPAGATION_CANDIDATE,
            )
        )
    return output


def _event(
    *,
    event_type: SectorAnomalyType,
    sector_id: SectorId,
    direction: AnomalyDirection,
    severity: EventSeverity,
    confidence: float,
    event_time: datetime,
    published_at: datetime,
    available_at: datetime,
    ingested_at: datetime,
    as_of: datetime,
    evidence_ids: tuple[str, ...],
    summary: str,
    chain_ids: tuple[str, ...] = (),
    source_assets: tuple[AssetId, ...] = (),
    affected_assets: tuple[AssetId, ...] = (),
    propagation_hypothesis: str | None = None,
    status: SectorAnomalyStatus = SectorAnomalyStatus.DETECTED,
) -> SectorAnomalyEvent:
    content = {
        "event_type": event_type.value,
        "sector_id": sector_id.value,
        "chain_ids": sorted(chain_ids),
        "source_asset_ids": sorted(str(item) for item in source_assets),
        "affected_asset_ids": sorted(str(item) for item in affected_assets),
        "event_time": event_time.isoformat(),
        "evidence_ids": sorted(evidence_ids),
        "version": _VERSION,
    }
    digest = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]
    return SectorAnomalyEvent(
        event_id=f"sector_anomaly_{digest}",
        event_type=event_type,
        sector_id=sector_id,
        chain_ids=tuple(sorted(set(chain_ids))),
        source_asset_ids=_unique_assets(source_assets),
        affected_asset_ids=_unique_assets(affected_assets),
        direction=direction,
        severity=severity,
        confidence=confidence,
        event_time=event_time,
        published_at=published_at,
        available_at=available_at,
        ingested_at=ingested_at,
        as_of=as_of,
        source_evidence_ids=tuple(sorted(set(evidence_ids))),
        summary=summary,
        propagation_hypothesis=propagation_hypothesis,
        status=status,
        version=_VERSION,
    )


def _asset_chains(
    asset_id: AssetId,
    memberships: Sequence[SectorMembership],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                chain_id
                for item in memberships
                if item.asset_id == asset_id
                for chain_id in item.chain_ids
            }
        )
    )


def _unique_assets(values: Sequence[AssetId]) -> tuple[AssetId, ...]:
    by_id = {str(item): item for item in values}
    return tuple(by_id[key] for key in sorted(by_id))


def _zscore(value: float, history: Sequence[float]) -> float:
    if len(history) < 20:
        return 0.0
    deviation = statistics.stdev(history)
    return (
        0.0
        if math.isclose(deviation, 0.0)
        else (value - statistics.mean(history)) / deviation
    )


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _validate_inputs(
    *,
    sector_state: SectorResearchSnapshot,
    macro_state: SectorMacroSnapshot,
    bars_by_asset: Mapping[str, Sequence[EodBarRecord]],
    corporate_events: Sequence[CorporateEventRecord],
    news: Sequence[NewsEvidenceRecord],
    memberships: Sequence[SectorMembership],
    as_of: datetime,
) -> None:
    if (sector_state.sector_id, sector_state.as_of) != (
        macro_state.sector_id,
        macro_state.as_of,
    ):
        raise SectorRadarInputError("Sector state and macro state identities differ")
    as_of_date = as_of.date()
    for asset_id, records in bars_by_asset.items():
        if any(str(item.asset_id) != asset_id for item in records):
            raise SectorRadarInputError("bar mapping contains a different asset")
        if any(
            item.trade_date > as_of_date or _as_utc(item.ingestion_ts) > as_of
            for item in records
        ):
            raise SectorRadarInputError("future price input is not allowed")
    for corporate_record in corporate_events:
        if _as_utc(corporate_record.event_date) > as_of:
            raise SectorRadarInputError("future corporate event is not allowed")
    for news_record in news:
        if (
            _as_utc(news_record.created_at) > as_of
            or _as_utc(news_record.ingestion_ts) > as_of
        ):
            raise SectorRadarInputError("future news input is not allowed")
    for membership in memberships:
        if membership.sector_id != sector_state.sector_id:
            raise SectorRadarInputError("membership is outside the Radar Sector")
        if not membership.is_effective(as_of_date):
            raise SectorRadarInputError("membership is not effective at as_of")
