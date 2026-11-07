"""G95 opt-in public baseline and append-only human review composition."""

from __future__ import annotations

import gzip
import json
import re
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.adapters.providers import _html_to_text
from src.memory.vnext_contracts import (
    ROLE_STAGES,
    ArtifactRef,
    MemoryDelta,
    MemoryReadSet,
    ResearchImpactPlan,
    Scope,
)
from src.models.enums import AgentName, MemoryLevel, ResearchScopeType
from src.services.native_preservation import NativePreserver
from src.services.research_vnext.contracts import artifact
from src.services.research_vnext.radar import (
    OpportunityCard,
    Selection,
    SelectionEvent,
    require_mandate,
    selected_mandate,
)
from src.services.research_vnext.radar_pilot import encoded, read_json, save, sha

IDS = {
    "AVGO": "card:sector_anomaly_df7910daebe92ae2efaad806:COMPANY_EVENT",
    "COHR": "card:sector_anomaly_7ccc0e9b7de0efa7d300ea52:COMPANY_EVENT",
    "AAOI": "card:sector_anomaly_dabfbc19fb2983bc13a05c4a:COMPANY_EVENT",
}
CHOICES: dict[str, Selection] = {
    "AVGO": "SELECT_FOR_RESEARCH",
    "COHR": "WATCH",
    "AAOI": "DEFER",
}
ROLES = (AgentName.FUNDAMENTAL_ANALYST, AgentName.NEWS_EVENT_ANALYST)


def check_user_event(
    event: dict[str, Any], text: str, provenance: dict[str, Any]
) -> None:
    """Verify retained current CLI message population, not an assistant signature."""
    payload = event["payload"]
    actual = "".join(
        v.get("text", "")
        for v in payload.get("content", [])
        if v.get("type") in {"input_text", "text"}
    )
    if (
        event.get("type") != "response_item"
        or payload.get("role") != "user"
        or actual != text
        or sha(text.encode()) != provenance["message_sha256"]
        or payload.get("id") != provenance["message_id"]
        or event.get("timestamp") != provenance["timestamp"]
    ):
        raise ValueError("ACTUAL_USER_EVENT_REQUIRED")
    for symbol, identity in IDS.items():
        pattern = (
            rf"{symbol}：\s*{CHOICES[symbol]}\s*Opportunity ID："
            rf"\s*{re.escape(identity)}"
        )
        if not re.search(pattern, text):
            raise ValueError("EXACT_HUMAN_SELECTION_REQUIRED")
    if "ASSET:US:AVGO" not in text or "DEVELOPMENT_RESEARCH_ONLY" not in text:
        raise ValueError("RESEARCH_SCOPE_REQUIRED")


def contract_operation(operation: str) -> None:
    """No arithmetic or legal-identity promotion from disclosure resemblance."""
    if operation != "RETAIN_DISCLOSURE_LOCAL_IDENTITIES_WITH_UNKNOWN_LINK":
        raise ValueError("LEGAL_IDENTITY_OR_CALCULATION_AUTHORITY_MISSING")


def source_text(root: Path, source: dict[str, Any], at: datetime) -> str:
    """Recover existing native receipt and bind its actual original entity bytes."""
    file = root / source["path"]
    if sha(file.read_bytes()) != source["file_sha256"]:
        raise ValueError("SOURCE_FILE_DRIFT")
    doc = read_json(file)
    receipt = doc["receipt"]
    base = "g94" if source["origin"] == "G94_RETAINED" else "g95"
    directory = (
        root
        / f"artifacts/{base}/sec-requests"
        / f"{receipt['request']['attempt']:02}-native"
    )
    session = read_json(directory / "session.json")
    store = NativePreserver(
        directory,
        provider=session["provider"],
        owner=session["owner"],
        run_id=session["run_id"],
        retention_authority=session["retention_authority"],
        allowed_endpoints=tuple(session["endpoints"]),
        normalization_version=session["normalization_version"],
    )
    native = store.recover(receipt["manifest_sha256"])
    raw = (directory / (native.acquisition.body_sha256 + ".raw")).read_bytes()
    if (
        sha(raw) != source["raw_sha256"]
        or native.acquisition.endpoint != source["url"]
        or native.acquisition.owner != "US:AVGO"
        or native.status_code != 200
        or native.ingested_at > at
        or datetime.fromisoformat(source["publication_date"]).date() > at.date()
    ):
        raise ValueError("SOURCE_IDENTITY_OR_TIME")
    body = (
        gzip.decompress(raw) if native.acquisition.content_encoding == "gzip" else raw
    )
    if body.decode() != doc["decoded"]:
        raise ValueError("DECODED_SOURCE_DRIFT")
    return _html_to_text(body.decode())


def verify_fact(row: dict[str, Any], text: str) -> None:
    """Check exact source quotation/offset; not a ClaimDecision or numeric grant."""
    start, end = row["text_span"]
    if not 0 <= start < end <= len(text) or text[start:end] != row["quote"]:
        raise ValueError("ATOMIC_SOURCE_SPAN")
    value, unit = row["reported_value"], row["unit"]
    if value is not None:
        patterns = {
            "USD_MAXIMUM": (r"\$\s*([\d,.]+)\s*billion", Decimal("1000000000")),
            "PERCENT_BASIS": (r"([\d.]+)\s*%", Decimal(1)),
            "YEARS": (r"([\d.]+)\s*-year", Decimal(1)),
            "GW_EXPECTED": (r"([\d.]+)\s*gigawatts", Decimal(1)),
        }
        if unit not in patterns:
            raise ValueError("UNSUPPORTED_ATOMIC_UNIT")
        pattern, scale = patterns[unit]
        matches = re.findall(pattern, row["quote"])
        if len(matches) != 1 or Decimal(matches[0].replace(",", "")) * scale != Decimal(
            value
        ):
            raise ValueError("ATOMIC_VALUE_OR_UNIT_MISMATCH")
    if row["verification_status"] != "ISSUER_DISCLOSED_FACT":
        raise ValueError("UNSUPPORTED_SOURCE_AUTHORITY")


def build(root: Path, output: Path, at: datetime) -> dict[str, Any]:
    """Build partial baseline and specialist-only planning artifacts."""
    output.mkdir(parents=True, exist_ok=False)
    inventory = read_json(root / "contracts/g95-inputs-v2.json")
    for row in inventory["files"]:
        path = root / row["path"]
        if (
            not path.resolve().is_relative_to(root.resolve())
            or sha(path.read_bytes()) != row["sha256"]
        ):
            raise ValueError("G95_FROZEN_INPUT_DRIFT")
    event = read_json(root / "artifacts/g95/user-event.json")
    text = (root / "artifacts/g95/user-instruction.txt").read_text()
    provenance = read_json(root / "artifacts/g95/user-event-provenance.json")
    check_user_event(event, text, provenance)
    selected_at = datetime.fromisoformat(event["timestamp"])
    if selected_at > at:
        raise ValueError("FUTURE_USER_EVENT")
    review = read_json(root / "artifacts/g95/atomic-source-review-v2.json")
    sources = review["sources"]
    texts = {k: source_text(root, s, at) for k, s in sources.items()}
    facts = []
    for row in review["facts"]:
        verify_fact(row, texts[row["source_id"]])
        src = sources[row["source_id"]]
        facts.append(
            {
                **row,
                "source": src,
                "research_as_of": at.isoformat(),
                "source_publication_date": src["publication_date"],
                "source_ingested_at": src["receipt"]["ingested_at"],
                "scientific_claim_admission": False,
            }
        )
    contract_operation("RETAIN_DISCLOSURE_LOCAL_IDENTITIES_WITH_UNKNOWN_LINK")
    original = read_json(root / "artifacts/g94/delivery-scan/opportunity-cards.json")
    cards = {c["baseline"]["source"]["symbol"]: c for c in original}
    for symbol, identity in IDS.items():
        if cards[symbol]["opportunity"]["record_id"] != identity:
            raise ValueError("ORIGINAL_CARD_IDENTITY")
    parent = cards["AVGO"]["baseline"]
    baseline = {
        "schema": "G95_COMPLETE_PUBLIC_INFORMATION_BASELINE_V1",
        "completeness": "PARTIAL_MISSING_OFFICIAL_JOINT_ANNOUNCEMENT_B",
        "revision": 2,
        "supplements": {
            "G94_baseline_sha256": sha(encoded(parent)),
            "G94_card": IDS["AVGO"],
        },
        "research_as_of": at.isoformat(),
        "facts": facts,
        "missing": review["unverified_B_requirements"],
        "public_before_G94_but_acquired_G95": ["C", "D"],
        "already_in_G94": ["A"],
        "B_publication_claim": "USER_DESCRIBED_2026-10-26_NOT_SOURCE_VERIFIED",
        "contract_identity": "UNKNOWN_NOT_ASSERTED_SAME_OR_DIFFERENT",
        "prohibited_operations": [
            "ADD_29_43",
            "DIVIDE_43_63",
            "INFER_RISK_DECREASE_85_TO_72_5",
            "ASSUME_SAME_CONTRACT",
            "ASSUME_DIFFERENT_CONTRACT",
            "EXPECTED_2027_AS_DELIVERED",
        ],
        "manager_expectations_not_verified": [
            "customer profitability",
            "low default likelihood",
            "asset sustaining value",
        ],
        "risk_cannot_be_quantified": [
            "default probability",
            "net loss",
            "asset residual value",
            "net aggregated exposure",
        ],
    }
    blobs: dict[str, bytes] = {}

    def ref(
        name: str, value: Any, clock: datetime = at, owner: str = "g95_composition"
    ) -> ArtifactRef:
        raw = encoded(value)
        blobs[name] = raw
        return ArtifactRef(
            artifact_id=name,
            sha256_digest=sha(raw),
            version="g95_v1",
            owner=owner,
            available_at=clock,
            observed_at=at,
            ingested_at=at,
        )

    def reader(reference: ArtifactRef) -> bytes:
        return blobs[reference.artifact_id]

    decisions = []
    mandate = None
    for symbol in IDS:
        card = OpportunityCard.model_validate(cards[symbol]["opportunity"])
        cardref = artifact(card)
        blobs[cardref.artifact_id] = encoded(card.model_dump(mode="json"))
        # Seven-day window; no paid calls or full workflow authority.
        selection = SelectionEvent(
            opportunity_sha256=card.sha256,
            actor_id="codex-user:" + provenance["thread"],
            selected_at=selected_at,
            selection=CHOICES[symbol],
            authority_kind="HUMAN_SELECTION",
            scopes=(card.scope,),
            roles=ROLES,
            expires_at=selected_at + timedelta(days=7),
        )
        selection_ref = ref(
            "g95-selection:" + symbol,
            selection.model_dump(mode="json"),
            selected_at,
            selection.actor_id,
        )
        decisions.append(
            {
                "schema": "G95_HUMAN_REVIEW_RECEIPT_V1",
                "revision": 1,
                "card": cardref.model_dump(mode="json"),
                "selection": selection.model_dump(mode="json"),
                "selection_ref": selection_ref.model_dump(mode="json"),
                "user_provenance": provenance,
                "original_user_event_sha256": sha(encoded(event)),
                "recorded_at": at.isoformat(),
                "signature": "NONE_NOT_CLAIMED",
                "original_pending_unchanged": True,
            }
        )
        if symbol == "AVGO":
            mandate = selected_mandate(card, selection_ref, at=at, reader=reader)
    assert mandate is not None
    before = ref("g95:AVGO:public-baseline", parent)
    after_raw = encoded(baseline)
    # Versions share logical identity; resolve by content hash.
    blobs[before.sha256_digest] = blobs.pop(before.artifact_id)
    after = ArtifactRef(
        artifact_id=before.artifact_id,
        sha256_digest=sha(after_raw),
        version="g95_v1",
        owner="g95_composition",
        available_at=at,
        observed_at=at,
        ingested_at=at,
    )
    blobs[after.sha256_digest] = after_raw
    policy = ref(
        "g95:phase-policy",
        {
            "roles": [r.value for r in ROLES],
            "automatic_downstream": False,
            "materiality": "new verified public-source facts; not price performance",
        },
    )
    delta = MemoryDelta(
        owner="coordinator",
        record_id="g95-public-information-delta",
        revision=1,
        created_at=at,
        research_as_of=at,
        scope=mandate.scope,
        source_refs=(before, after),
        memory_level=MemoryLevel.L2,
        change_kind="FILING",
        before=before,
        after=after,
        change_detector=policy,
        materiality_rule=policy,
        material=True,
    )
    for role in ROLES:
        require_mandate(mandate, role=role, scope=mandate.scope, at=at, reader=reader)
    plan = ResearchImpactPlan(
        owner="coordinator",
        record_id="g95-specialist-impact",
        revision=1,
        created_at=at,
        research_as_of=at,
        scope=mandate.scope,
        source_refs=(after, policy),
        delta_sha256=delta.sha256,
        mandate_sha256=mandate.sha256,
        policy_sha256=policy.sha256,
        direct_roles=ROLES,
        execution_stages=(ROLES,),
        reusable_state=None,
        disposition="SELECTIVE_EXECUTION",
        reason="Specialist plan only. No dispatch/payment. Baseline B missing.",
    )
    bundle = ref(
        "g95:assembly-context", {"baseline_sha256": sha(after_raw), "memory_items": []}
    )
    readset = MemoryReadSet(
        owner="coordinator",
        record_id="g95-assembly-readset",
        revision=1,
        created_at=at,
        research_as_of=at,
        scope=Scope(scope_type=ResearchScopeType.ASSET, scope_id="ASSET:US:AVGO"),
        source_refs=(after,),
        agent_role="coordinator",
        agent_run_id="g95-offline-assembly:" + sha(after_raw),
        retrieval_query_id="NO_AGENT_MEMORY_RETRIEVAL",
        bundle_ref=bundle,
        bundle_sha256=bundle.sha256_digest,
        memory_refs=(),
    )
    investigation = {
        "topic": "Broadcom AI Compute Financing and Contingent Exposure",
        "questions": [
            "What links financing, purchases, leases and residual support?",
            "Do arrangements overlap, replace or add? INDETERMINATE is valid.",
            "Who bears performance, default, finance and residual-value risk?",
            "What changes on delivery, payment, default and equipment sale?",
            "What additional official disclosure would change or refute the analysis?",
        ],
        "competing_hypotheses": [
            "Arrangements may overlap or be revised; legal proof required.",
            "Arrangements may be separate; also unproven without contracts.",
        ],
        "falsification_conditions": [
            "Executed contract identifier and amendment history",
            "Express non-overlap or replacement clause",
            "Cross-guarantee, recourse, netting or cancellation provisions",
            "Actual delivery and payment disclosure",
        ],
        "source_requirements": [
            "Missing official October26 joint announcement",
            "Executed relevant agreements and legal scope",
            "Subsequent official performance disclosure",
        ],
        "research_relevance": "Map obligations and decisive evidence, not returns.",
        "confidence": "UNKNOWN_UNCALIBRATED_NOT_DEFAULT_PROBABILITY",
        "missingness": baseline["missing"],
        "non_goals": [
            "buy/sell/price target",
            "invented customer profit or default probability",
            "simple baseline paraphrase as AI contribution",
        ],
    }
    rubric = {
        "schema": "G95_W5_INCREMENTAL_EVALUATION_BASELINE_V1",
        "baseline_sha256": sha(after_raw),
        "status": "NOT_READY_COMPLETE_BASELINE_B_MISSING",
        "baseline_restatement_credit": 0,
        "not_AI_increment": [
            "63 billion financing",
            "Anthropic financing identity",
            "43 billion Backstop",
            "29 billion Backstop",
            "all verified SEC facts",
        ],
        "missing_B_rule": (
            "Freeze B before AI evaluation. Public facts are baseline, not insight."
        ),
        "eligible_contributions": [
            "evidence-dependent competitive explanation",
            "feasible high-information investigation",
            "specific falsifying observation",
            "new legitimate source relation",
            "supported revision",
        ],
        "no_penalty_for_supported_indeterminate": True,
        "scores_created": False,
        "future_returns_forbidden": True,
    }
    handoff = {
        "schema": "G95_W3_W5_HANDOFF_V1",
        "ready": False,
        "reason": "Missing B; incomplete evaluation baseline.",
        "mandate": mandate.model_dump(mode="json"),
        "impact": plan.model_dump(mode="json"),
        "budget_proposal": {
            "model_calls": 0,
            "CNY": 0,
            "future_paid_budget": "NOT_PROPOSED_OR_AUTHORIZED",
        },
        "scientific_state_revision": {
            "status": "NOT_CREATED_NO_AGENT_RESULT",
            "new_revision": None,
        },
        "nine_role_topology": [[str(r) for r in stage] for stage in ROLE_STAGES],
        "forbidden_data": [
            "G71/G78 future return labels",
            "private answers",
            "unseen future sources",
        ],
        "allowed_evidence": list(sources),
        "cross_scope_propagation": "BLOCKED",
        "real_agent_dispatch": 0,
        "production_admission": False,
    }
    for name, value in [
        ("human-review-decisions", decisions),
        ("complete-public-baseline", baseline),
        ("research-mandate", mandate.model_dump(mode="json")),
        ("memory-delta", delta.model_dump(mode="json")),
        ("research-impact-plan", plan.model_dump(mode="json")),
        ("memory-readset", readset.model_dump(mode="json")),
        ("investigation-scope", investigation),
        ("w5-evaluation-baseline", rubric),
        ("w3-w5-handoff", handoff),
        ("resolved-artifacts", {k: json.loads(v) for k, v in blobs.items()}),
    ]:
        save(output / (name + ".json"), value)
    result = {
        "baseline_completeness": "PARTIAL",
        "primary_sources_verified": 3,
        "atomic_facts": len(facts),
        "human_selection": "PASS",
        "COHR": "WATCH",
        "AAOI": "DEFER",
        "mandate": "PASS",
        "impact_plan": "ELIGIBLE",
        "contract_identity": "UNKNOWN",
        "handoff_ready": False,
        "model_calls": 0,
        "dispatches": 0,
    }
    save(output / "execution-receipt.json", result)
    return result
