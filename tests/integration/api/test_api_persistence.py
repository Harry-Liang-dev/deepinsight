"""API integration with temporary DuckDB and FAISS persistence."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api import create_app
from src.api.schemas import MemorySnapshotResponse
from src.api.services import (
    ApiServices,
    InProcessReportTaskService,
)
from src.core.settings import AppEnvironment, AppSettings
from src.memory import MemoryService
from src.models.enums import TaskStatus
from src.models.types import JsonObject
from src.reports import ReportAssembler
from src.repositories import (
    DuckDBDatabase,
    FaissVectorRepository,
    MemoryItemRepository,
    ReportRepository,
)
from src.schemas import GenerateReportRequest, ResearchReport
from src.services import FakeEmbeddingService
from tests.fixtures.report_data import make_report_input

pytestmark = pytest.mark.integration

NOW = datetime(2026, 7, 31, 9, 30, tzinfo=UTC)
SUMMARY = "Observed policy remained restrictive."
QUERY = "policy outlook"


class PersistingReportGenerator:
    """Persist a deterministic report through the real Repository."""

    def __init__(
        self,
        repository: ReportRepository,
        report: ResearchReport,
    ) -> None:
        self._repository = repository
        self._report = report

    def generate(self, request: GenerateReportRequest) -> ResearchReport:
        if request != make_report_input().request:
            raise ValueError("unexpected integration-test request")
        self._repository.save(self._report)
        return self._report


class NoSnapshots:
    """Keep filesystem snapshot creation outside the API integration test."""

    def get(self, snapshot_date: date) -> MemorySnapshotResponse | None:
        del snapshot_date
        return None


def _application(tmp_path: Path) -> FastAPI:
    database = DuckDBDatabase(tmp_path / "api.duckdb")
    database.bootstrap()

    report_repository = ReportRepository(database)
    report = ReportAssembler().assemble(
        make_report_input(),
        status=TaskStatus.COMPLETED,
    )
    generator = PersistingReportGenerator(report_repository, report)

    embedder = FakeEmbeddingService(
        {
            SUMMARY: [1.0, 0.0, 0.0],
            QUERY: [1.0, 0.0, 0.0],
        }
    )
    vectors = FaissVectorRepository(
        tmp_path / "faiss",
        embedder_model=embedder.model_name,
        embedding_dim=embedder.dimension,
    )
    memory = MemoryService(
        MemoryItemRepository(database),
        vectors,
        embedder,
        clock=lambda: NOW,
        memory_id_factory=lambda: "memory-api-1",
    )
    services = ApiServices(
        report_tasks=InProcessReportTaskService(
            generator,
            job_id_factory=lambda: "job-api-1",
        ),
        reports=report_repository,
        memory=memory,
        snapshots=NoSnapshots(),
    )
    return create_app(
        settings=AppSettings(env=AppEnvironment.TEST),
        services=services,
    )


async def test_report_and_memory_round_trip_through_http(
    tmp_path: Path,
) -> None:
    """HTTP requests round-trip through temporary real persistence."""

    application = _application(tmp_path)
    transport = ASGITransport(app=application)
    report_payload = cast(
        JsonObject,
        make_report_input().request.model_dump(mode="json"),
    )
    memory_payload: JsonObject = {
        "memory_level": "L1",
        "namespace_key": "US",
        "effective_ts": NOW.isoformat(),
        "summary_text": SUMMARY,
        "memory_type": "macro",
        "importance_score": 0.8,
        "source_ref_json": {"document_id": "doc-api-1"},
        "created_by": "integration-test",
    }
    search_payload: JsonObject = {
        "memory_levels": ["L1"],
        "namespace_keys": ["US"],
        "query_text": QUERY,
        "top_k": 1,
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            "/v1/reports/generate",
            json=report_payload,
        )
        task = await client.get("/v1/reports/jobs/job-api-1")
        report = await client.get("/v1/reports/report-1")
        written = await client.post("/v1/memory/write", json=memory_payload)
        searched = await client.post("/v1/memory/search", json=search_payload)
        empty_search = await client.post(
            "/v1/memory/search",
            json={**search_payload, "namespace_keys": ["GLOBAL"]},
        )

    assert submitted.status_code == 202
    assert task.json()["status"] == "completed"
    assert report.status_code == 200
    assert report.json()["report_id"] == "report-1"
    assert written.status_code == 201
    assert written.json()["memory_id"] == "memory-api-1"
    assert searched.status_code == 200
    assert searched.json()["results"][0]["memory_id"] == "memory-api-1"
    assert empty_search.json()["results"] == []
    assert (tmp_path / "api.duckdb").is_file()
    assert any((tmp_path / "faiss").iterdir())
