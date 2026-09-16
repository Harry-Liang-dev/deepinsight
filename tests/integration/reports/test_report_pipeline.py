"""Offline report pipeline integration with temporary DuckDB and FAISS."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.memory import MemoryService
from src.models.enums import MemoryLevel, TaskStatus
from src.orchestration import ResearchReportPipeline
from src.reports import ReportAssembler
from src.repositories import (
    DuckDBDatabase,
    FaissVectorRepository,
    MemoryItemRepository,
    ReportRepository,
)
from src.schemas.sector_research import SectorClaimCategory
from src.services import FakeEmbeddingService
from tests.fixtures.report_data import NOW, make_report_input
from tests.unit.services.test_sector_context import _aapl_bundle

pytestmark = pytest.mark.integration


def test_pipeline_persists_report_and_attributable_l3_memory(
    tmp_path: Path,
) -> None:
    """A report should close the local DuckDB and FAISS-backed Memory loop."""

    database = DuckDBDatabase(tmp_path / "report-pipeline.duckdb")
    database.bootstrap()
    payload = make_report_input()
    assembler = ReportAssembler()
    running = assembler.assemble(payload)
    memory_request = assembler.to_memory_request(running)
    embedder = FakeEmbeddingService({memory_request.summary_text: [1.0, 0.0, 0.0]})
    vectors = FaissVectorRepository(
        tmp_path / "faiss",
        embedder_model=embedder.model_name,
        embedding_dim=embedder.dimension,
    )
    memories = MemoryItemRepository(database)
    memory_service = MemoryService(
        memories,
        vectors,
        embedder,
        clock=lambda: NOW,
        memory_id_factory=lambda: "memory-report-1",
    )
    reports = ReportRepository(database)
    pipeline = ResearchReportPipeline(assembler, reports, memory_service)

    completed = pipeline.execute(payload)

    stored_report = reports.get(payload.report_id)
    assert stored_report is not None
    assert stored_report.status is TaskStatus.COMPLETED
    assert stored_report.report_markdown == completed.report_markdown
    stored_memories = memories.list_namespace("memory_L3_v1")
    assert len(stored_memories) == 1
    assert stored_memories[0].memory_level is MemoryLevel.L3
    assert stored_memories[0].namespace_key == "REPORT:report-1"
    assert stored_memories[0].source_ref == completed.source_trace[0]
    assert vectors.count("memory_L3_v1") == 1


def test_report_surfaces_accepted_industry_chain_context() -> None:
    """The human report should render, not merely carry, accepted Chain context."""

    sector_context = _aapl_bundle()
    chain_claim = sector_context.accepted_claims[0].model_copy(
        update={
            "category": SectorClaimCategory.INDUSTRY_CHAINS,
            "claim_text": "The asset is a core member of the active Chain.",
        }
    )
    sector_context = sector_context.model_copy(
        update={"accepted_claims": (chain_claim, *sector_context.accepted_claims[1:])}
    )
    payload = make_report_input().model_copy(update={"sector_context": sector_context})

    report = ReportAssembler().assemble(payload)

    chain_id = sector_context.active_chain_ids[0]
    assert chain_id in report.report_markdown
    assert "Industry Chain context" in report.report_markdown
    chain_claim_ids = {
        claim.claim_id
        for claim in sector_context.accepted_claims
        if claim.category.value == "industry_chains"
    }
    executive = report.report_json["executive_view"]
    assert isinstance(executive, dict)
    facts = executive["facts"]
    assert isinstance(facts, list)
    assert any(
        isinstance(item, dict) and item.get("claim_id") in chain_claim_ids
        for item in facts
    )


def test_existing_report_sector_projection_is_idempotent() -> None:
    """Resume-time deterministic surfacing must not duplicate Chain Claims."""

    assembler = ReportAssembler()
    report = assembler.assemble(make_report_input())
    sector_context = _aapl_bundle()
    chain_claim = sector_context.accepted_claims[0].model_copy(
        update={
            "category": SectorClaimCategory.INDUSTRY_CHAINS,
            "claim_text": "The asset is a core member of the active Chain.",
        }
    )
    sector_context = sector_context.model_copy(
        update={"accepted_claims": (chain_claim, *sector_context.accepted_claims[1:])}
    )

    once = assembler.surface_sector_context(report, sector_context)
    twice = assembler.surface_sector_context(once, sector_context)

    assert twice.report_markdown == once.report_markdown
    assert twice.source_trace == once.source_trace
