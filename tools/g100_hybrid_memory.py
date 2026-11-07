"""Offline G100 source-observation composition; no model or provider requests."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from src.memory.contracts import ResearchContextRequest
from src.memory.controlled import admit_source_assertion
from src.memory.hybrid import (
    consume_observation,
    retrieve_observations,
)
from src.memory.hybrid_contracts import EvidenceLocator, NarrativeProposal
from src.memory.hybrid_sources import NativeLocatorResolver, RegisteredNarrativeSource
from src.memory.service import MemoryService
from src.memory.vnext import MemoryAccessContext
from src.memory.vnext_contracts import Scope
from src.models.enums import AgentName, Market, MemoryLevel, ResearchScopeType
from src.repositories import DuckDBDatabase, FaissVectorRepository, MemoryItemRepository
from src.repositories.memory_journal import MemoryJournalRepository
from src.schemas.common import SourceReference
from src.schemas.research_episode import ResearchEpisode, ResearchEpisodeBuildInput
from src.schemas.research_state import ResearchStateBuildInput
from src.services.embedding import FakeEmbeddingService
from src.services.native_preservation import NativePreserver, blob_hash
from src.services.research_episode import ResearchEpisodeBuilder
from src.services.research_state import ResearchStateBuilder
from src.services.research_vnext.g97_sources import AVGOSources, read


def retained_sources(sources: AVGOSources) -> dict[str, RegisteredNarrativeSource]:
    """Project only the checked existing G96 registry into locator adapters."""
    result = {}
    for key, source in sources.sources.items():
        receipt = read(sources.root / source["path"])["receipt"]
        generation = Path(source["path"]).parts[1]
        family = "corporate-requests" if generation == "g96" else "sec-requests"
        directory = (
            sources.root
            / "artifacts"
            / generation
            / family
            / f"{receipt['request']['attempt']:02}-native"
        )
        session = read(directory / "session.json")
        store = NativePreserver(
            directory,
            provider=session["provider"],
            owner=session["owner"],
            run_id=session["run_id"],
            retention_authority=session["retention_authority"],
            allowed_endpoints=tuple(session["endpoints"]),
            normalization_version=session["normalization_version"],
        )
        chunk = next(
            c
            for fid, c in sources.fact_chunks.items()
            if sources.facts[fid]["source_id"] == key
        )
        ref = SourceReference(
            document_id=chunk.document_id,
            provider=chunk.source_identity.provider,
            source_url=source["url"],
        )
        result[key] = RegisteredNarrativeSource(
            store=store,
            manifest_identity=receipt["manifest_sha256"],
            source_ref=ref,
            raw_sha256=source["raw_sha256"],
            subject="US:AVGO",
            publisher=(
                "Blackstone: joint official release" if key == "B" else "Broadcom"
            ),
            source_type="OFFICIAL_RELEASE" if key == "B" else "SEC_FILING",
            format="HTML",
            relevant_period=source.get("report_date"),
            published_at=chunk.temporal_provenance.available_at,
            publication_literal=source["publication_date"],
            origin="REAL_RETAINED_SOURCE",
        )
    return result


def episode(
    sources: AVGOSources, at: datetime, identity: str, created: datetime | None = None
) -> ResearchEpisode:
    """Build an empty development State/Episode without accepted Agent claims."""
    state = ResearchStateBuilder().build(
        ResearchStateBuildInput(
            research_data_bundle=sources.bundle(at),
            accepted_claims=(),
            source_run_id=identity,
        )
    )
    return ResearchEpisodeBuilder().build(
        ResearchEpisodeBuildInput(
            research_state=state,
            agent_traces=(),
            created_at=created or at,
            missing_metadata=("SOURCE_OBSERVATION_ONLY_NO_AGENT_EXECUTION",),
        )
    )


class OfflineSession:
    """Original DuckDB/FAISS MemoryService with declared nonsemantic test indexing."""

    def __init__(self, path: Path, sources: AVGOSources, at: datetime) -> None:
        self.path, self.sources, self.at = path, sources, at
        self.registry = retained_sources(sources)
        self.resolver = NativeLocatorResolver(
            {s.source_ref.document_id or "": s for s in self.registry.values()}
        )
        self.first = episode(sources, at, "g100-source-observation")
        self.scope = Scope(
            scope_type=ResearchScopeType.RESEARCH_EPISODE,
            scope_id="EPISODE:" + self.first.episode_id,
        )
        self.access = MemoryAccessContext(
            owner="news_event_analyst",
            role=AgentName.NEWS_EVENT_ANALYST,
            scopes=(self.scope,),
            enabled=True,
        )
        self.proposals: list[NarrativeProposal] = []
        self.open()

    def proposal(self, fid: str, **updates: Any) -> NarrativeProposal:
        """Retain exact immutable quote, Unicode coordinates and source identity."""
        fact = self.sources.facts[fid]
        source = self.registry[fact["source_id"]]
        start, end = fact["text_span"]
        # Existing fact spans can contain outer whitespace; narrow without inventing.
        text = self.sources.texts[fact["source_id"]]
        quote = fact["quote"]
        positions = [i for i in range(start, end) if text.startswith(quote, i)]
        if len(positions) != 1:
            raise ValueError("G100_AMBIGUOUS_ORIGINAL_FACT_SPAN")
        start = positions[0]
        end = start + len(quote)
        p = NarrativeProposal(
            record_id=fid,
            owner=self.access.owner,
            scope=self.scope,
            episode_id=self.first.episode_id,
            research_state_id=self.first.research_state_id,
            created_at=self.at,
            research_as_of=self.at,
            subject="US:AVGO",
            statement=quote,
            source_ref=source.source_ref,
            evidence_locator=EvidenceLocator(
                kind="NORMALIZED_UNICODE",
                start=start,
                end=end,
                normalization_sha256=blob_hash(text.encode()),
                quote=quote,
            ),
            source_sha256=source.raw_sha256,
            attribution=source.publisher,
            relevant_period=source.relevant_period,
            kind="DIRECT_SOURCE",
            retention_horizon="MEDIUM",
        )
        return NarrativeProposal.model_validate({**p.model_dump(), **updates})

    def open(self) -> None:
        """Recreate all storage/service instances from persisted files."""
        self.db = DuckDBDatabase(self.path / "memory.duckdb")
        self.db.bootstrap()
        self.journal = MemoryJournalRepository(self.db)
        self.journal.bootstrap()
        vectors = {"g100 observations": [1.0, 0.0, 0.0]}
        for p in self.proposals:
            vectors[self.resolver.validate(p).model_dump_json()] = [1.0, 0.0, 0.0]
        for _, body in self.journal.entries("g100-write-intents"):
            vectors[json.loads(body)["summary_text"]] = [1.0, 0.0, 0.0]
        embedding = FakeEmbeddingService(
            vectors, model_name="g100-engineering-nonsemantic-local-index"
        )
        self.vector = FaissVectorRepository(
            self.path / "faiss",
            embedder_model=embedding.model_name,
            embedding_dim=embedding.dimension,
        )
        self.service = MemoryService(
            MemoryItemRepository(self.db), self.vector, embedding, clock=lambda: self.at
        )

    def admit(self, p: NarrativeProposal) -> Any:
        """Use the versioned controlled adapter, never direct DB writes."""
        self.proposals.append(p)
        self.open()
        return admit_source_assertion(
            self.service,
            p,
            resolver=self.resolver,
            access=self.access,
            journal=self.journal,
            episode=self.first,
            enabled=True,
        )

    def retrieve(
        self,
        lane: Literal["ATTRIBUTED_SOURCES", "ISOLATED_LEADS"] = "ATTRIBUTED_SOURCES",
        cutoff: datetime | None = None,
    ) -> Any:
        """Build a fresh Episode and actual G84 read set for retained observations."""
        self.next = episode(
            self.sources, cutoff or self.at, "g100-cross-episode", created=self.at
        )
        receiving = Scope(
            scope_type=ResearchScopeType.RESEARCH_EPISODE,
            scope_id="EPISODE:" + self.next.episode_id,
        )
        self.access = self.access.model_copy(
            update={"scopes": tuple(dict.fromkeys((*self.access.scopes, receiving)))}
        )
        return retrieve_observations(
            self.service,
            resolver=self.resolver,
            access=self.access,
            journal=self.journal,
            request=ResearchContextRequest(
                query_text="g100 observations",
                as_of=cutoff or self.at,
                market=Market.US,
                namespace_keys=[self.scope.scope_id],
                memory_levels=[MemoryLevel.L2, MemoryLevel.L3],
                top_k_per_section=20,
            ),
            episode=self.next,
            run_id="ENGINEERING_FIXTURE:consumer:" + lane,
            as_created=self.at,
            lane=lane,
        )


def run(root: Path, output: Path) -> dict[str, Any]:
    """Execute real retained sources plus explicitly synthetic citation consumption."""
    output.mkdir(parents=True, exist_ok=False)
    at = datetime.now(UTC)
    sources = AVGOSources(root, at)
    s = OfflineSession(output / "storage", sources, at)
    proposals = [s.proposal(fid) for fid in ("A02", "A03", "A07", "B10", "C05", "D03")]
    proposals += [
        s.proposal(
            "A02",
            record_id="pending-paraphrase",
            kind="PARAPHRASE",
            statement="The issuer describes residual value support to an SPV.",
        ),
        s.proposal(
            "C05",
            record_id="unverified-merge",
            kind="RESEARCH_HYPOTHESIS",
            statement=(
                "Hypothesis requiring legal evidence: the disclosed 29B "
                "and 43B arrangements might overlap."
            ),
        ),
    ]
    receipts = [s.admit(p) for p in proposals]
    assert s.admit(proposals[0]) == receipts[0]
    del s.service, s.vector, s.journal, s.db
    s.at = datetime.now(UTC)
    s.open()
    delivered = s.retrieve()
    leads = s.retrieve("ISOLATED_LEADS")
    r = delivered.supplied_records[0]
    mid = r.result.memory_id
    # This is a declared synthetic citation, NOT a new Agent/LLM response.
    model_text = (
        r.record.publisher
        + " stated: "
        + r.record.proposal.statement
        + " [memory:"
        + mid
        + "]"
    )
    consumed = consume_observation(
        delivered,
        memory_id=mid,
        model_text=model_text,
        use="ATTRIBUTED_SOURCE",
        access=s.access,
        journal=s.journal,
        at=s.at,
        resolver=s.resolver,
    )
    assert consumed["validly_consumed"] and not consumed["world_fact_authority"]
    receipt = {
        "origin": "REAL_RETAINED_SOURCE_WITH_SYNTHETIC_ENGINEERING_CONSUMER",
        "original_source_verification": sources.verification,
        "source_count": len(s.registry),
        "source_assertions_admitted": sum(
            r.source_assertion_admitted for r in receipts
        ),
        "pending_leads": len(leads.supplied_records),
        "persisted_records": len(receipts),
        "durable_reopen": True,
        "first_episode": s.first.model_dump(mode="json"),
        "next_episode": s.next.model_dump(mode="json"),
        "admissions": [r.model_dump(mode="json") for r in receipts],
        "attributed_delivery": delivered.model_dump(mode="json"),
        "lead_delivery": leads.model_dump(mode="json"),
        "synthetic_consumption": consumed,
        "scientific_memory_admitted": False,
        "research_result_accepted": False,
        "new_provider_calls": 0,
        "new_model_calls": 0,
        "false_fact_promotions": 0,
    }
    (output / "receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    )
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(Path.cwd(), args.output)
    print(
        json.dumps(
            {k: v for k, v in result.items() if isinstance(v, (str, int, bool))},
            indent=2,
        )
    )
