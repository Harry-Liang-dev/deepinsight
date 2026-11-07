"""Real retained source controls for the generic binder; no issuer-specific adapter."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.memory.contracts import ResearchContextBundle, ResearchContextRequest
from src.memory.hybrid_contracts import EvidenceLocator, NarrativeProposal
from src.memory.hybrid_sources import RegisteredNarrativeSource
from src.memory.service import MemoryService
from src.memory.vnext import MemoryAccessContext
from src.memory.vnext_contracts import ArtifactRef, Scope
from src.models.enums import AgentName, Market, ResearchScopeType
from src.models.identifiers import AssetId
from src.repositories import DuckDBDatabase, FaissVectorRepository, MemoryItemRepository
from src.schemas.agents import RoleEvidenceManifest, RoleEvidenceManifestEntry
from src.schemas.common import SourceReference
from src.services.embedding import FakeEmbeddingService
from src.services.native_preservation import NativePreserver
from src.services.research_vnext.g97_sources import AVGOSources
from src.services.research_vnext.g98_numeric import DisclosureNumericBinding
from src.services.research_vnext.radar_pilot import encoded
from src.services.research_vnext.source_task_binding import (
    SourceSelection,
    SourceTaskBinder,
    SourceTaskSpec,
)
from tools.g100_hybrid_memory import retained_sources
from tools.g101_vertical import inputs


def load(path: Path) -> Any:
    """Read explicit retained test artifacts."""
    return json.loads(path.read_bytes())


def store(directory: Path) -> NativePreserver:
    """Reopen an existing exact native session, never collect data."""
    s = load(directory / "session.json")
    return NativePreserver(
        directory,
        provider=s["provider"],
        owner=s["owner"],
        run_id=s["run_id"],
        retention_authority=s["retention_authority"],
        allowed_endpoints=tuple(s["endpoints"]),
        normalization_version=s["normalization_version"],
    )


def metadata(root: Path, relative: str) -> RegisteredNarrativeSource:
    """Resolve actual original issuer submissions for either fixture."""
    p = root / relative
    s = load(p)
    receipt = s["receipt"]
    native_store = store(
        p.parent / "sec-requests" / f"{receipt['request']['attempt']:02}-native"
    )
    native = native_store.recover(receipt["manifest_sha256"])
    return RegisteredNarrativeSource(
        native_store,
        receipt["manifest_sha256"],
        SourceReference(
            document_id=native.acquisition.artifact_id,
            provider=native.acquisition.provider,
            source_url=native.acquisition.endpoint,
        ),
        native.acquisition.body_sha256,
        native.acquisition.owner,
        "SEC issuer metadata",
        "SEC_FILING",
        "UTF8_TEXT",
        None,
        None,
        None,
        "REAL_RETAINED_SOURCE",
    )


@dataclass
class Control:
    """Composition-root fixtures, not a second source or authorization service."""

    binder: SourceTaskBinder
    spec: SourceTaskSpec
    task_ref: ArtifactRef
    access: MemoryAccessContext
    bundle: ResearchContextBundle
    artifacts: dict[str, bytes]
    legacy: AVGOSources | None
    numeric: DisclosureNumericBinding | None

    def register(self, spec: SourceTaskSpec) -> ArtifactRef:
        """Freeze a distinct engineering task before its negative/positive check."""
        raw = spec.model_dump_json().encode()
        ref = ArtifactRef(
            artifact_id=spec.task_id,
            sha256_digest=hashlib.sha256(raw).hexdigest(),
            version=spec.schema_version,
            owner=spec.issuer,
            available_at=spec.research_as_of,
            observed_at=spec.research_as_of,
            ingested_at=spec.research_as_of,
        )
        self.artifacts[ref.sha256_digest] = raw
        return ref

    def kwargs(self) -> dict[str, Any]:
        """Use assigned role/run/access, never model-supplied identity."""
        return dict(
            run_id=self.spec.run_id,
            role=AgentName.FUNDAMENTAL_ANALYST,
            access=self.access,
            memory_bundle=self.bundle,
            memory_refs={},
            model_name="OFFLINE_NO_DISPATCH",
        )


def control(root: Path, output: Path, population: str) -> Control:
    """Compose two real retained populations through the exact same binder."""
    at = datetime.now(UTC)
    role = AgentName.FUNDAMENTAL_ANALYST
    mandate, mandate_artifacts = inputs(root)
    artifacts: dict[str, bytes] = {}
    for value in mandate_artifacts.values():
        raw = encoded(value)
        artifacts[hashlib.sha256(raw).hexdigest()] = raw
    mandate_raw = mandate.model_dump_json().encode()
    mandate_ref = ArtifactRef(
        artifact_id=mandate.record_id,
        sha256_digest=hashlib.sha256(mandate_raw).hexdigest(),
        version=mandate.schema_version,
        owner=mandate.owner,
        available_at=mandate.created_at,
        observed_at=mandate.created_at,
        ingested_at=mandate.created_at,
    )
    artifacts[mandate_ref.sha256_digest] = mandate_raw
    legacy = AVGOSources(root, at) if population == "legacy" else None
    rows = []
    if legacy is not None:
        issuer, cik = "US:AVGO", "0001730168"
        registry = retained_sources(legacy)
        meta = metadata(root, legacy.sources["A"]["SEC_metadata_file"])
        for fact in legacy.facts.values():
            src = registry[fact["source_id"]]
            text = legacy.texts[fact["source_id"]]
            a, b = fact["text_span"]
            positions = [i for i in range(a, b) if text.startswith(fact["quote"], i)]
            assert len(positions) == 1
            start = positions[0]
            rows.append(
                (
                    fact["id"],
                    src,
                    EvidenceLocator(
                        kind="NORMALIZED_UNICODE",
                        start=start,
                        end=start + len(fact["quote"]),
                        normalization_sha256=hashlib.sha256(text.encode()).hexdigest(),
                        quote=fact["quote"],
                    ),
                )
            )
    else:
        base = root / "artifacts/g105/retained/artifacts/g104-r1"
        assert load(base / "NO_GO_HANDOFF.json")["stop_AAOI_paid_task"] is True
        qualified = load(base / "qualification-v3/SOURCE_REGISTRY_QUALIFICATION.json")
        registry = {}
        issuer, cik = qualified[0]["owner"], qualified[0]["CIK"]
        meta = metadata(
            root,
            "artifacts/g94/38f50a9e91af5f1065bcaa5753a4ddfd847f4246e752f888dbc00b492ec95985.source.json",
        )
        locators = load(base / "qualification-v3/EXACT_EVIDENCE_LOCATORS.json")
        for q in qualified:
            ns = store(
                base
                / "sec-requests"
                / f"{q['source_receipt']['request']['attempt']:02}-native"
            )
            source = RegisteredNarrativeSource(
                ns,
                q["native_manifest_sha256"],
                SourceReference(
                    document_id=q["id"],
                    provider=ns.provider,
                    source_url=q["source_url"],
                ),
                q["raw_entity_sha256"],
                q["owner"],
                "SEC issuer disclosure",
                "SEC_FILING",
                "HTML",
                q["report_period_end"],
                datetime.fromisoformat(
                    q["filing_acceptance_time"].replace("Z", "+00:00")
                ),
                q["filing_date"],
                "REAL_RETAINED_SOURCE",
            )
            registry[q["id"]] = source
            loc = next(x for x in locators if x["source_id"] == q["id"])
            rows.append(
                (loc["id"], source, EvidenceLocator.model_validate(loc["locator"]))
            )
    scope = Scope(scope_type=ResearchScopeType.ASSET, scope_id="ASSET:" + issuer)
    selections = []
    seen_locators: set[tuple[str | None, str]] = set()
    for fid, src, loc in rows:
        key = (src.source_ref.document_id, loc.sha256)
        if key in seen_locators:
            continue
        seen_locators.add(key)
        native = src.store.recover(src.manifest_identity)
        proposal = NarrativeProposal(
            record_id=fid,
            owner=role.value,
            scope=scope,
            episode_id="ENGINEERING_INPUT_ONLY",
            research_state_id="NO_STATE_CREATED",
            created_at=at,
            research_as_of=at,
            subject=issuer,
            statement=loc.quote,
            source_ref=src.source_ref,
            evidence_locator=loc,
            source_sha256=src.raw_sha256,
            attribution=src.publisher,
            relevant_period=src.relevant_period,
            kind="DIRECT_SOURCE",
            retention_horizon="MEDIUM",
        )
        selections.append(
            SourceSelection(
                proposal=proposal,
                receipt_identity=src.manifest_identity,
                source_revision=native.acquisition.revision_id,
                available_at=max(
                    native.ingested_at,
                    native.acquisition.observed_at,
                    src.published_at or native.ingested_at,
                ),
            )
        )
    spec = SourceTaskSpec(
        task_id="ENGINEERING_FIXTURE:g105:" + population,
        run_id="ENGINEERING_FIXTURE:g105:" + population + ":fundamental",
        run_role=role,
        issuer=issuer,
        cik=cik,
        scope=scope,
        research_as_of=at,
        permitted_roles=(role, AgentName.NEWS_EVENT_ANALYST),
        sources=tuple(selections),
        mandate=mandate_ref if legacy is not None else None,
        disposition="RESEARCH_ELIGIBLE" if legacy is not None else "NO_GO",
    )

    def reader(reference: ArtifactRef) -> bytes:
        return artifacts[reference.sha256_digest]

    numeric = DisclosureNumericBinding(legacy, root) if legacy is not None else None

    def canonical_evidence(task: SourceTaskSpec) -> RoleEvidenceManifest:
        """Read original producer registration; do not certify caller fields."""
        if numeric is None:
            raise ValueError("G105_R1_NO_ORIGINAL_CANONICAL_PRODUCER")
        original = numeric.verify()  # Reopens and verifies existing native sources.
        owners = {n.acquisition.owner for n in original.native.values()}
        if (
            owners != {task.issuer}
            or task.scope.scope_id != "ASSET:" + task.issuer
            or task.research_as_of != original.at
            or task.run_role not in (role, AgentName.NEWS_EVENT_ANALYST)
        ):
            raise ValueError("G105_R1_ORIGINAL_PRODUCER_SCOPE_TIME")
        return RoleEvidenceManifest(
            agent_name=task.run_role, entries=tuple(original.entries)
        )

    binder = SourceTaskBinder(
        sources={s.source_ref.document_id or "": s for s in registry.values()},
        issuer_metadata=meta,
        reader=reader,
        enabled=True,
        canonical_evidence=canonical_evidence,
    )
    db = DuckDBDatabase(output / "memory.duckdb")
    db.bootstrap()
    embed = FakeEmbeddingService(
        {"g105 query": [1.0, 0.0]}, model_name="g105-offline-fixture"
    )
    service = MemoryService(
        MemoryItemRepository(db),
        FaissVectorRepository(
            output / "faiss",
            embedder_model=embed.model_name,
            embedding_dim=embed.dimension,
        ),
        embed,
    )
    bundle = service.retrieve_context(
        ResearchContextRequest(
            query_text="g105 query",
            as_of=at,
            market=Market.US,
            asset_id=AssetId(issuer),
            namespace_keys=[scope.scope_id],
        )
    )
    c = Control(
        binder,
        spec,
        mandate_ref,
        MemoryAccessContext(owner=role.value, role=role, scopes=(scope,), enabled=True),
        bundle,
        artifacts,
        legacy,
        numeric,
    )
    c.task_ref = c.register(spec)
    return c


def legacy_evidence(c: Control) -> tuple[RoleEvidenceManifestEntry, ...]:
    """Use the two frozen G98 engineering claims, not a filtered Agent result."""
    if c.legacy is None:
        return ()
    draft = (
        load(
            c.numeric.root / "artifacts/g98/engineering-input/fundamental_analyst.json"
        )
        if c.numeric is not None
        else {}
    )
    ids = {
        eid for claim in draft["analysis"]["claims"] for eid in claim["evidence_ids"]
    }
    entries = tuple(e for e in c.legacy.entries if e.evidence_id in ids)
    assert len(entries) == len(ids) == 2
    return entries


def run(root: Path, output: Path) -> None:
    """Save actual readsets, input projections and NO_GO refusal without dispatch."""
    output.mkdir(parents=True, exist_ok=False)
    from src.schemas.agents import RoleEvidenceManifest

    receipts = []
    for name in ("legacy", "new-issuer"):
        c = control(root, output / name, name)
        bound = c.binder.bind(c.task_ref, **c.kwargs())
        evidence = RoleEvidenceManifest(
            agent_name=AgentName.FUNDAMENTAL_ANALYST,
            entries=legacy_evidence(c),
        )
        denial = None
        try:
            inv, _ = c.binder.invocation(
                c.task_ref, **c.kwargs(), evidence=evidence, native_numeric=c.numeric
            )
            (output / (name + "-invocation.json")).write_text(
                inv.model_dump_json(indent=2) + "\n"
            )
        except ValueError as exc:
            denial = str(exc)
        assert denial == ("G105_NO_GO" if name == "new-issuer" else None), denial
        for label, value in [
            ("source-readset", bound.source_reads),
            ("memory-readset", bound.memory_reads),
            ("task-request", bound.request),
            ("task-spec", c.spec),
        ]:
            (output / (name + "-" + label + ".json")).write_text(
                value.model_dump_json(indent=2) + "\n"
            )
        receipts.append(
            {
                "population": name,
                "issuer": c.spec.issuer,
                "cik": c.spec.cik,
                "source_statements": len(bound.source_reads.records),
                "input_projection": denial or "BUILT_NOT_DISPATCHED",
                "world_fact_authority": False,
                "new_agent_runs": 0,
                "new_provider_calls": 0,
                "new_model_calls": 0,
            }
        )
    (output / "RECEIPT.json").write_text(json.dumps(receipts, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run(Path.cwd(), args.output)
