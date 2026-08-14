"""Strict loading and materialization for fixed live Agent snapshots."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from src.models.enums import MemoryLevel, ReportMarketScope
from src.schemas.agents import AgentContext
from src.schemas.common import SourceReference
from src.schemas.documents import RetrievedDocument
from src.schemas.live_benchmark import (
    LiveBenchmarkSnapshot,
    LiveSnapshotSource,
    MaterializedLiveScenario,
)
from src.schemas.memory import MemorySearchResult


class LiveSnapshotError(RuntimeError):
    """Raised before inference when a fixed snapshot is invalid or changed."""


@dataclass(frozen=True, slots=True)
class LoadedLiveSnapshot:
    """Validated snapshot paired with its verified content digest."""

    snapshot: LiveBenchmarkSnapshot
    sha256: str


class LiveSnapshotLoader:
    """Load one exact YAML snapshot and verify its detached SHA-256."""

    def __init__(self, snapshot_path: Path, checksum_path: Path) -> None:
        """Bind explicit snapshot and checksum paths."""

        self._snapshot_path = snapshot_path
        self._checksum_path = checksum_path

    def load(self) -> LoadedLiveSnapshot:
        """Return a validated snapshot only when its bytes match the checksum."""

        try:
            payload = self._snapshot_path.read_bytes()
            expected = self._checksum_path.read_text(encoding="ascii").strip()
            actual = hashlib.sha256(payload).hexdigest()
            if expected != actual:
                raise LiveSnapshotError("live Benchmark snapshot checksum mismatch")
            raw = yaml.safe_load(payload)
            snapshot = LiveBenchmarkSnapshot.model_validate(raw)
        except LiveSnapshotError:
            raise
        except (OSError, UnicodeError, yaml.YAMLError, ValidationError) as exc:
            raise LiveSnapshotError("live Benchmark snapshot is unavailable") from exc
        return LoadedLiveSnapshot(snapshot=snapshot, sha256=actual)


def materialize_scenarios(
    loaded: LoadedLiveSnapshot,
) -> list[MaterializedLiveScenario]:
    """Build fixed Agent contexts without any Provider or network access."""

    snapshot = loaded.snapshot
    sources = {item.evidence_id: item for item in snapshot.sources}
    memories = {item.memory_id: item for item in snapshot.memories}
    materialized: list[MaterializedLiveScenario] = []
    for scenario in sorted(snapshot.scenarios, key=lambda item: item.case_id):
        selected = {key: sources[key] for key in scenario.source_ids}
        context = AgentContext(
            report_date=scenario.report_date,
            market_scope=ReportMarketScope.US,
            asset_id=scenario.asset_id,
            structured_features=scenario.structured_features,
            retrieved_documents=[_document(source) for source in selected.values()],
            retrieved_memories=[
                MemorySearchResult(
                    memory_id=item.memory_id,
                    memory_level=MemoryLevel(item.memory_level),
                    namespace_key=item.namespace_key,
                    summary_text=item.summary_text,
                    score=item.score,
                    effective_ts=item.effective_ts,
                    asset_id=scenario.asset_id,
                    memory_type=item.memory_type,
                    importance_score=item.importance_score,
                    source_ref_json=_source_ref(sources[item.source_evidence_id]),
                    created_by="live_agent_benchmark_snapshot",
                )
                for memory_id in scenario.memory_ids
                for item in [memories[memory_id]]
            ],
        )
        materialized.append(
            MaterializedLiveScenario(
                case_id=scenario.case_id,
                scenario=scenario.scenario,
                context=context,
                evidence_by_id=selected,
                known_missing_data=scenario.known_missing_data,
            )
        )
    return materialized


def _document(source: LiveSnapshotSource) -> RetrievedDocument:
    return RetrievedDocument(
        document_id=source.document_id,
        chunk_id=source.chunk_id,
        title=source.title,
        chunk_text=source.text,
    )


def _source_ref(source: LiveSnapshotSource) -> SourceReference:
    return SourceReference(
        document_id=source.document_id,
        excerpt_ref=source.chunk_id,
        provider=source.provider,
        source_url=source.source_locator,
    )
