"""G96 opt-in official-source baseline closure; no Agent or Claim admission."""

from __future__ import annotations

import gzip
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.adapters.providers import _html_to_text
from src.memory import MemoryService
from src.memory.contracts import ResearchContextBundle, ResearchContextRequest
from src.memory.vnext_contracts import (
    ArtifactRef,
    MemoryDelta,
    MemoryReadSet,
    ResearchImpactPlan,
    ResearchMandate,
)
from src.models.enums import Market, MarketScope, MemoryLevel
from src.models.identifiers import AssetId
from src.repositories import (
    DuckDBDatabase,
    FaissVectorRepository,
    MemoryItemRepository,
    SourceRegistryRepository,
)
from src.repositories.records import SourceRegistryRecord
from src.services.embedding import FakeEmbeddingService
from src.services.native_preservation import NativePreserver
from src.services.research_vnext.mandate_baseline import ROLES, source_text, verify_fact
from src.services.research_vnext.radar import require_mandate
from src.services.research_vnext.radar_pilot import encoded, read_json, save, sha

C10_SENTENCE = "As of August 2, 2026, no notes have been issued to us."


def exact_location(text: str, quote: str) -> tuple[int, int]:
    """Locate one exact native normalized quote; refuse absent/duplicate spans."""
    if not quote or text.count(quote) != 1:
        raise ValueError("MISSING_OR_AMBIGUOUS_NATIVE_SPAN")
    start = text.index(quote)
    return start, start + len(quote)


def verify_binding(text: str, row: dict[str, Any], source: dict[str, Any]) -> None:
    """Bind the entire native text identity, original receipt and exact location."""
    if (
        row["source_id"] != source["source_id"]
        or row["raw_sha256"] != source["raw_sha256"]
        or row["receipt_identity"] != source["receipt"]["manifest_sha256"]
        or row["normalized_text_sha256"] != sha(text.encode())
        or tuple(row["text_span"]) != exact_location(text, row["quote"])
    ):
        raise ValueError("EXACT_NATIVE_EVIDENCE_BINDING")


def validate_c10(text: str, row: dict[str, Any], source: dict[str, Any]) -> None:
    """Require uniquely located notes statement and its report-period context."""
    verify_binding(text, row, source)
    context = row["context_quote"]
    if (
        row["quote"] != C10_SENTENCE
        or row["report_date"] != source["report_date"]
        or row["report_date"] != "2026-08-02"
        or row["effective_period"] != "As of 2026-08-02"
        or not context.startswith(
            "Convertible Notes In connection with lease agreements"
        )
        or not context.endswith(C10_SENTENCE)
        or len(context) > 700
        or tuple(row["context_span"]) != exact_location(text, context)
        or not row["context_span"][0]
        <= row["text_span"][0]
        < row["text_span"][1]
        == row["context_span"][1]
    ):
        raise ValueError("C10_PERIOD_OR_NOTES_CONTEXT")


def recover_announcement(root: Path, source: dict[str, Any], at: datetime) -> str:
    """Reopen the actual NativePreserver receipt without fetching the URL again."""
    file = root / source["path"]
    if sha(file.read_bytes()) != source["file_sha256"]:
        raise ValueError("ANNOUNCEMENT_FILE_HASH")
    doc = read_json(file)
    receipt = doc["receipt"]
    directory = (
        root
        / "artifacts/g96/corporate-requests"
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
        or native.status_code != 200
        or native.acquisition.endpoint != source["url"]
        or native.acquisition.owner != "US:AVGO"
        or native.ingested_at > at
        or native.acquisition.observed_at > at
        or datetime.fromisoformat(source["available_at"])
        != native.acquisition.observed_at
        or source["receipt"] != receipt
    ):
        raise ValueError("ANNOUNCEMENT_SOURCE_OR_TIME")
    body = (
        gzip.decompress(raw) if native.acquisition.content_encoding == "gzip" else raw
    )
    if body.decode() != doc["decoded"]:
        raise ValueError("ANNOUNCEMENT_DECODE_DRIFT")
    text = _html_to_text(body.decode())
    if (
        source["normalized_text_sha256"] != sha(text.encode())
        or source["publication_date"] != "2026-10-26"
    ):
        raise ValueError("ANNOUNCEMENT_NORMALIZATION_OR_DATE")
    exact_location(
        text, "NEW YORK, CHARLOTTE, N.C. and PALO ALTO, Calif. — October 26, 2026 —"
    )
    return text


def validate_announcement_fact(
    text: str, row: dict[str, Any], source: dict[str, Any]
) -> None:
    """Validate reviewed literal facts without legal or economic extrapolation."""
    verify_binding(text, row, source)
    if (
        row["verification_status"] != "JOINT_ANNOUNCEMENT_FACT"
        or row["scientific_claim_admission"]
    ):
        raise ValueError("JOINT_DISCLOSURE_ONLY")
    if row["id"] == "B02":
        amount = re.findall(r"\$(\d+) billion", row["quote"])
        if (
            len(amount) != 1
            or Decimal(amount[0]) * Decimal(10**9) != Decimal(row["reported_value"])
            or row["unit"] != "USD_TRANSACTION_SIZE"
        ):
            raise ValueError("TRANSACTION_AMOUNT_NOT_EXPOSURE")
    elif row["id"] == "B01":
        if row["reported_value"] != source["publication_date"] or row["unit"] != "DATE":
            raise ValueError("ANNOUNCEMENT_PUBLICATION_DATE")
    elif row["id"] == "B10":
        if (
            row["reported_value"] != "2027"
            or row["unit"] != "EXPECTED_CALENDAR_YEAR"
            or "expected deliveries" not in row["quote"]
        ):
            raise ValueError("EXPECTED_NOT_ACTUAL_DELIVERY")
    elif row["reported_value"] is not None or row["unit"] is not None:
        raise ValueError("UNSUPPORTED_ANNOUNCEMENT_NUMERIC_INFERENCE")


def register_context(
    output: Path, sources: dict[str, Any], at: datetime
) -> tuple[list[dict[str, Any]], ResearchContextBundle]:
    """Use existing SourceRegistry and empty retrieval without fact authority."""
    db = DuckDBDatabase(output / "local-context.duckdb")
    db.bootstrap()
    registry = SourceRegistryRepository(db)
    records = []
    for key, source in sources.items():
        sid = "g96-source:" + key + ":" + source["raw_sha256"]
        registry.upsert(
            SourceRegistryRecord(
                source_id=sid,
                source_name=f"G96 AVGO {key}",
                market_scope=MarketScope.US,
                source_type=(
                    "official_joint_announcement" if key == "B" else "sec_filing"
                ),
                auth_mode="public_retained",
                base_url=source["url"],
                notes="DEVELOPMENT_METADATA_ONLY; raw SHA256 "
                + source["raw_sha256"]
                + "; no Claim admission",
            )
        )
        read = SourceRegistryRepository(DuckDBDatabase(db.path)).get(sid)
        assert read is not None
        records.append(read.model_dump(mode="json"))
    query = "AVGO prior qualified research memory"
    embed = FakeEmbeddingService(
        {query: [1.0, 0.0]}, model_name="g96-local-empty-context-control-no-model-call"
    )
    vector = FaissVectorRepository(
        output / "local-faiss",
        embedder_model=embed.model_name,
        embedding_dim=embed.dimension,
    )
    memory = MemoryService(MemoryItemRepository(db), vector, embed, clock=lambda: at)
    bundle = memory.retrieve_context(
        ResearchContextRequest(
            query_text=query,
            as_of=at,
            market=Market.US,
            asset_id=AssetId("US:AVGO"),
            namespace_keys=["ASSET:US:AVGO"],
            memory_levels=[MemoryLevel.L2, MemoryLevel.L3],
        )
    )
    if bundle.retrieval_metadata.result_count:
        raise ValueError("UNEXPECTED_PRIOR_MEMORY_POPULATION")
    return records, bundle


def build(root: Path, output: Path, at: datetime) -> dict[str, Any]:
    """Freeze same-source W3/W5 handoff with unchanged G95 mandate and no dispatch."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("AWARE_CURRENT_RESEARCH_CUTOFF_REQUIRED")
    output.mkdir(parents=True, exist_ok=False)
    for item in read_json(root / "contracts/g96-inputs-v1.json")["files"]:
        p = root / item["path"]
        if (
            not p.resolve().is_relative_to(root.resolve())
            or sha(p.read_bytes()) != item["sha256"]
        ):
            raise ValueError("G96_FROZEN_INPUT_DRIFT")
    prior = read_json(root / "artifacts/g95/delivery-v2/complete-public-baseline.json")
    review = read_json(root / "artifacts/g95/atomic-source-review-v2.json")
    original_inventory = read_json(root / "artifacts/g95/SOURCE_INVENTORY.json")
    sources = {s["source_id"]: s for s in original_inventory["verified"]}
    texts = {key: source_text(root, source, at) for key, source in sources.items()}
    for fact in review["facts"]:
        verify_fact(fact, texts[fact["source_id"]])
    announcement = read_json(root / "artifacts/g96/announcement-source-review.json")
    sources["B"] = announcement["source"]
    texts["B"] = recover_announcement(root, sources["B"], at)
    if [f["id"] for f in announcement["facts"]] != [f"B{i:02}" for i in range(1, 11)]:
        raise ValueError("B_FACT_POPULATION")
    for f in announcement["facts"]:
        validate_announcement_fact(texts["B"], f, sources["B"])
    c10 = read_json(root / "artifacts/g96/C10-evidence-revision.json")
    validate_c10(texts["C"], c10, sources["C"])
    mandate = ResearchMandate.model_validate(
        read_json(root / "artifacts/g95/delivery-v2/research-mandate.json")
    )
    original_blobs = read_json(
        root / "artifacts/g95/delivery-v2/resolved-artifacts.json"
    )

    def original_reader(reference: ArtifactRef) -> bytes:
        return encoded(original_blobs[reference.artifact_id])

    for role in ROLES:
        require_mandate(
            mandate, role=role, scope=mandate.scope, at=at, reader=original_reader
        )
    current_facts = [
        {**f, "source": sources[f["source_id"]], "research_as_of": at.isoformat()}
        for f in prior["facts"]
        if f["id"] != "C10"
    ]
    current_facts += [
        {**c10, "source": sources["C"], "research_as_of": at.isoformat()},
        *[
            {**f, "source": sources["B"], "research_as_of": at.isoformat()}
            for f in announcement["facts"]
        ],
    ]
    baseline = {
        "schema": "G96_AVGO_COMPLETE_PUBLIC_BASELINE_V1",
        "revision": 1,
        "research_as_of": at.isoformat(),
        "parent": {
            "schema": prior["schema"],
            "path": "artifacts/g95/delivery-v2/complete-public-baseline.json",
            "file_sha256": sha(
                (
                    root / "artifacts/g95/delivery-v2/complete-public-baseline.json"
                ).read_bytes()
            ),
            "canonical_sha256": sha(encoded(prior)),
        },
        "completeness": (
            "COMPLETE_FOR_EXPLICIT_G96_PUBLIC_SOURCE_SCOPE"
            "_NOT_ALL_PUBLIC_INFORMATION"
        ),
        "facts": current_facts,
        "sources": sources,
        "C10_replaces_evidence_only": c10["supersedes_evidence_only"],
        "contract_identity": "UNKNOWN",
        "relation_status": "POSSIBLE_RELATIONSHIP_PENDING_LEGAL_CONFIRMATION",
        "unresolved_contract_relations": [
            "A-B complete legal contract identity",
            "C29B-A43B overlap/replacement/addition",
            "D collaboration-B facility full identity",
            "cross guarantees and netting",
        ],
        "prohibited_inferences": prior["prohibited_operations"]
        + [
            "FIRST_LIEN_EQUALS_43B",
            "SECOND_LIEN_EQUALS_63_MINUS_43",
            "REPLACE_ALL_ANONYMOUS_CUSTOMERS_WITH_ANTHROPIC",
        ],
        "fact_authority": (
            "Issuer/joint public statements only; no economic performance proof "
            "or original v2 ClaimDecision"
        ),
        "publication_vs_acquisition": (
            "B published date Oct26, exact native publication time/timezone UNKNOWN; "
            "available_at conservatively actual G96 capture, never backdated"
        ),
        "independent_joint_announcement_evidence_count": 1,
    }
    save(output / "baseline.json", baseline)
    baseline_file_sha = sha((output / "baseline.json").read_bytes())
    baseline_canonical_sha = sha(encoded(baseline))
    records, bundle = register_context(output, sources, at)
    save(output / "source-registry-records.json", records)
    save(output / "research-context-bundle.json", bundle.model_dump(mode="json"))
    blobs: dict[str, Any] = {}

    def ref(name: str, value: Any) -> ArtifactRef:
        blobs[sha(encoded(value))] = value
        return ArtifactRef(
            artifact_id=name,
            sha256_digest=sha(encoded(value)),
            version="g96_v1",
            owner="coordinator",
            available_at=at,
            observed_at=at,
            ingested_at=at,
        )

    before = ref("AVGO:public-baseline", prior)
    after = ref("AVGO:public-baseline", baseline)
    policy = ref(
        "g96:public-source-delta-policy",
        {
            "materiality": (
                "new previously public official facts plus precise evidence revision"
            ),
            "roles": [r.value for r in ROLES],
            "phase": "specialists_only",
            "model_dispatch": False,
        },
    )
    delta = MemoryDelta(
        owner="coordinator",
        record_id="g96-public-baseline-delta",
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
    plan = ResearchImpactPlan(
        owner="coordinator",
        record_id="g96-specialist-impact",
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
        reason=(
            "G95 authorization retained; baseline complete for G96 scope; "
            "no dispatch or paid authority"
        ),
    )
    bundle_ref = ref(
        "g96:empty-qualified-memory-context", bundle.model_dump(mode="json")
    )
    reads = MemoryReadSet(
        owner="coordinator",
        record_id="g96-assembly-readset",
        revision=1,
        created_at=at,
        research_as_of=at,
        scope=mandate.scope,
        source_refs=(after,),
        agent_role="coordinator",
        agent_run_id="g96-offline-context-assembly",
        retrieval_query_id=bundle.retrieval_metadata.query_id,
        bundle_ref=bundle_ref,
        bundle_sha256=bundle_ref.sha256_digest,
        memory_refs=(),
    )
    investigation = read_json(
        root / "artifacts/g95/delivery-v2/investigation-scope.json"
    )
    investigation["source_requirements"] = [
        x
        for x in investigation["source_requirements"]
        if "Missing official October26" not in x
    ]
    investigation["missingness"] = baseline["unresolved_contract_relations"]
    investigation["baseline_already_known"] = [f["id"] for f in current_facts]
    rubric = read_json(root / "artifacts/g95/W5_PUBLIC_RUBRIC_V2.json")
    rubric.update(
        {
            "schema": "G96_W5_FROZEN_EVALUATION_RUBRIC_V1",
            "baseline_sha256": baseline_file_sha,
            "baseline_canonical_sha256": baseline_canonical_sha,
            "ready": True,
            "independent_evaluation_performed": False,
            "blocking_requirement": None,
            "supersedes": "artifacts/g95/W5_PUBLIC_RUBRIC_V2.json",
            "no_AI_increment": [
                "63B transaction",
                "Anthropic",
                "SPV",
                "financial institutions",
                "first/second lien",
                "residual support",
                "expected2027delivery",
                "29B/43B disclosed maxima",
                "SEC lease/default/notes conditions",
            ],
            "unknown_legal_identity_does_not_block_research": True,
        }
    )
    handoff = {
        "schema": "G96_W3_W5_HANDOFF",
        "ready": True,
        "research_as_of": at.isoformat(),
        "baseline_sha256": baseline_file_sha,
        "baseline_sha256_encoding": "SHA256 of exact baseline.json bytes",
        "baseline_canonical_sha256": baseline_canonical_sha,
        "mandate_sha256": mandate.sha256,
        "mandate_file_sha256": sha(
            (root / "artifacts/g95/delivery-v2/research-mandate.json").read_bytes()
        ),
        "mandate_expires_at": mandate.expires_at.isoformat(),
        "roles": [r.value for r in ROLES],
        "source_evidence_context": (
            "baseline.json and evidence-inventory.json are source sidecars, "
            "not Memory items or ValidatedClaims"
        ),
        "memory_context": (
            "Actual empty isolated MemoryService retrieval; local fake embedding "
            "index only; zero Memory writes/citations"
        ),
        "allowed_information": [
            "A/B/C/D pinned sources and exact baseline facts",
            "clearly labelled hypotheses and unresolved legal questions",
        ],
        "forbidden_information": [
            "G71/G78 Outcome or future returns",
            "private answers",
            "unseen future sources",
            "unsupported numerical/legal inference",
        ],
        "source_scope_only": True,
        "independent_W3_W5_review_done": False,
        "paid_model_authorization": False,
        "dispatches": 0,
        "cross_scope_propagation": "BLOCKED",
        "production_admission": False,
        "scientific_nine_role_state": "BLOCKED",
    }
    for name, value in [
        ("research-mandate", mandate.model_dump(mode="json")),
        ("memory-delta", delta.model_dump(mode="json")),
        ("research-impact-plan", plan.model_dump(mode="json")),
        ("memory-readset", reads.model_dump(mode="json")),
        ("investigation-scope", investigation),
        ("w5-rubric", rubric),
        ("w3-handoff", handoff),
        ("w5-handoff", handoff),
        ("resolved-artifacts", blobs),
        ("source-inventory", sources),
        ("evidence-inventory", current_facts),
    ]:
        save(output / (name + ".json"), value)
    result = {
        "G96_AVGO_BASELINE_CLOSURE": "PASS",
        "OFFICIAL_JOINT_ANNOUNCEMENT": "PASS",
        "B_ATOMIC_FACTS_ACCEPTED": 10,
        "C10_PRECISE_EVIDENCE": "PASS",
        "C10_SPAN": c10["text_span"],
        "C10_QUOTE_LENGTH": len(c10["quote"]),
        "CONTRACT_IDENTITY_RESOLVED": "UNKNOWN",
        "BASELINE_SHA256": baseline_file_sha,
        "G95_MANDATE_VALID": "PASS",
        "W3_HANDOFF_READY": "YES",
        "W5_HANDOFF_READY": "YES",
        "NEW_MODEL_CALLS": 0,
        "REAL_AGENT_DISPATCH": 0,
    }
    save(output / "execution-receipt.json", result)
    return result
