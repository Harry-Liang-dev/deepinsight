"""HTTP contract tests for the Phase One FastAPI application."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import cast

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api import create_app
from src.api.dependencies import get_report_task_service
from src.api.schemas import MemorySnapshotResponse
from src.api.services import (
    ApiServices,
    InProcessReportTaskService,
)
from src.core.settings import AppEnvironment, AppSettings
from src.models.enums import MemoryLevel, TaskStatus
from src.models.types import JsonObject
from src.reports import ReportAssembler
from src.schemas import (
    GenerateReportRequest,
    MemorySearchRequest,
    MemorySearchResponse,
    MemorySearchResult,
    MemoryWriteRequest,
    MemoryWriteResult,
    ResearchReport,
    SourceReference,
    TaskStatusResponse,
)
from tests.fixtures.report_data import make_report_input

NOW = datetime(2026, 7, 31, 9, 30, tzinfo=UTC)


class FixedReportGenerator:
    """Return one deterministic completed report."""

    def __init__(self, report: ResearchReport) -> None:
        self.report = report
        self.requests: list[GenerateReportRequest] = []

    def generate(self, request: GenerateReportRequest) -> ResearchReport:
        self.requests.append(request)
        return self.report


class DictReportQuery:
    """Read reports from an instance-local mapping."""

    def __init__(self, reports: list[ResearchReport]) -> None:
        self._reports = {report.report_id: report for report in reports}

    def get(self, report_id: str) -> ResearchReport | None:
        return self._reports.get(report_id)


class FakeMemoryService:
    """Return deterministic Memory results while capturing requests."""

    def __init__(self) -> None:
        self.writes: list[MemoryWriteRequest] = []
        self.searches: list[MemorySearchRequest] = []

    def write(self, request: MemoryWriteRequest) -> MemoryWriteResult:
        self.writes.append(request)
        return MemoryWriteResult(
            memory_id="memory-1",
            faiss_namespace="memory_L1_v1",
            faiss_vector_id=7,
        )

    def search(self, request: MemorySearchRequest) -> MemorySearchResponse:
        self.searches.append(request)
        return MemorySearchResponse(
            results=[
                MemorySearchResult(
                    memory_id="memory-1",
                    memory_level=MemoryLevel.L1,
                    namespace_key="US",
                    summary_text="Observed policy remained restrictive.",
                    score=0.9,
                    effective_ts=NOW,
                    memory_type="macro",
                    importance_score=0.8,
                    source_ref_json=SourceReference(document_id="doc-1"),
                    created_by="test",
                )
            ]
        )


class FixedSnapshotQuery:
    """Return a snapshot only for the deterministic test date."""

    def get(self, snapshot_date: date) -> MemorySnapshotResponse | None:
        if snapshot_date != date(2026, 7, 31):
            return None
        return MemorySnapshotResponse(
            snapshot_date=snapshot_date,
            duckdb_artifact="platform.duckdb",
            faiss_artifacts=["memory_L1_v1.index"],
        )


class MissingReportQuery:
    """Return no reports."""

    def get(self, report_id: str) -> None:
        del report_id
        return None


def _completed_report() -> ResearchReport:
    return ReportAssembler().assemble(
        make_report_input(),
        status=TaskStatus.COMPLETED,
    )


def _services() -> tuple[ApiServices, FixedReportGenerator, FakeMemoryService]:
    report = _completed_report()
    generator = FixedReportGenerator(report)
    memory = FakeMemoryService()
    services = ApiServices(
        report_tasks=InProcessReportTaskService(
            generator,
            job_id_factory=lambda: "job-report-1",
        ),
        reports=DictReportQuery([report]),
        memory=memory,
        snapshots=FixedSnapshotQuery(),
    )
    return services, generator, memory


def _application(services: ApiServices | None = None) -> FastAPI:
    settings = AppSettings(env=AppEnvironment.TEST)
    return create_app(settings=settings, services=services)


def _generate_payload() -> JsonObject:
    return cast(
        JsonObject,
        make_report_input().request.model_dump(mode="json"),
    )


def _memory_write_payload() -> JsonObject:
    return {
        "memory_level": "L1",
        "namespace_key": "US",
        "effective_ts": NOW.isoformat(),
        "summary_text": "Observed policy remained restrictive.",
        "memory_type": "macro",
        "importance_score": 0.8,
        "source_ref_json": {"document_id": "doc-1"},
        "created_by": "test",
    }


async def test_health_check_exposes_safe_environment() -> None:
    """Health route returns liveness without secret configuration."""

    transport = ASGITransport(app=_application())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "deepinsight-api",
        "environment": "test",
    }


async def test_report_task_lifecycle_and_report_retrieval() -> None:
    """A submitted task completes through the injected generator."""

    services, generator, _ = _services()
    transport = ASGITransport(app=_application(services))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            "/v1/reports/generate",
            json=_generate_payload(),
        )
        task = await client.get("/v1/reports/jobs/job-report-1")
        report = await client.get("/v1/reports/report-1")

    assert submitted.status_code == 202
    assert submitted.json()["status"] == "queued"
    assert task.status_code == 200
    assert task.json()["status"] == "completed"
    assert task.json()["report_id"] == "report-1"
    assert report.status_code == 200
    assert report.json()["report_id"] == "report-1"
    assert len(generator.requests) == 1


async def test_validation_and_not_found_errors_use_one_contract() -> None:
    """Validation and missing resources share the standard error envelope."""

    services, _, _ = _services()
    transport = ASGITransport(app=_application(services))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        invalid = await client.post("/v1/reports/generate", json={})
        missing_job = await client.get("/v1/reports/jobs/missing")
        missing_report = await client.get("/v1/reports/missing")
        missing_snapshot = await client.get("/v1/memory/snapshot/2026-07-30")

    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"
    assert missing_job.json()["error"]["code"] == "job_not_found"
    assert missing_report.json()["error"]["code"] == "report_not_found"
    assert missing_snapshot.json()["error"]["code"] == "snapshot_not_found"


async def test_memory_and_snapshot_routes_delegate_to_services() -> None:
    """Memory HTTP handlers perform validation and delegate operations."""

    services, _, memory = _services()
    search_payload: JsonObject = {
        "memory_levels": ["L1"],
        "namespace_keys": ["US"],
        "query_text": "policy",
        "top_k": 3,
    }
    transport = ASGITransport(app=_application(services))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        written = await client.post(
            "/v1/memory/write",
            json=_memory_write_payload(),
        )
        searched = await client.post("/v1/memory/search", json=search_payload)
        snapshot = await client.get("/v1/memory/snapshot/2026-07-31")

    assert written.status_code == 201
    assert written.json()["memory_id"] == "memory-1"
    assert searched.status_code == 200
    assert searched.json()["results"][0]["memory_id"] == "memory-1"
    assert snapshot.status_code == 200
    assert snapshot.json()["duckdb_artifact"] == "platform.duckdb"
    assert len(memory.writes) == 1
    assert len(memory.searches) == 1


async def test_default_unconfigured_service_fails_safely() -> None:
    """A directly startable app never silently invokes missing infrastructure."""

    transport = ASGITransport(app=_application())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/memory/write",
            json=_memory_write_payload(),
        )

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "service_unavailable",
        "message": "Memory service is not configured.",
        "retryable": True,
        "details": None,
    }


async def test_unconfigured_report_generator_records_failed_task() -> None:
    """Background generation failures remain safely queryable."""

    application = _application()
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            "/v1/reports/generate",
            json=_generate_payload(),
        )
        task = await client.get(f"/v1/reports/jobs/{submitted.json()['job_id']}")

    assert submitted.status_code == 202
    assert task.json()["status"] == "failed"
    assert task.json()["error"]["code"] == "service_unavailable"


async def test_fastapi_dependency_override_replaces_task_service() -> None:
    """Tests can replace a single dependency without rebuilding route code."""

    status_response = TaskStatusResponse(
        job_id="job-overridden",
        status=TaskStatus.QUEUED,
    )

    class OverrideTaskService:
        def submit(self, request: GenerateReportRequest) -> TaskStatusResponse:
            del request
            return status_response

        def run(self, job_id: str, request: GenerateReportRequest) -> None:
            del job_id, request

        def get_status(self, job_id: str) -> TaskStatusResponse | None:
            del job_id
            return status_response

    override_service = OverrideTaskService()

    async def override_task_service() -> OverrideTaskService:
        return override_service

    application = create_app(settings=AppSettings(env=AppEnvironment.TEST))
    application.dependency_overrides[get_report_task_service] = override_task_service
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/reports/generate",
            json=_generate_payload(),
        )

    assert response.status_code == 202
    assert response.json()["job_id"] == "job-overridden"


async def test_phase_two_routes_are_explicitly_not_implemented() -> None:
    """Reserved Phase Two routes consistently return HTTP 501."""

    paths = (
        "/v1/phase2/factors/mine",
        "/v1/phase2/router/select",
        "/v1/phase2/training/run",
        "/v1/phase2/backtest/run",
        "/v1/phase2/execution/paper",
        "/v1/phase2/execution/live",
    )
    transport = ASGITransport(app=_application())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        responses = [await client.post(path) for path in paths]

    assert all(response.status_code == 501 for response in responses)
    assert all(
        response.json()["error"]["code"] == "phase_two_not_implemented"
        for response in responses
    )
