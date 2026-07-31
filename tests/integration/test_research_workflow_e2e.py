"""Deterministic request-to-report integration through the public API."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.offline import (
    OFFLINE_ASSET_ID,
    OFFLINE_EMBEDDING_DIMENSION,
    OFFLINE_EMBEDDING_MODEL,
    create_offline_application,
    offline_report_request,
)
from src.models.enums import MemoryLevel, TaskStatus
from src.reports import STANDARD_SECTION_NAMES
from src.repositories import (
    DuckDBDatabase,
    FaissVectorRepository,
    InstrumentRepository,
    MarketDataRepository,
    MemoryItemRepository,
    ReportRepository,
)
from src.services import LLMTimeoutError

pytestmark = pytest.mark.integration


async def test_offline_api_runs_the_complete_research_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Fixed data and fake LLMs should produce one durable cited report."""

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    application = create_offline_application(tmp_path)
    transport = ASGITransport(app=application)
    payload = offline_report_request().model_dump(mode="json")

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        submitted = await client.post("/v1/reports/generate", json=payload)
        job_id = submitted.json()["job_id"]
        task = await client.get(f"/v1/reports/jobs/{job_id}")
        report_id = task.json()["report_id"]
        response = await client.get(f"/v1/reports/{report_id}")

    assert submitted.status_code == 202
    assert submitted.json()["status"] == TaskStatus.QUEUED.value
    assert task.status_code == 200
    assert task.json()["status"] == TaskStatus.COMPLETED.value
    assert response.status_code == 200

    report_json = response.json()
    assert report_json["report_id"] == "rep_demo_1"
    assert report_json["status"] == TaskStatus.COMPLETED.value
    assert [section["section_name"] for section in report_json["sections"]] == list(
        STANDARD_SECTION_NAMES
    )
    assert report_json["source_trace"]
    assert all(
        section["citations"] or "Uncertainties" in section["section_markdown"]
        for section in report_json["sections"]
    )
    assert "research analysis only" in report_json["final_recommendation"]

    database_path = tmp_path / "duckdb" / "platform.duckdb"
    restarted_database = DuckDBDatabase(database_path)
    stored_report = ReportRepository(restarted_database).get("rep_demo_1")
    assert stored_report is not None
    assert stored_report.status is TaskStatus.COMPLETED
    assert len(stored_report.sections) == len(STANDARD_SECTION_NAMES)

    instrument = InstrumentRepository(restarted_database).get(OFFLINE_ASSET_ID)
    bar = MarketDataRepository(restarted_database).get_eod_bar(
        OFFLINE_ASSET_ID,
        offline_report_request().report_date,
    )
    assert instrument is not None
    assert instrument.source_primary == "fake"
    assert bar is not None
    assert bar.close == 210.5

    l3_records = MemoryItemRepository(restarted_database).list_namespace("memory_L3_v1")
    assert len(l3_records) == 1
    assert l3_records[0].memory_level is MemoryLevel.L3
    assert l3_records[0].source_ref is not None

    restarted_vectors = FaissVectorRepository(
        tmp_path / "faiss",
        embedder_model=OFFLINE_EMBEDDING_MODEL,
        embedding_dim=OFFLINE_EMBEDDING_DIMENSION,
    )
    assert restarted_vectors.count("docs_v1") == 1
    assert restarted_vectors.count("memory_L1_v1") == 1
    assert restarted_vectors.count("memory_L3_v1") == 1

    with restarted_database.connection() as connection:
        counts = connection.execute("""
            SELECT
                (SELECT count(*) FROM ingestion_jobs),
                (SELECT count(*) FROM text_documents),
                (SELECT count(*) FROM agent_runs),
                (SELECT count(*) FROM report_sections),
                (SELECT count(*) FROM llm_cache)
            """).fetchone()
    assert counts == (1, 1, 8, 10, 8)
    assert "OPENAI_API_KEY" not in capsys.readouterr().out


async def test_fake_llm_failure_remains_visible_as_failed_job(
    tmp_path: Path,
) -> None:
    """A deterministic LLM timeout must not disappear or create a report."""

    application = create_offline_application(
        tmp_path,
        llm_error=LLMTimeoutError("offline timeout"),
    )
    transport = ASGITransport(app=application)
    payload = offline_report_request().model_dump(mode="json")

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        submitted = await client.post("/v1/reports/generate", json=payload)
        task = await client.get(f"/v1/reports/jobs/{submitted.json()['job_id']}")

    assert submitted.status_code == 202
    assert task.json()["status"] == TaskStatus.FAILED.value
    assert task.json()["error"] == {
        "code": "report_generation_failed",
        "message": "Report generation failed.",
        "retryable": True,
        "details": None,
    }
    database = DuckDBDatabase(tmp_path / "duckdb" / "platform.duckdb")
    assert ReportRepository(database).get("rep_demo_1") is None
    with database.connection() as connection:
        statuses = connection.execute(
            "SELECT status FROM agent_runs ORDER BY run_id"
        ).fetchall()
    assert statuses == [("error",)] * 4
