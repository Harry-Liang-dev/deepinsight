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
from src.services import FakeEmbeddingService
from tests.fixtures.report_data import NOW, make_report_input

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
