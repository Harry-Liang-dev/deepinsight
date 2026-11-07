"""G93 opt-in retained-source composition of the existing Radar and G86 cards.

No network or Agent entrypoint. Source bytes are checked against a frozen local
inventory before normalization. Unknown membership never becomes Sector authority.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.memory.vnext_contracts import ArtifactRef, Scope
from src.models.enums import (
    AnomalyDirection,
    EventSeverity,
    ResearchScopeType,
    SectorAnomalyStatus,
    SectorAnomalyType,
)
from src.models.identifiers import AssetId
from src.schemas.market_data import EodBarRecord
from src.schemas.sectors import SectorAnomalyEvent
from src.services.research_vnext.contracts import artifact
from src.services.research_vnext.radar import RadarDataInput, VNextSectorRadar
from src.services.research_vnext.real_native_source import NativeSource
from src.services.research_vnext.source_adapters import recompute_l0


def encoded(value: Any) -> bytes:
    """Canonical development artifact bytes, not an independent signature."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def sha(raw: bytes) -> str:
    """Full byte identity."""
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path) -> Any:
    """Read local retained JSON only."""
    return json.loads(path.read_bytes())


def save(path: Path, value: Any) -> None:
    """Append a new immutable artifact; refuse existing bytes."""
    with path.open("xb") as stream:
        stream.write(
            json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode()
            + b"\n"
        )


class RetainedMarket:
    """Join native HTTP bodies, receipts, security identities and W2 projections."""

    def __init__(self, root: Path, cutoff: datetime) -> None:
        self.root, self.cutoff = root, cutoff
        policy = read_json(root / "contracts/g93-radar-policy-v1.json")
        inventory = root / "artifacts/g93/input-inventory.json"
        if sha(inventory.read_bytes()) != policy["source_pack_sha256"]:
            raise ValueError("SOURCE_INVENTORY_DRIFT")
        for row in read_json(inventory):
            path = root / row["path"]
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("SOURCE_PATH_ESCAPE")
            raw = path.read_bytes()
            if sha(raw) != row["sha256"] or len(raw) != row["byte_size"]:
                raise ValueError("SOURCE_BYTE_DRIFT")
        self.base = root / "artifacts/g93/inputs"
        self.policy = policy
        self.handoff = read_json(self.base / "market-fact-handoff.json")
        self.rows = read_json(self.base / "ordered-native-prices.json")["rows"]
        self.proofs = read_json(self.base / "source-proofs.json")
        if (
            sha((self.base / "source-proofs.json").read_bytes())
            != self.handoff["source_proofs"]["sha256"]
        ):
            raise ValueError("HANDOFF_SOURCE_PROOFS")
        self.captures: dict[str, Any] = {}
        self.bodies: dict[str, Any] = {}
        for number in [*range(1, 13), 14, 17, 18]:
            cap = read_json(self.base / f"{number:04}.response.json")
            receipt = read_json(self.base / f"{number:04}.receipt.json")
            raw = (self.base / f"{number:04}.raw").read_bytes()
            if (
                cap["status_code"] != 200
                or sha(raw) != cap["raw_sha256"]
                or len(raw) != cap["raw_size"]
                or receipt["payload"]["sha256"] != sha(raw)
                or receipt["core_receipt_ref"]["artifact_id"] != cap["core_receipt_id"]
                or receipt["request"] != cap["request"]
                or receipt["observed_at"] != cap["observed_at"]
                or receipt["ingested_at"] != cap["ingested_at"]
                or not datetime.fromisoformat(cap["observed_at"])
                <= datetime.fromisoformat(cap["ingested_at"])
                <= cutoff
            ):
                raise ValueError("NATIVE_MARKET_RECEIPT_MISMATCH_OR_FUTURE")
            self.captures[cap["core_receipt_id"]] = cap
            self.bodies[cap["core_receipt_id"]] = json.loads(raw)
        self.bars: dict[str, list[EodBarRecord]] = defaultdict(list)
        seen = set()
        self.normalized_lineage = []
        for row in self.rows:
            symbol, session = row["symbol"], row["session"]
            key = symbol, session
            if key in seen or session > policy["market_session"]:
                raise ValueError("DUPLICATE_OR_POST_CUTOFF_MARKET_ROW")
            seen.add(key)
            cap = self.captures[row["source_receipt_id"]]
            proof = self.proofs["prices"][row["source_receipt_id"]]
            params = {p["name"]: p["value"] for p in cap["request"]["parameters"]}
            if (
                params.get("feed") != "iex"
                or params.get("adjustment") != "raw"
                or params.get("currency") != "USD"
            ):
                raise ValueError("MARKET_BASIS_MISMATCH")
            if any(
                row[k] != proof[k]
                for k in ["observed_at", "ingested_at", "response_sha256"]
            ):
                raise ValueError("ROW_RECEIPT_CLOCK_OR_SHA_MISMATCH")
            native = [
                b
                for b in self.bodies[row["source_receipt_id"]]["bars"][symbol]
                if b["t"] == row["provider_bar_timestamp"]
            ]
            if len(native) != 1:
                raise ValueError("NATIVE_BAR_AMBIGUITY")
            bar = native[0]
            provider_session = (
                datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
                .astimezone(ZoneInfo("America/New_York"))
                .date()
                .isoformat()
            )
            if provider_session != session or any(
                Decimal(str(bar[k])) != Decimal(row[v])
                for k, v in [
                    ("o", "raw_open"),
                    ("h", "raw_high"),
                    ("l", "raw_low"),
                    ("c", "raw_close"),
                    ("v", "volume"),
                ]
            ):
                raise ValueError("NATIVE_MARKET_VALUE_OR_SESSION_MISMATCH")
            identity = self.proofs["identities"][symbol]
            if (
                row["security_id"] != identity["quant_uuid"]
                or self.bodies[identity["receipt"]["receipt_id"]] != identity["source"]
                or identity["source"]["symbol"] != symbol
            ):
                raise ValueError("SECURITY_IDENTITY_MISMATCH")
            normalized = EodBarRecord(
                asset_id=AssetId("US:" + symbol),
                trade_date=session,
                open=float(row["raw_open"]),
                high=float(row["raw_high"]),
                low=float(row["raw_low"]),
                close=float(row["raw_close"]),
                volume=float(row["volume"]),
                source_id=row["source_receipt_id"],
                ingestion_ts=datetime.fromisoformat(row["ingested_at"]),
                feed_identity="iex",
                coverage_scope="PARTIAL_IEX_NOT_CONSOLIDATED",
            )
            self.bars[str(normalized.asset_id)].append(normalized)
            self.normalized_lineage.append(row)
        for bars in self.bars.values():
            bars.sort(key=lambda b: b.trade_date)
        if sorted(self.bars) != ["US:" + s for s in sorted(self.handoff["symbols"])]:
            raise ValueError("UNIVERSE_POPULATION_DRIFT")
        self.facts = []
        index = {(r["symbol"], r["session"]): r for r in self.rows}
        for fact in self.handoff["latest_facts"]:
            if (
                fact["security_id"]
                != self.proofs["identities"][fact["symbol"]]["quant_uuid"]
                or fact["as_of_session"] != policy["market_session"]
                or datetime.fromisoformat(fact["available_at"].replace("Z", "+00:00"))
                > cutoff
            ):
                raise ValueError("W2_FACT_SCOPE_OR_CLOCK")
            for operand in fact["ordered_inputs"]:
                row = index[(fact["symbol"], operand["session"])]
                if (
                    operand["receipt_id"] != row["source_receipt_id"]
                    or operand["response_sha256"] != row["response_sha256"]
                    or Decimal(operand["raw_close"]) != Decimal(row["raw_close"])
                ):
                    raise ValueError("W2_FACT_NATIVE_OPERAND")
            self.facts.append(fact)


def scan(root: Path, output: Path, at: datetime) -> dict[str, Any]:
    """Execute frozen retained-source scan; generate no mandate or Agent call."""
    output.mkdir(parents=True, exist_ok=False)
    market = RetainedMarket(root, at)
    blobs: dict[str, bytes] = {}

    def ref(identifier: str, value: Any, available: datetime = at) -> ArtifactRef:
        raw = encoded(value)
        blobs[identifier] = raw
        return ArtifactRef(
            artifact_id=identifier,
            sha256_digest=sha(raw),
            version="g93_retained_projection_v1",
            owner="g93_composition",
            available_at=available,
            observed_at=at,
            ingested_at=at,
        )

    def reader(reference: ArtifactRef) -> bytes:
        return blobs[reference.artifact_id]

    l0 = {}
    for asset, bars in market.bars.items():
        source = ref("g93:bars:" + asset, [b.model_dump(mode="json") for b in bars])
        l0[asset] = recompute_l0(
            bars, asset=AssetId(asset), cutoff=at, source=source, reader=reader
        )
    radar = VNextSectorRadar()
    price_events = radar.detect_asset_prices(
        bars_by_asset=market.bars, research_as_of=at
    )
    events = list(price_events)
    source_rows: dict[str, Any] = {}
    for event in price_events:
        asset = str(event.source_asset_ids[0])
        source_rows[event.event_id] = {
            "rows": [r for r in market.rows if "US:" + r["symbol"] == asset],
            "historical_published_at": "UNKNOWN",
            "origin": "REAL_RETAINED_SOURCE",
        }
    native = NativeSource(root, output / "native-recovery", at)
    source_rows["sec-filing"] = {
        "registration": native.registration.model_dump(mode="json"),
        "document_receipt": native.document.model_dump(mode="json"),
        "submissions_receipt": native.submissions.model_dump(mode="json"),
        "native_proofs": [p.model_dump(mode="json") for p in native.proofs],
    }
    company_records = [
        (
            "sec-filing",
            AssetId("US:AAPL"),
            native.available,
            native.document.ingested_at,
            (
                "Retained SEC 10-Q filed: 0000320193-26-000020; period end 2026-06-27."
                " Filing disclosure only, not an earnings surprise."
            ),
        )
    ]
    for entry in market.proofs["corporate_actions"]:
        cap = market.captures[entry["receipt"]["receipt_id"]]
        body = market.bodies[cap["core_receipt_id"]]
        if body != entry["body"]:
            raise ValueError("CORPORATE_ACTION_BODY_MISMATCH")
        for dividend in body["corporate_actions"].get("cash_dividends", []):
            source_rows[dividend["id"]] = {
                "body": dividend,
                "receipt": cap,
                "historical_published_at": "UNKNOWN",
            }
            company_records.append(
                (
                    dividend["id"],
                    AssetId("US:" + dividend["symbol"]),
                    datetime.fromisoformat(dividend["ex_date"])
                    .replace(tzinfo=ZoneInfo("America/New_York"))
                    .astimezone(UTC),
                    datetime.fromisoformat(cap["ingested_at"]),
                    (
                        f"Retained corporate action: cash dividend {dividend['rate']}"
                        f" USD/share; ex-date {dividend['ex_date']}; payable"
                        f" {dividend['payable_date']}. Not a new catalyst or"
                        " total-return proof."
                    ),
                )
            )
    for record_key, company_asset, event_time, ingested, summary in company_records:
        eid = (
            "sector_anomaly_"
            + sha(
                encoded([record_key, str(company_asset), "g93-company-disclosure-v1"])
            )[:24]
        )
        source_rows[eid] = source_rows.pop(record_key)
        events.append(
            SectorAnomalyEvent(
                event_id=eid,
                event_type=SectorAnomalyType.NEWS_EVENT,
                sector_id=None,
                source_asset_ids=(company_asset,),
                affected_asset_ids=(company_asset,),
                direction=AnomalyDirection.UNKNOWN,
                severity=EventSeverity.MEDIUM,
                confidence=1.0,
                event_time=event_time,
                # Conservative observation bound, not actual publication.
                published_at=ingested,
                available_at=ingested,
                ingested_at=ingested,
                as_of=at,
                source_evidence_ids=(eid + ":source",),
                summary=summary,
                status=SectorAnomalyStatus.DETECTED,
                version="g93-company-disclosure-v1",
            )
        )
    # Ranking is frozen before any signal inspection, and uses no future returns.
    events.sort(
        key=lambda e: (
            -e.event_time.timestamp(),
            str(e.source_asset_ids[0]),
            e.event_id,
        )
    )
    candidates: list[dict[str, Any]] = []
    dedup: set[tuple[str, str]] = set()
    for event in events:
        asset = str(event.source_asset_ids[0])
        key = asset, event.event_type.value
        if key in dedup:
            continue
        dedup.add(key)
        if len(candidates) >= market.policy["maximum_cards"]:
            break
        sources = tuple(
            ref(e, source_rows[event.event_id]) for e in event.source_evidence_ids
        )
        sources += (
            ref(
                "g93:context:" + asset,
                {
                    "l0": l0[asset],
                    "source_rows": [
                        r for r in market.rows if "US:" + r["symbol"] == asset
                    ],
                    "w2_handoff_sha256": sha(
                        (market.base / "market-fact-handoff.json").read_bytes()
                    ),
                    "market_facts": [
                        f for f in market.facts if "US:" + f["symbol"] == asset
                    ],
                    "input_inventory_sha256": market.policy["source_pack_sha256"],
                },
            ),
        )
        event_ref = ref(event.event_id, event.model_dump(mode="json"))
        data = RadarDataInput(
            owner="g93_composition",
            record_id="g93-input:" + event.event_id,
            revision=1,
            created_at=at,
            research_as_of=at,
            scope=Scope(scope_type=ResearchScopeType.ASSET, scope_id="ASSET:" + asset),
            source_refs=sources,
            events=(event,),
            event_refs=(event_ref,),
        )
        card = radar.opportunity_cards(data, reader=reader)[0]
        card_ref = artifact(card)
        blobs[card_ref.artifact_id] = encoded(card.model_dump(mode="json"))
        observations = [f for f in market.facts if "US:" + f["symbol"] == asset]
        missing = [
            "SECTOR_CHAIN_AUTHORITY_INCOMPLETE",
            "VERIFIED_FLOW_MISSING",
            "CONSOLIDATED_VOLUME_MISSING",
            "BID_ASK_SPREAD_AND_IMPACT_COST_MISSING",
            "CURRENT_DATA_STALE",
            "COMPARABLE_VALUATION_MISSING",
            "QUALIFIED_RESEARCH_MEMORY_MISSING",
        ]
        questions = (
            [
                "Does a consolidated feed confirm the observed IEX anomaly?",
                (
                    "Is the move associated with a separately sourced issuer event"
                    " rather than a market-wide move?"
                ),
            ]
            if event.event_type == SectorAnomalyType.PRICE_VOLUME
            else [
                (
                    "What changed in this issuer disclosure relative to the preceding"
                    " filing?"
                ),
                (
                    "Is there newer independently sourced information that changes its"
                    " relevance today?"
                ),
            ]
        )
        if "cash dividend" in event.summary:
            questions = [
                "Does issuer disclosure confirm dividend currency, ex-date and terms?",
                (
                    "Would corporate-action adjustment change the raw-price"
                    " interpretation?"
                ),
                "Is this old routine dividend still relevant after newer information?",
            ]
        baseline = {
            "schema_version": "G93_DETERMINISTIC_RESEARCH_BASELINE_V1",
            "card_sha256": card.sha256,
            "source_refs": [r.model_dump(mode="json") for r in sources],
            "event": event.model_dump(mode="json"),
            "l0": l0[asset],
            "w2_market_fact_observations": observations,
            "market_fact_qualification": (
                "W2_DECLARED_OPERATOR_RESULTS_NATIVE_INPUTS_REVERIFIED_NOT_NEW_FACTOR_ADMISSION"
            ),
            "verified_relationships": [],
            "known_missing": missing,
            "known_financial_facts": [],
        }
        scope = {
            "schema_version": "G93_INVESTIGATION_SCOPE_V1",
            "baseline_sha256": sha(encoded(baseline)),
            "questions": questions,
            "known_already": (
                "Baseline event, retained metrics and source gaps are deterministic;"
                " repetition is not AI incremental insight."
            ),
            "falsifiable_hypothesis": (
                "The observation remains issuer-specific and relevant after"
                " consolidated-feed, corporate-action and newer-disclosure checks."
            ),
            "refutation": (
                "Consolidated feed does not confirm anomaly, corporate action explains"
                " raw move, or later disclosure invalidates relevance."
            ),
            "required_new_sources": missing,
            "next_roles_if_selected": [
                "news_event_analyst",
                "fundamental_analyst",
                "technical_text_analyst",
            ],
            "research_started": False,
        }
        candidates.append(
            {
                "opportunity": card.model_dump(mode="json"),
                "card_sha256": card.sha256,
                "signal_category": (
                    "PRICE_VOLUME_ANOMALY"
                    if event.event_type == SectorAnomalyType.PRICE_VOLUME
                    else "COMPANY_EVENT"
                ),
                "human_review_status": "PENDING_HUMAN_REVIEW",
                "allowed_actions": ["SELECT_FOR_RESEARCH", "WATCH", "DEFER", "REJECT"],
                "origin": "HISTORICAL_RETROSPECTIVE_REPLAY",
                "discovered_at": at.isoformat(),
                "publication_time_qualification": (
                    "UNKNOWN_ORIGINAL_MARKET_PUBLICATION; event published_at is"
                    " compatibility metadata, not a historical publication assertion"
                ),
                "severity_qualification": "RULE_PRIORITY_NOT_ECONOMIC_MATERIALITY",
                "memory_qualification": "L0_RECOMPUTED_CONTEXT_NOT_DURABLE_MEMORY",
                "source_truth": "REAL_RETAINED_SOURCE",
                "sector": None,
                "industry_chain": None,
                "related_assets": [],
                "comparable_assets": [],
                "relevant_memory": {"L0": l0[asset], "L1": None, "L2": None},
                "liquidity_capacity_quality": (
                    "IEX_ONLY_NOT_EXECUTABLE_COST_OR_CAPACITY"
                ),
                "known_risks": missing,
                "baseline": baseline,
                "investigation_scope": scope,
                "production_admission": False,
            }
        )
    receipt = {
        "schema_version": "G93_SCAN_RECEIPT_V1",
        "status": "PARTIAL",
        "research_as_of": at.isoformat(),
        "policy_sha256": sha(
            (root / "contracts/g93-radar-policy-v1.json").read_bytes()
        ),
        "input_inventory_sha256": sha(
            (root / "artifacts/g93/input-inventory.json").read_bytes()
        ),
        "universe": sorted(market.bars),
        "securities": market.proofs["identities"],
        "market_rows": len(market.rows),
        "session_start": min(r["session"] for r in market.rows),
        "latest_session": max(r["session"] for r in market.rows),
        "real_company_events": len(company_records),
        "real_price_volume_signals": len(price_events),
        "verified_flow_signals": 0,
        "qualified_opportunity_cards": len(candidates),
        "human_review_pending": len(candidates),
        "source_time_qualification": "PARTIAL_HISTORICAL_MARKET_PUBLICATION_UNKNOWN",
        "sector_chain_authority": "BLOCKED",
        "source_class": "REAL_RETAINED_SOURCE",
        "discovery_class": "HISTORICAL_RETROSPECTIVE_REPLAY",
        "P0_readiness": "PARTIAL",
        "P1": "BLOCKED_NO_INDEPENDENT_TREND_STRATEGY_VALIDATION",
        "P2": "RESERVED",
        "new_model_calls": 0,
        "new_provider_calls": 0,
        "formal_pit": False,
        "validated_alpha": False,
        "production_admission": False,
        "real_trading": False,
    }
    save(output / "scan.json", receipt)
    save(output / "all-detections.json", [e.model_dump(mode="json") for e in events])
    save(output / "opportunity-cards.json", candidates)
    for item in candidates:
        ident = item["card_sha256"]
        save(output / (ident + ".card.json"), item)
        save(output / (ident + ".baseline.json"), item["baseline"])
        save(output / (ident + ".scope.json"), item["investigation_scope"])

    save(output / "l0-indicators.json", l0)
    save(
        output / "resolved-evidence.json", {k: json.loads(v) for k, v in blobs.items()}
    )
    save(output / "native-source-lineage.json", source_rows)
    board = [
        "# G93 Opportunity Board",
        "",
        (
            f"实际发现时间：{at.isoformat()}。使用截至 2026-10-15"
            " 的保留行情；全部为当前重放发现，非历史实时发现。"
        ),
        "",
        (
            "12只美股是字母顺序偏置的局部样本。IEX不是全市场；无真实资金流、"
            "成本容量或产业链权威。所有卡片待人工选择，不签发交易。"
        ),
        "",
    ]
    for i, row in enumerate(candidates, 1):
        card_json = row["opportunity"]
        board += [
            f"## {i}. {card_json['asset_ids'][0]} — {row['signal_category']}",
            f"ID: `{card_json['record_id']}`",
            "",
            card_json["trigger"]["summary"],
            "",
            (
                f"事件时间：{card_json['trigger']['event_time']}；来源可用时间：{card_json['trigger']['available_at']}。"
            ),
            "可靠内容：原始来源及确定性观测；不是风险发生、资金流、估值低估或收益优势证明。",
            "日频交易适用性：当前资料陈旧、局部成交量和成本数据不足，不能据此进行交易决策。",
            "行业/产业链/可比公司：未核验，不推断关联。",
            "待补证据：" + "; ".join(row["known_risks"]),
            "下一轮研究：" + " ".join(row["investigation_scope"]["questions"]),
            (
                "状态：PENDING_HUMAN_REVIEW。可选择 SELECT_FOR_RESEARCH / WATCH / DEFER"
                " / REJECT。"
            ),
            "",
        ]
    (output / "OPPORTUNITY_BOARD.md").write_text("\n".join(board))
    return receipt
