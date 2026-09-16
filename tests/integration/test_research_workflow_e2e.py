"""Deterministic request-to-report integration through the public API."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, time
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api import offline as offline_app
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
    AgentRunRepository,
    DuckDBDatabase,
    FaissVectorRepository,
    InstrumentRepository,
    MarketDataRepository,
    MemoryItemRepository,
    ReportRepository,
)
from src.schemas.sector_context import SectorContextBundle
from src.services import LLMTimeoutError
from src.services.sector_context import FrozenSectorContextResolver
from tests.unit.services.test_sector_context import _aapl_bundle

pytestmark = pytest.mark.integration


async def test_phase4_sector_chain_and_radar_surface_through_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The formal workflow must render a used Sector Claim, not only carry it."""

    original = _aapl_bundle()
    research_as_of = datetime.combine(
        original.research_as_of.date(),
        time.max,
        tzinfo=UTC,
    )
    raw = original.model_dump(mode="json")
    raw["research_as_of"] = research_as_of
    claims = raw["accepted_claims"]
    assert isinstance(claims, list)
    anomaly = claims[-1]
    assert isinstance(anomaly, dict)
    surfaced_text = (
        "The Semiconductors & AI Compute sector's NVIDIA AI Infrastructure "
        "chain has a radar event whose asset implication remains conditional."
    )
    anomaly["claim_text"] = surfaced_text
    sector_context = SectorContextBundle.model_validate(raw)
    monkeypatch.setattr(
        offline_app,
        "OFFLINE_QUERY_TEXT",
        f"Research evidence for US:AAPL through {research_as_of.date().isoformat()}",
    )
    application = create_offline_application(
        tmp_path,
        sector_context_resolver=FrozenSectorContextResolver(sector_context),
    )
    request = offline_report_request().model_copy(
        update={"report_date": research_as_of.date()}
    )
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            "/v1/reports/generate",
            json=request.model_dump(mode="json"),
        )
        job_id = submitted.json()["job_id"]
        task = await client.get(f"/v1/reports/jobs/{job_id}")
        report = await client.get(f"/v1/reports/{task.json()['report_id']}")

    assert task.json()["status"] == TaskStatus.COMPLETED.value
    payload = report.json()
    assert surfaced_text in payload["report_markdown"]
    assert any(
        item.get("provider") == "sector_anomaly_radar"
        for item in payload["source_trace"]
    )


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
        durable_counts = connection.execute("""
            SELECT
                (SELECT count(*) FROM ingestion_jobs),
                (SELECT count(*) FROM text_documents),
                (SELECT count(*) FROM agent_runs),
                (SELECT count(*) FROM report_sections)
            """).fetchone()
        agent_cache_outcomes = connection.execute("""
            SELECT agent_name, status, cache_hit, output_payload_json
            FROM agent_runs
            ORDER BY agent_name
            """).fetchall()
        cache_rows = connection.execute("""
            SELECT cache_key, response_json
            FROM llm_cache
            ORDER BY cache_key
            """).fetchall()
    assert durable_counts == (1, 1, 8, 10)

    successful_cache_misses = [
        row
        for row in agent_cache_outcomes
        if row[1] == "ok" and row[2] is False and row[3] is not None
    ]
    rejected_initial_responses = [
        row for row in agent_cache_outcomes if row[1] == "error" and row[3] is None
    ]
    # Under agent_output_v2, invalid initial responses are rejected before
    # valid-cache persistence; cache cardinality is not an Agent-count proxy.
    assert rejected_initial_responses
    assert len(cache_rows) == len(successful_cache_misses)

    cache_fingerprints = [row[0] for row in cache_rows]
    assert len(cache_fingerprints) == len(set(cache_fingerprints))
    assert all(re.fullmatch(r"[0-9a-f]{64}", item) for item in cache_fingerprints)
    cached_responses = [json.loads(row[1]) for row in cache_rows]
    assert all(isinstance(response, dict) and response for response in cached_responses)
    assert not any(
        response.get("agent_name") == "fundamental_analyst"
        for response in cached_responses
    )
    fundamental_run = AgentRunRepository(restarted_database).get(
        "task_demo_1:fundamental_analyst"
    )
    assert fundamental_run is not None
    assert fundamental_run.status == "error"
    assert fundamental_run.output_payload is None
    assert fundamental_run.cache_hit is False

    technical_run = AgentRunRepository(restarted_database).get(
        "task_demo_1:technical_text_analyst"
    )
    assert technical_run is not None
    assert technical_run.status == "ok"
    invocation = technical_run.input_payload["input_payload"]
    assert isinstance(invocation, dict)
    contract = invocation["research_contract"]
    assert isinstance(contract, dict)
    assert contract["schema_version"] == "agent_input_v1"
    output = technical_run.output_payload
    assert output is not None
    analysis = output["analysis"]
    assert isinstance(analysis, dict)
    bindings = analysis["claim_evidence"]
    assert isinstance(bindings, list)
    assert bindings
    dict_bindings = [binding for binding in bindings if isinstance(binding, dict)]
    assert len(dict_bindings) == len(bindings)
    claim_paths = [binding["claim_path"] for binding in dict_bindings]
    assert len(claim_paths) == len(set(claim_paths))
    manifest = invocation["input_context"]
    assert isinstance(manifest, dict)
    role_manifest = manifest["role_evidence_manifest"]
    assert isinstance(role_manifest, dict)
    entries = role_manifest["entries"]
    assert isinstance(entries, list)
    canonical_ids = {
        entry["evidence_id"]
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("evidence_id"), str)
    }
    for binding in dict_bindings:
        evidence_ids = binding["evidence_ids"]
        assert isinstance(evidence_ids, list)
        assert all(isinstance(item, str) for item in evidence_ids)
        assert set(evidence_ids) <= canonical_ids
        assert binding["claim_path"]
        assert binding["claim_text"]
        assert binding["derivation_type"] == "direct_evidence"
    scope = contract["scope"]
    assert isinstance(scope, dict)
    assert scope["dataset_version"] == "offline_api_fixture_v1"
    memory = contract["memory"]
    assert isinstance(memory, dict)
    metadata = memory["retrieval_metadata"]
    assert isinstance(metadata, dict)
    as_of = metadata["as_of"]
    assert isinstance(as_of, str)
    assert as_of.endswith("Z")
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
