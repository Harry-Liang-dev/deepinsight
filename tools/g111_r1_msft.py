"""Offline MSFT longitudinal integration over G111/G100; never invoke a model."""

from __future__ import annotations

import argparse
import json
import shutil
import socket
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.memory.contracts import ResearchContextRequest
from src.memory.hybrid import (
    HybridRead,
    admit_source_observation,
    retrieve_observations,
)
from src.memory.hybrid_contracts import EvidenceLocator, NarrativeProposal
from src.memory.hybrid_sources import NativeLocatorResolver, RegisteredNarrativeSource
from src.memory.temporal_delta import (
    ContentNode,
    ObservedContent,
    TemporalSource,
    run_temporal_cycle,
    selective_impact,
)
from src.memory.temporal_relations import (
    bind_relation,
    read_relations,
    require_delivered,
)
from src.memory.vnext_contracts import Scope
from src.models.enums import AgentName, Market, MemoryLevel, ResearchScopeType
from src.schemas.common import SourceReference
from src.schemas.research_v2_shared import digest
from src.services.native_preservation import NativePreserver, blob_hash
from src.services.phase5d_temporal import receipt_bytes
from src.services.research_vnext.native_numeric_binding import scaled_decimal
from src.services.sec_native_financial import D, X, _Tree
from tools.g111_temporal_memory import ReplayMemory, episode, read

SOURCE_IDS = ("G105-GET-05", "G105-GET-09", "G105-GET-12")
EXTRACTOR = "g111-r1-w3-msft-frozen-population-v1"


def save(path: Path, value: Any) -> None:
    """Write an experiment receipt in its explicit new output directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def w3_identity(value: Any) -> str:
    """Match the original W3 source-population identity, not model text similarity."""
    return blob_hash(json.dumps(value, sort_keys=True, ensure_ascii=False).encode())


class MSFTMemory(ReplayMemory):
    """Issuer adapter using the original MemoryService, G100 and G111 processor."""

    def __init__(self, root: Path, output: Path) -> None:
        super().__init__(root, output, "US:MSFT")
        self.package = root / "artifacts/g111-r1/w3-input"
        self.case = self.package / "artifacts/g111"
        self.facts = read(self.case / "inputs/T1_FACT_OBSERVATIONS.json")
        self.seed_rows = read(self.case / "inputs/T0_MEMORY_SEED_PROPOSALS.json")[
            "records"
        ]
        self.evidences: dict[str, dict[str, Any]] = {}
        self.numeric_trees: dict[str, _Tree] = {}
        self.source_catalog = {
            s["id"]: s
            for s in read(self.package / "artifacts/g110/SOURCE_READSET.json")[
                "sources"
            ]
        }
        self.temporal_sources = {sid: self.register_source(sid) for sid in SOURCE_IDS}
        self.resolver = NativeLocatorResolver(self.sources)
        self.check_frozen_population()
        scopes = {self.scope.scope_id: self.scope}
        known_ids = {
            ContentNode.model_validate_json(b).memory_id
            for _, b in self.journal.entries("g111-nodes")
        }
        for _, body in self.journal.entries("g100-source-catalog"):
            row = json.loads(body)
            proposal = row["record"]["proposal"]
            if proposal["subject"] == "US:MSFT":
                if row["result"]["memory_id"] not in known_ids:
                    raise ValueError("G111_R1_UNMAPPED_EXISTING_MSFT_IDENTITY")
                if proposal["owner"] == self.access.owner:
                    scope = Scope.model_validate(proposal["scope"])
                    scopes[scope.scope_id] = scope
        self.history_scopes = tuple(scopes.values())
        self.access = self.access.model_copy(update={"scopes": self.history_scopes})

    def register_source(self, sid: str) -> TemporalSource:
        """Recover a private copy of original acquisition bytes; never backdate it."""
        dest = self.output / "native" / sid
        if not dest.exists():
            shutil.copytree(self.root / "artifacts/g111-r1/native-inputs" / sid, dest)
        session = read(dest / "session.json")
        store = NativePreserver(
            dest,
            provider=session["provider"],
            owner=session["owner"],
            run_id=session["run_id"],
            retention_authority=session["retention_authority"],
            allowed_endpoints=tuple(session["endpoints"]),
            normalization_version=session["normalization_version"],
        )
        entry = self.source_catalog[sid]
        manifest = store.recover(entry["native_manifest_identity"])
        raw = (dest / (manifest.acquisition.body_sha256 + ".raw")).read_bytes()
        if (
            blob_hash(raw) != entry["raw_sha256"]
            or manifest.acquisition.owner != "US:MSFT"
        ):
            raise ValueError("G111_R1_SOURCE_BINDING")
        self.raws[sid] = raw
        self.sources[sid] = RegisteredNarrativeSource(
            store,
            manifest.content_identity,
            SourceReference(
                document_id=sid,
                provider="sec_edgar",
                source_url=manifest.acquisition.endpoint,
            ),
            blob_hash(raw),
            "US:MSFT",
            "Microsoft Corporation",
            "SEC_FILING",
            "HTML",
            None,
            None,
            None,
            "REAL_RETAINED_SOURCE",
        )
        return TemporalSource(
            source_id=sid,
            raw_sha256=blob_hash(raw),
            subject="US:MSFT",
            scope_ids=("ASSET:US:MSFT",),
            event_at=None,
            available_at=max(manifest.ingested_at, manifest.acquisition.observed_at),
            observed_at=manifest.acquisition.observed_at,
            ingested_at=manifest.ingested_at,
            origin="REAL_RETAINED_SOURCE",
        )

    def check_frozen_population(self) -> None:
        """Verify W3 input bytes before any semantic interpretation."""
        path = self.root / "artifacts/g111-r1/W3_SOURCE_MANIFEST.json"
        if (
            blob_hash(path.read_bytes())
            != "6f6555bc32268369090d542822129e49b49e78d69f1e162277e35c3efa926304"
        ):
            raise ValueError("G111_R1_W3_MANIFEST_PIN")
        manifest = read(path)
        expected = {m["path"]: m["sha256"] for m in manifest["members"]}
        for p in self.package.rglob("*"):
            if p.is_file() and str(p.relative_to(self.package)) in expected:
                if (
                    blob_hash(p.read_bytes())
                    != expected[str(p.relative_to(self.package))]
                ):
                    raise ValueError("G111_R1_FROZEN_INPUT_CHANGED")
        for fact in self.facts:
            fid = "G111:OBS:" + w3_identity(
                {k: fact[k] for k in ("issuer", "series", "period", "value")}
            )
            if (
                fact["id"] != fid
                or fact["issuer"] != "US:MSFT"
                or fact["world_fact_authority"]
                or fact["agent_generated"]
            ):
                raise ValueError("G111_R1_POPULATION_IDENTITY")

    def proposal(self, evidence: dict[str, Any], record_id: str) -> NarrativeProposal:
        """Bind an exact quote to current development Episode and original source."""
        sid = evidence["source_id"]
        if evidence["native_manifest_identity"] != self.sources[sid].manifest_identity:
            raise ValueError("G111_R1_NATIVE_MANIFEST")
        return NarrativeProposal(
            record_id=record_id,
            owner=self.access.owner,
            scope=self.scope,
            episode_id=self.ep.episode_id,
            research_state_id=self.ep.research_state_id,
            created_at=self.at,
            research_as_of=self.ep.research_as_of,
            subject="US:MSFT",
            statement=evidence["quote"],
            source_ref=self.sources[sid].source_ref,
            evidence_locator=EvidenceLocator(
                **evidence["locator"], quote=evidence["quote"]
            ),
            source_sha256=evidence["raw_sha256"],
            attribution="Microsoft Corporation",
            relevant_period=None,
            kind="DIRECT_SOURCE",
            retention_horizon="MEDIUM",
        )

    def validate_support(self, evidence: dict[str, Any]) -> None:
        """Reuse G100 native quote/time validation before each source support use."""
        self.access.require("READ_HISTORY", self.scope)
        self.resolver.validate(self.proposal(evidence, "support:" + digest(evidence)))

    def check_numeric(self, fact: dict[str, Any]) -> None:
        """Recheck frozen G110 native tags with original parser and decimal routine."""
        n = fact.get("numeric_observation")
        if n is None:
            return
        originals = read(
            self.package
            / "artifacts/g110/evaluator_only/NATIVE_OPERAND_OBSERVATIONS.json"
        )["facts"]
        if n not in originals or fact["value"] != n["value_usd"]:
            raise ValueError("G111_R1_NATIVE_OPERAND")
        sid = n["source_id"]
        if (
            fact["period"]
            != {
                "kind": "QUARTER_DURATION",
                "start": n["period"]["startdate"],
                "end": n["period"]["enddate"],
            }
            or fact["series"]
            != w3_identity({k: n[k] for k in ("concept", "dimensions", "unit")})
            or n["raw_sha256"] != self.sources[sid].raw_sha256
        ):
            raise ValueError("G111_R1_NATIVE_PERIOD_SCOPE")
        if sid not in self.numeric_trees:
            self.numeric_trees[sid] = _Tree(
                receipt_bytes(
                    self.sources[sid]
                    .store.recover(self.sources[sid].manifest_identity)
                    .acquisition
                ).decode()
            )
        t = self.numeric_trees[sid]
        nodes = list(t.root.iter())
        node = next(x for x in nodes if x.attrib.get("id") == n["element_id"])
        context = next(
            x for x in nodes if x.attrib.get("id") == node.attrib["contextref"]
        )
        ns = t.namespaces[node]
        literal = "".join(node.itertext()).strip()
        unit_node = next(
            x for x in nodes if x.attrib.get("id") == node.attrib["unitref"]
        )
        measure = next(x for x in unit_node.iter() if x.tag == "{" + X + "}measure")
        period = {
            x.tag.split("}")[-1]: (x.text or "").strip()
            for x in context.iter()
            if x.tag
            in {"{" + X + "}" + k for k in ("identifier", "startdate", "enddate")}
        }
        dimensions = [
            {
                "axis": t.qname(x.attrib["dimension"], t.namespaces[x]),
                "member": t.qname(x.text or "", t.namespaces[x]),
            }
            for x in context.iter()
            if x.tag == "{" + D + "}explicitmember"
        ]
        value = scaled_decimal(
            literal, int(node.attrib["scale"]), node.attrib.get("sign", "")
        )
        if (
            t.qname(node.attrib["name"], ns) != n["concept"]
            or literal != n["literal"]
            or period != n["period"]
            or dimensions != n["dimensions"]
            or t.qname(measure.text or "", t.namespaces[measure]) != n["unit"]
            or value != Decimal(n["value_usd"])
            or period["identifier"] != "0000789019"
        ):
            raise ValueError("G111_R1_NATIVE_ASPECT_MISMATCH")

    def content(
        self, fact: dict[str, Any], evidence: dict[str, Any]
    ) -> ObservedContent:
        """Preserve complete periods, units and original natural-language values."""
        locator_id = digest(evidence)
        self.evidences[locator_id] = evidence
        return ObservedContent(
            subject=fact["issuer"],
            concept=fact["series"],
            period=json.dumps(fact["period"], sort_keys=True),
            unit=fact.get("numeric_observation", {}).get(
                "unit", "SOURCE_NATURAL_LANGUAGE"
            ),
            basis="W3_FROZEN_SOURCE_POPULATION:" + fact["period"]["kind"],
            value_literal=json.dumps(fact["value"], sort_keys=True, ensure_ascii=False),
            locator=locator_id,
            quote=evidence["quote"],
            source_id=evidence["source_id"],
            raw_sha256=evidence["raw_sha256"],
            event_at=None,
            period_end=(
                date.fromisoformat(fact["period"]["end"])
                if "end" in fact["period"]
                else None
            ),
        )

    def extract(self, sid: str) -> tuple[ObservedContent, ...]:
        """Extract only frozen and verified observations supported by this source."""
        result = []
        for fact in self.facts:
            for e in fact["evidence"]:
                if e["source_id"] == sid:
                    self.validate_support(e)
                    self.check_numeric(fact)
                    result.append(self.content(fact, e))
        return tuple(result)

    def admit(self, c: ObservedContent) -> str:
        """Persist exact attributable text through the original checked G100 API."""
        p = self.proposal(self.evidences[c.locator], c.content_id)
        self.vectors[self.resolver.validate(p).model_dump_json()] = [1.0, 0.0, 0.0]
        service = self.service()
        result = admit_source_observation(
            service,
            p,
            resolver=self.resolver,
            access=self.access,
            journal=self.journal,
            episode=self.ep,
            enabled=True,
        )
        return result.result.memory_id

    def retrieve(self, label: str) -> HybridRead:
        """Reopen permitted history and obtain actual G84 delivery receipts."""
        self.at = datetime.now(UTC)
        ep = episode(self.at, label, "US:MSFT")
        scopes = {s.scope_id: s for s in self.history_scopes}
        for scope in self.history_scopes:
            self.access.require("READ_HISTORY", scope)
        receiving = Scope(
            scope_type=ResearchScopeType.RESEARCH_EPISODE,
            scope_id="EPISODE:" + ep.episode_id,
        )
        self.access = self.access.model_copy(
            update={"scopes": tuple(scopes.values()) + (receiving,)}
        )
        return retrieve_observations(
            self.service(),
            resolver=self.resolver,
            access=self.access,
            journal=self.journal,
            request=ResearchContextRequest(
                query_text="g111 retained context",
                as_of=self.at,
                market=Market.US,
                namespace_keys=list(scopes),
                memory_levels=[MemoryLevel.L2],
                top_k_per_section=100,
            ),
            episode=ep,
            run_id=label,
            as_created=self.at,
            lane="ATTRIBUTED_SOURCES",
        )

    def population(self) -> dict[str, str]:
        """Fingerprint complete existing rows, including their original vector IDs."""
        with self.db.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM memory_items ORDER BY memory_id"
            ).fetchall()
        return {
            str(row[0]): blob_hash(json.dumps(row, default=str).encode())
            for row in rows
        }

    def snapshot(self) -> dict[str, Any]:
        """Retain exact ordered audit streams and all persisted Memory IDs."""
        streams = (
            "g111-nodes",
            "g111-sources",
            "g111-source-contents",
            "g111-relations",
            "g111-invalidations",
            "g111-r1-support",
            "g111-r1-relations",
        )
        return {s: self.journal.entries(s) for s in streams}

    def id_map(self) -> dict[str, str]:
        """Resolve W3 observation aliases through actual persisted G111 content IDs."""
        nodes = {
            k: ContentNode.model_validate_json(v)
            for k, v in self.journal.entries("g111-nodes")
        }
        result = {}
        for f in self.facts:
            c = self.content(f, f["evidence"][0])
            if c.content_id in nodes:
                result[f["id"]] = nodes[c.content_id].memory_id
        return result

    def process(
        self, sid: str, label: str, source_cutoff: datetime | None = None
    ) -> dict[str, Any]:
        """Read and validate eligibility before hash-based skip or source processing."""
        self.access.require("APPEND_EVENT", self.scope)
        available = self.temporal_sources[sid].available_at
        if source_cutoff is not None and (
            available is None or available > source_cutoff
        ):
            raise ValueError("G111_R1_SOURCE_AFTER_REPLAY_CUTOFF")
        delivery = self.retrieve(label + "-before")
        allowed = require_delivered(delivery, self.journal, self.access)
        related = self.id_map()
        if not set(related.values()) <= allowed:
            raise ValueError("G111_R1_EXISTING_MEMORY_NOT_ELIGIBLE")
        supports = [
            (f, e) for f in self.facts for e in f["evidence"] if e["source_id"] == sid
        ]
        for _, e in supports:
            self.validate_support(e)
        cycle = run_temporal_cycle(
            self.journal,
            self.temporal_sources[sid],
            raw=self.raws[sid],
            as_of=self.at,
            created_at=self.at,
            extract=lambda: self.extract(sid),
            admit=self.admit,
            extractor_identity=EXTRACTOR,
        )
        mapping = self.id_map()
        with self.journal.serialized():
            existing = {k for k, _ in self.journal.entries("g111-r1-support")}
            for f, e in supports:
                key = digest((f["id"], e))
                if key not in existing:
                    row = dict(
                        fact_id=f["id"],
                        memory_id=mapping[f["id"]],
                        evidence=e,
                        created_at=self.at.isoformat(),
                        support_coverage=(
                            "AZURE_MEMBERSHIP_ONLY"
                            if sid == "G105-GET-12"
                            else "FROZEN_OBSERVATION_SOURCE_CONTEXT"
                        ),
                    )
                    self.journal.append(
                        "g111-r1-support",
                        key,
                        json.dumps(row, sort_keys=True),
                        len(self.journal.entries("g111-r1-support")),
                    )
        return dict(
            source_id=sid,
            source_replay_cutoff=source_cutoff.isoformat() if source_cutoff else None,
            temporal_cycle=cycle.model_dump(mode="json"),
            memory_readset_before=delivery.read_set.model_dump(mode="json"),
            impact_plans=selective_impact(cycle),
            source_history_classification=(
                "HISTORICAL_ANNUAL_BACKFILL_ADDITIONAL_SUPPORT"
                if sid == "G105-GET-12"
                else "RETAINED_DISCLOSURE"
            ),
            business_dispatch_authorized=False,
            business_action=(
                "DETERMINISTIC_HISTORICAL_SUPPORT_ONLY"
                if sid == "G105-GET-12"
                else "W3_SELECTIVE_RESEARCH_CANDIDATE"
            ),
            impact_plans_are_dependency_candidates_not_dispatch=True,
        )

    def fetch_evidence(self, evidence: dict[str, Any]) -> dict[str, Any]:
        """Fetch exact local source coordinates after ACL/hash/time validation."""
        self.validate_support(evidence)
        row = dict(
            source_id=evidence["source_id"],
            source_sha256=evidence["raw_sha256"],
            native_manifest_identity=evidence["native_manifest_identity"],
            locator=evidence["locator"],
            returned_text=evidence["quote"],
            research_as_of=self.at.isoformat(),
            source_clocks=self.temporal_sources[evidence["source_id"]].model_dump(
                mode="json"
            ),
            status="RETRIEVED_NOT_MODEL_CONSUMED",
            retrieved_by_role=self.access.role,
        )
        with self.journal.serialized():
            self.journal.append(
                "g111-r1-source-reads",
                digest(row),
                json.dumps(row, sort_keys=True),
                len(self.journal.entries("g111-r1-source-reads")),
            )
        return row


def census(
    memory: MSFTMemory, before_ids: dict[str, str], before_support: set[str]
) -> list[dict[str, Any]]:
    """Measure actual ID and support changes without using oracle counts."""
    after = memory.id_map()
    added = [
        json.loads(body)
        for key, body in memory.journal.entries("g111-r1-support")
        if key not in before_support
    ]
    result = []
    for f in memory.facts:
        fid = f["id"]
        kind = (
            "NEW_FACT"
            if fid not in before_ids
            else (
                "NEW_EVIDENCE_FOR_EXISTING_FACT"
                if any(r["fact_id"] == fid for r in added)
                else "UNCHANGED"
            )
        )
        result.append(
            dict(
                fact_id=fid,
                memory_id=after[fid],
                kind=kind,
                observation={k: v for k, v in f.items() if k != "evidence"},
                added_evidence=[r["evidence"] for r in added if r["fact_id"] == fid],
                authority="SOURCE_OBSERVATION_ONLY",
            )
        )
    return result


def relation_bindings(memory: MSFTMemory, delivery: HybridRead) -> list[dict[str, Any]]:
    """Resolve frozen aliases to actual IDs and persist checked source-context edges."""
    proposals = read(memory.case / "expected/EXPECTED_RELATION_DELTA.json")["relations"]
    return [
        bind_relation(
            memory.journal,
            p,
            facts={f["id"]: f for f in memory.facts},
            seeds={s["record_id"]: s for s in memory.seed_rows},
            actual_ids=memory.id_map(),
            delivery=delivery,
            access=memory.access,
            validate_support=memory.validate_support,
            at=memory.at,
        ).model_dump(mode="json")
        for p in proposals
    ]


def research_inputs(
    memory: MSFTMemory,
    delivery: HybridRead,
    changes: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Construct two bounded W1 candidate requests; record provided versus consumed."""
    allowed = require_delivered(delivery, memory.journal, memory.access)
    mapping = memory.id_map()
    result: dict[str, Any] = {}
    if all(c["kind"] == "UNCHANGED" for c in changes):
        return result
    writer_access = memory.access
    for role in ("fundamental_analyst", "news_event_analyst"):
        memory.access = writer_access.model_copy(update={"role": AgentName(role)})
        delivery = memory.retrieve("g111-r1-candidate-" + role)
        allowed = require_delivered(delivery, memory.journal, memory.access)
        template = read(memory.case / "model-inputs" / (role + ".TASK_TEMPLATE.json"))
        historical_ids = [mapping[s["fact_id"]] for s in memory.seed_rows]
        if not set(historical_ids) <= allowed or not set(mapping.values()) <= allowed:
            raise ValueError("G111_R1_INPUT_NOT_DELIVERED")
        views = []
        for view in template["new_source_views"]:
            evidence = dict(
                source_id=view["source_id"],
                raw_sha256=view["raw_source_sha256"],
                native_manifest_identity=view["native_manifest_identity"],
                locator=view["locator"],
                quote=view["content"],
            )
            views.append(memory.fetch_evidence(evidence))
        records = [
            {
                "memory_id": r.result.memory_id,
                "source_record": r.record.model_dump(mode="json"),
            }
            for r in delivery.supplied_records
        ]
        result[role] = dict(
            schema_version="g111_r1_selective_candidate_v1",
            role=role,
            security="US:MSFT",
            task=template["task"],
            research_as_of=memory.at.isoformat(),
            memory_snapshot_id=digest(memory.snapshot()),
            source_readset=[
                {k: v for k, v in view.items() if k != "returned_text"}
                for view in views
            ],
            memory_readset=delivery.read_set.model_dump(mode="json"),
            historical_memory_ids=historical_ids,
            changed_observations=changes,
            relations=relations,
            source_attributed_memory=records,
            required_source_excerpt_views=views,
            affected_research_questions=[
                template["task"],
                "Does the recast change presentation rather than consolidated results?",
                "Which periods and allocations remain incomparable or uncertain?",
            ],
            lazy_evidence_interface="tools.g111_r1_msft.MSFTMemory.fetch_evidence(evidence)",
            evidence_request_fields=[
                "source_id",
                "raw_sha256",
                "native_manifest_identity",
                "locator",
                "quote",
            ],
            output_contract=template["output_contract"],
            role_schema_changed=False,
            status="PROVIDED_TO_W1_CANDIDATE_NOT_MODEL",
            retrieved_memory_ids=sorted(allowed),
            actually_consumed_memory_ids=[],
            qualified_agent_result_reuse="NOT_DEMONSTRATED",
            world_fact_authority=False,
            native_scientific_admission="BLOCKED",
            scientific_memory_writes=0,
            model_calls=0,
            dispatcher_unchanged=True,
        )
    memory.access = writer_access
    return result


def run_case(
    root: Path, output: Path, *, existing_storage: Path | None = None
) -> dict[str, Any]:
    """Run T0, T1, repeat and reopened retrieval without clearing an existing store."""
    output.mkdir(parents=True, exist_ok=False)
    mode = (
        "ACTUAL_EXISTING_MEMORY_DIFF"
        if existing_storage
        else "CONTROLLED_SOURCE_REPLAY"
    )
    if existing_storage:
        shutil.copytree(existing_storage, output / "storage")
    m = MSFTMemory(root, output)
    initial = m.snapshot()
    original_population = m.population()
    initial_ids = m.id_map()
    source_windows = read(m.case / "inputs/CASE.json")["cycles"]
    cutoffs = [
        (
            datetime.fromisoformat(c["source_replay_cutoff"])
            if mode == "CONTROLLED_SOURCE_REPLAY"
            else None
        )
        for c in source_windows
    ]
    t0 = m.process("G105-GET-05", mode + "-T0", cutoffs[0])
    t0read = m.retrieve(mode + "-T0-after")
    t0_ids = m.id_map()
    aliases = {s["record_id"]: t0_ids[s["fact_id"]] for s in m.seed_rows}
    save(
        output / "T0.json",
        dict(
            cycle=t0,
            alias_to_actual_memory_id=aliases,
            readset=t0read.read_set.model_dump(mode="json"),
            snapshot=m.snapshot(),
            created_at=m.at.isoformat(),
        ),
    )
    before_support = {k for k, _ in m.journal.entries("g111-r1-support")}
    t1 = [m.process(sid, mode + "-T1-" + sid, cutoffs[1]) for sid in SOURCE_IDS[1:]]
    t1read = m.retrieve(mode + "-T1-after")
    changes = census(m, t0_ids, before_support)
    relations = relation_bindings(m, t1read)
    inputs = research_inputs(m, t1read, changes, relations)
    t1_snapshot = m.snapshot()
    save(
        output / "T1.json",
        dict(
            cycles=t1,
            observation_delta=changes,
            actual_id_map=m.id_map(),
            relations=relations,
            readset=t1read.read_set.model_dump(mode="json"),
            snapshot=t1_snapshot,
        ),
    )
    save(output / "W1_SELECTIVE_RESEARCH_INPUT.json", inputs)
    repeat = [m.process(sid, mode + "-repeat-" + sid) for sid in SOURCE_IDS]
    repeat_read = m.retrieve(mode + "-repeat-after")
    repeated_relations = relation_bindings(m, repeat_read)
    assert m.snapshot() == t1_snapshot and repeated_relations == relations
    assert all(
        r["temporal_cycle"]["duplicate_research_skipped"]
        and r["temporal_cycle"]["admission_calls"] == 0
        for r in repeat
    )
    # A fresh composition instance reopens the same actual DB/index and native copies.
    reopened = MSFTMemory(root, output)
    next_read = reopened.retrieve(mode + "-next-cycle-reopened")
    next_relations = read_relations(
        reopened.journal, next_read, reopened.access, reopened.validate_support
    )
    actual_ids = reopened.id_map()
    assert set(actual_ids.values()) <= {
        r.artifact_id for r in next_read.read_set.memory_refs
    }
    assert len(next_relations) == len(relations)
    counts = {
        k: sum(c["kind"] == k for c in changes)
        for k in ("NEW_FACT", "NEW_EVIDENCE_FOR_EXISTING_FACT", "UNCHANGED")
    }
    expected = read(m.case / "expected/EXPECTED_FACT_DELTA.json")["source_oracle"]
    expected_map = {e["fact_id"]: e["kind"] for e in expected}
    comparison = [
        dict(
            fact_id=c["fact_id"],
            expected=expected_map[c["fact_id"]],
            actual=c["kind"],
            explanation=(
                "MATCH"
                if expected_map[c["fact_id"]] == c["kind"]
                else "Measured existing population/support differs; no count override"
            ),
        )
        for c in changes
    ]
    final_population = reopened.population()
    assert all(final_population.get(k) == v for k, v in original_population.items())
    report = dict(
        initial_population=original_population,
        final_population=final_population,
        all_existing_rows_preserved=True,
        schema_version="g111_r1_longitudinal_receipt_v1",
        mode=mode,
        initial_msft_population=len(initial_ids),
        initial_memory_snapshot=initial,
        t0_actual_memory_ids=aliases,
        t1_counts=counts,
        observation_comparison=comparison,
        actual_relation_bindings=len(relations),
        repeat_source_skip=len(repeat),
        duplicate_memory_writes=sum(
            r["temporal_cycle"]["admission_calls"] for r in repeat
        ),
        repeat=repeat,
        repeat_affected_research_topics=[],
        repeat_new_relation_edges=0,
        final_memory_snapshot=m.snapshot(),
        next_cycle_memory_readset=next_read.read_set.model_dump(mode="json"),
        next_cycle_relations=[r.model_dump(mode="json") for r in next_relations],
        stable_memory_ids=actual_ids,
        real_cross_scope="NOT_DEMONSTRATED",
        qualified_agent_result_reuse="NOT_DEMONSTRATED",
        actually_consumed=[],
        real_model_calls=0,
        new_provider_calls=0,
        scientific_memory_writes=0,
        native_scientific_admission="BLOCKED",
        w1_input="READY",
        w5_input="READY",
    )
    save(output / "result.json", report)
    for stream in (
        "g111-nodes",
        "g111-sources",
        "g111-r1-support",
        "g111-r1-relations",
        "g111-r1-source-reads",
    ):
        save(
            output / (stream + ".json"),
            [json.loads(body) for _, body in m.journal.entries(stream)],
        )
    return report


def main() -> None:
    """Run offline into a new output directory and preserve the original."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--existing-storage", type=Path, required=True)
    args = parser.parse_args()

    def denied(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("G111_R1_NETWORK_FORBIDDEN")

    socket.socket.connect = denied  # type: ignore[method-assign]
    socket.create_connection = denied
    root = Path(__file__).resolve().parents[1]
    args.output.mkdir(parents=True, exist_ok=False)
    results = {
        "actual": run_case(
            root, args.output / "actual", existing_storage=args.existing_storage
        ),
        "controlled": run_case(root, args.output / "controlled"),
    }
    save(
        args.output / "RESULTS.json",
        {
            k: {
                f: v[f]
                for f in (
                    "mode",
                    "initial_msft_population",
                    "t1_counts",
                    "actual_relation_bindings",
                    "repeat_source_skip",
                    "duplicate_memory_writes",
                    "real_model_calls",
                    "scientific_memory_writes",
                )
            }
            for k, v in results.items()
        },
    )
    print(json.dumps(read(args.output / "RESULTS.json")))


if __name__ == "__main__":
    main()
