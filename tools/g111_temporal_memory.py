"""Replay archived META filings into isolated G100 development Memory; no network."""

from __future__ import annotations

import argparse
import calendar
import gzip
import json
import re
import shutil
import socket
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from src.memory.contracts import ResearchContextRequest
from src.memory.hybrid import admit_source_observation, retrieve_observations
from src.memory.hybrid_contracts import EvidenceLocator, NarrativeProposal
from src.memory.hybrid_sources import NativeLocatorResolver, RegisteredNarrativeSource
from src.memory.service import MemoryService
from src.memory.temporal_delta import (
    ObservedContent,
    TemporalSource,
    eligible_nodes,
    run_temporal_cycle,
    selective_impact,
)
from src.memory.vnext import MemoryAccessContext
from src.memory.vnext_contracts import Scope
from src.models.enums import AgentName, Market, MemoryLevel, ResearchScopeType
from src.repositories import DuckDBDatabase, FaissVectorRepository, MemoryItemRepository
from src.repositories.memory_journal import MemoryJournalRepository
from src.schemas.common import SourceReference
from src.schemas.research_data import DataCapability, ResearchDataBundle
from src.schemas.research_episode import ResearchEpisode, ResearchEpisodeBuildInput
from src.schemas.research_state import ResearchStateBuildInput
from src.schemas.research_v2_shared import digest
from src.services.embedding import FakeEmbeddingService
from src.services.native_preservation import NativePreserver, blob_hash
from src.services.research_episode import ResearchEpisodeBuilder
from src.services.research_state import ResearchStateBuilder
from tools.g109_meta_review import observations


def read(path: Path) -> Any:
    """Read retained JSON only."""
    return json.loads(path.read_bytes())


def period_basis(period: dict[str, str]) -> str:
    """Separate calendar quarters, instants and explicitly same-start durations."""
    prefix = "CONSOLIDATED_NO_DIMENSIONS:"
    if "instant" in period:
        return prefix + "INSTANT"
    start = date.fromisoformat(period["startdate"])
    end = date.fromisoformat(period["enddate"])
    if (
        start.year == end.year
        and start.month in (1, 4, 7, 10)
        and start.day == 1
        and end.month == start.month + 2
        and end.day == calendar.monthrange(end.year, end.month)[1]
    ):
        return prefix + "CALENDAR_QUARTER"
    return prefix + "DURATION_START:" + start.isoformat()


def episode(at: datetime, name: str, asset_id: str = "US:META") -> ResearchEpisode:
    """Use original builders with explicitly empty structured/scientific inputs."""
    body: dict[str, Any] = dict(
        bundle_id="rdb_" + digest(name)[:24],
        input_fingerprint=digest(name),
        asset_id=asset_id,
        as_of=at,
        window_start=at.date(),
        window_end=at.date(),
        dataset_version="g111-source-attribution-only",
    )
    for c in DataCapability:
        body[c.value] = dict(
            capability=c,
            status="missing",
            as_of=at,
            freshness=dict(
                status="unknown",
                evaluated_at=at,
                policy_name="g111-no-canonical-input",
                policy_version="1",
                reason="No canonical structured admission",
            ),
            quality=dict(
                status="unknown",
                observation_count=0,
                source_count=0,
                reason="No scientific admission",
            ),
            requested_field_count=0,
            available_field_count=0,
        )
    state = ResearchStateBuilder().build(
        ResearchStateBuildInput(
            research_data_bundle=ResearchDataBundle.model_validate(body),
            accepted_claims=(),
            source_run_id=name,
        )
    )
    return ResearchEpisodeBuilder().build(
        ResearchEpisodeBuildInput(
            research_state=state,
            agent_traces=(),
            created_at=at,
            missing_metadata=("NO_AGENT_EXECUTION",),
        )
    )


class ReplayMemory:
    """Composition of original G100 admission/retrieval and original storage."""

    def __init__(self, root: Path, output: Path, asset_id: str = "US:META") -> None:
        self.root, self.output = root, output
        self.at = datetime.now(UTC)
        self.ep = episode(self.at, "g111-initial", asset_id)
        self.scope = Scope(
            scope_type=ResearchScopeType.RESEARCH_EPISODE,
            scope_id="EPISODE:" + self.ep.episode_id,
        )
        self.access = MemoryAccessContext(
            owner="g111-development",
            role=AgentName.FUNDAMENTAL_ANALYST,
            scopes=(self.scope,),
            enabled=True,
        )
        self.sources: dict[str, RegisteredNarrativeSource] = {}
        self.raws: dict[str, bytes] = {}
        self.locators: dict[str, tuple[int, int]] = {}
        self.vectors = {"g111 retained context": [1.0, 0.0, 0.0]}
        self.db = DuckDBDatabase(output / "storage/memory.duckdb")
        self.db.bootstrap()
        self.journal = MemoryJournalRepository(self.db)
        self.journal.bootstrap()
        self.embedding_calls = 0

    def source(self, sid: str, wrapper: Path, period: str) -> TemporalSource:
        """Verify a copied native transaction with original clocks."""
        w = read(wrapper)
        receipt = w["receipt"]
        native = (
            Path(receipt["manifest_path"]).parent
            if "manifest_path" in receipt
            else wrapper.parent / "sec-requests/01-native"
        )
        pinned = self.root / "artifacts/g111/native-inputs" / sid
        if pinned.is_dir():
            native = pinned
        if not native.is_dir():
            raise ValueError("ORIGINAL_NATIVE_TRANSACTION_MISSING")
        dest = self.output / "native" / sid
        shutil.copytree(native, dest)
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
        manifest = store.recover(receipt["manifest_sha256"])
        raw = (dest / (manifest.acquisition.body_sha256 + ".raw")).read_bytes()
        self.raws[sid] = raw
        source_ref = SourceReference(
            document_id=sid,
            provider="sec_edgar",
            source_url=manifest.acquisition.endpoint,
        )
        self.sources[sid] = RegisteredNarrativeSource(
            store,
            manifest.content_identity,
            source_ref,
            blob_hash(raw),
            "US:META",
            "Meta Platforms, Inc.",
            "SEC_FILING",
            "HTML",
            period,
            None,
            None,
            "REAL_RETAINED_SOURCE",
        )
        return TemporalSource(
            source_id=sid,
            raw_sha256=blob_hash(raw),
            subject="US:META",
            scope_ids=("ASSET:US:META",),
            event_at=None,
            available_at=manifest.ingested_at,
            observed_at=manifest.acquisition.observed_at,
            ingested_at=manifest.ingested_at,
            origin="REAL_RETAINED_SOURCE",
        )

    def extract(self, sid: str) -> tuple[ObservedContent, ...]:
        """Reuse G109 parser for the declared current-period cells."""
        s = self.sources[sid]
        assert s.relevant_period is not None
        raw = self.raws[sid]
        text = (gzip.decompress(raw) if raw.startswith(b"\x1f\x8b") else raw).decode()
        result = []
        seen = set()
        for o in observations(raw, sid)["observations"]:
            period = o["period"]
            end = period.get("enddate", period.get("instant"))
            if end != s.relevant_period:
                continue
            key = digest((o["concept"], period, o["unit"], o["reported_value_usd"]))
            if key in seen:
                continue
            seen.add(key)
            pattern = (
                r'<ix:nonFraction\b[^>]*\bid="'
                + re.escape(o["native_element_id"])
                + r'"[^>]*>.*?</ix:nonFraction>'
            )
            match = re.search(pattern, text, re.S | re.I)
            if match is None:
                raise ValueError("MISSING_EXACT_NATIVE_ELEMENT")
            start = len(text[: match.start()].encode())
            endbyte = len(text[: match.end()].encode())
            self.locators[key] = (start, endbyte)
            result.append(
                ObservedContent(
                    subject="US:META",
                    concept=o["concept"],
                    period=json.dumps(period, sort_keys=True),
                    unit=o["unit"],
                    basis=period_basis(period),
                    value_literal=o["reported_value_usd"],
                    locator=sid + "#" + key,
                    quote=match.group(),
                    source_id=sid,
                    raw_sha256=s.raw_sha256,
                    event_at=None,
                    period_end=date.fromisoformat(s.relevant_period),
                )
            )
        return tuple(result)

    def service(self) -> MemoryService:
        """Reopen persisted original DuckDB/FAISS; index is explicitly nonsemantic."""
        for _, body in self.journal.entries("g100-write-intents"):
            self.vectors[json.loads(body)["summary_text"]] = [1.0, 0.0, 0.0]
        embedding = FakeEmbeddingService(
            self.vectors, model_name="g111-nonsemantic-local-index"
        )
        vector = FaissVectorRepository(
            self.output / "storage/faiss",
            embedder_model=embedding.model_name,
            embedding_dim=3,
        )
        return MemoryService(
            MemoryItemRepository(self.db), vector, embedding, clock=lambda: self.at
        )

    def admit(self, c: ObservedContent) -> str:
        """Write exact source attribution only through the existing G100 validator."""
        s = self.sources[c.source_id]
        start, end = self.locators[c.locator.split("#")[1]]
        resolver = NativeLocatorResolver(self.sources)
        p = NarrativeProposal(
            record_id=c.content_id,
            owner=self.access.owner,
            scope=self.scope,
            episode_id=self.ep.episode_id,
            research_state_id=self.ep.research_state_id,
            created_at=self.at,
            research_as_of=self.ep.research_as_of,
            subject=c.subject,
            statement=c.quote,
            source_ref=s.source_ref,
            evidence_locator=EvidenceLocator(
                kind="RAW_UTF8_BYTES", start=start, end=end, quote=c.quote
            ),
            source_sha256=c.raw_sha256,
            attribution=s.publisher,
            relevant_period=s.relevant_period,
            kind="DIRECT_SOURCE",
            retention_horizon="MEDIUM",
        )
        self.vectors[resolver.validate(p).model_dump_json()] = [1.0, 0.0, 0.0]
        service = self.service()
        r = admit_source_observation(
            service,
            p,
            resolver=resolver,
            access=self.access,
            journal=self.journal,
            episode=self.ep,
            enabled=True,
        )
        self.embedding_calls += len(service._embedder.calls)  # type: ignore[attr-defined]
        return r.result.memory_id

    def retrieve(self, label: str) -> Any:
        """Create a later Episode and an actual original G84 MemoryReadSet."""
        self.at = datetime.now(UTC)
        ep = episode(self.at, label, str(self.ep.asset_id))
        scope = Scope(
            scope_type=ResearchScopeType.RESEARCH_EPISODE,
            scope_id="EPISODE:" + ep.episode_id,
        )
        access = self.access.model_copy(update={"scopes": (self.scope, scope)})
        return retrieve_observations(
            self.service(),
            resolver=NativeLocatorResolver(self.sources),
            access=access,
            journal=self.journal,
            request=ResearchContextRequest(
                query_text="g111 retained context",
                as_of=self.at,
                market=Market.US,
                namespace_keys=[self.scope.scope_id],
                memory_levels=[MemoryLevel.L2],
                top_k_per_section=100,
            ),
            episode=ep,
            run_id=label,
            as_created=self.at,
            lane="ATTRIBUTED_SOURCES",
        )


def run(root: Path, output: Path) -> dict[str, Any]:
    """Execute real source cycles with socket egress explicitly denied."""
    output.mkdir(parents=True, exist_ok=False)
    m = ReplayMemory(root, output)
    q3 = m.source(
        "G105-GET-10",
        root / "artifacts/g108/sources/G105-GET-10/source-wrapper.json",
        "2026-09-30",
    )
    q2 = m.source(
        "G109-META-Q2", root / "artifacts/g109/G109-META-Q2.source.json", "2026-06-30"
    )
    cycles = []
    snapshots = []
    for index, source in enumerate((q3, q3, q2, q2)):
        before = m.retrieve("g111-before-" + str(index))
        before_rows = {
            stream: list(m.journal.entries(stream))
            for stream in (
                "g111-nodes",
                "g111-sources",
                "g111-source-contents",
                "g111-relations",
                "g111-invalidations",
            )
        }
        embeddings = m.embedding_calls
        cycle = run_temporal_cycle(
            m.journal,
            source,
            raw=m.raws[source.source_id],
            as_of=m.at,
            created_at=m.at,
            extract=lambda: m.extract(source.source_id),
            admit=m.admit,
            extractor_identity="g111-g109-eight-concepts-current-period-v1",
        )
        after = m.retrieve("g111-after-" + str(index))
        row = cycle.model_dump(mode="json")
        accepted = {ref.artifact_id for ref in after.read_set.memory_refs}
        context_nodes = [
            n.model_dump(mode="json")
            for n in eligible_nodes(m.journal, m.at)
            if n.memory_id in accepted
        ]
        selected = [
            n
            for n in context_nodes
            if n["memory_id"] in cycle.selected_memory_ids
            or ObservedContent.model_validate(n["content"]).content_id
            in cycle.selected_content_ids
        ]
        context = dict(
            source_readset=[d.source_readset for d in cycle.deltas],
            memory_readset=before.read_set.model_dump(mode="json"),
            post_write_memory_readset=after.read_set.model_dump(mode="json"),
            selected_content=selected,
            relations=[r.model_dump(mode="json") for r in cycle.relations],
            impact_plans=selective_impact(cycle),
            authority="DEVELOPMENT_SOURCE_ATTRIBUTION_ONLY",
            dispatched_roles=[],
            model_calls=0,
        )
        (output / f"cycle-{index}-selective-input.json").write_text(
            json.dumps(context, indent=2) + "\n"
        )
        row.update(
            selected_context_utf8_bytes=len(json.dumps(selected).encode()),
            full_context_utf8_bytes=len(json.dumps(context_nodes).encode()),
            memory_readset_before=before.read_set.model_dump(mode="json"),
            memory_readset_after=after.read_set.model_dump(mode="json"),
            embeddings_for_admission=m.embedding_calls - embeddings,
        )
        (output / f"cycle-{index}-memory-snapshot.json").write_text(
            json.dumps(
                dict(
                    before=before_rows,
                    after={
                        stream: list(m.journal.entries(stream))
                        for stream in before_rows
                    },
                    before_sha256=cycle.before_snapshot,
                    after_sha256=cycle.after_snapshot,
                ),
                indent=2,
            )
            + "\n"
        )
        cycles.append(row)
        snapshots.append(
            dict(
                cycle=index,
                before_ids=[r.artifact_id for r in before.read_set.memory_refs],
                after_ids=[r.artifact_id for r in after.read_set.memory_refs],
            )
        )
    assert (
        cycles[1]["duplicate_research_skipped"]
        and cycles[1]["embeddings_for_admission"] == 0
    )
    assert snapshots[0]["after_ids"] == snapshots[1]["after_ids"]
    assert any(d["kind"] == "HISTORICAL_BACKFILL" for d in cycles[2]["deltas"])
    for stream in (
        "g111-nodes",
        "g111-relations",
        "g111-sources",
        "g111-source-contents",
        "g111-cycles",
    ):
        (output / (stream + ".json")).write_text(
            json.dumps([json.loads(b) for _, b in m.journal.entries(stream)], indent=2)
            + "\n"
        )
    report = dict(
        status="PARTIAL",
        cycles=cycles,
        snapshots=snapshots,
        scientific_memory_writes=0,
        new_provider_calls=0,
        new_model_calls=0,
        actual_source_fetches_saved="UNKNOWN",
        actual_model_calls_saved="UNKNOWN",
        false_delta="UNKNOWN_OUTSIDE_CURATED_POPULATION",
        missed_delta="UNKNOWN",
        extraction_scope="Eight G109 concepts; consolidated current period only",
        avoided_extractor_calls=sum(c["duplicate_research_skipped"] for c in cycles),
        avoided_repeat_admissions=cycles[0]["admission_calls"]
        + cycles[2]["admission_calls"],
        production_admission=False,
        real_trading=False,
        embedding_origin="DECLARED_NONSEMANTIC_LOCAL_INDEX",
        next_research="EXACT_SOURCE_ATTRIBUTED_CONTEXT_NOT_LLM_RESEARCH",
    )
    (output / "replay.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    """Run an explicit offline experiment; never overwrite an earlier result."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    def denied(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("G111_NETWORK_FORBIDDEN")

    socket.socket.connect = denied  # type: ignore[method-assign]
    socket.create_connection = denied
    result = run(Path(__file__).resolve().parents[1], args.output)
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in ("cycles", "snapshots")}
        )
    )


if __name__ == "__main__":
    main()
