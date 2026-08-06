"""Network-free checks for the durable production API composition."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from apps.api.production import create_production_application
from src.core import AppEnvironment, AppSettings, StorageSettings
from src.operations import create_snapshot


@pytest.mark.asyncio
async def test_production_factory_exposes_health_and_existing_snapshot(
    tmp_path: Path,
) -> None:
    """Production reads should work without loading LLM credentials or Redis."""

    storage = StorageSettings(
        duckdb_path=tmp_path / "duckdb" / "platform.duckdb",
        faiss_root=tmp_path / "faiss",
        raw_root=tmp_path / "raw",
        snapshot_root=tmp_path / "snapshots",
        backup_root=tmp_path / "backups",
    )
    app = create_production_application(
        AppSettings(env=AppEnvironment.TEST, storage=storage)
    )
    create_snapshot(
        storage,
        now=datetime(2026, 8, 7, 12, tzinfo=UTC),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        health = await client.get("/health")
        snapshot = await client.get("/v1/memory/snapshot/2026-08-07")

    assert health.status_code == 200
    assert health.json()["environment"] == "test"
    assert snapshot.status_code == 200
    assert snapshot.json() == {
        "snapshot_date": "2026-08-07",
        "duckdb_artifact": "platform.duckdb",
        "faiss_artifacts": ["faiss.tar.gz"],
        "status": "ok",
    }
