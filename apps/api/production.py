"""Production API composition with durable DuckDB jobs and Redis dispatch."""

from __future__ import annotations

from fastapi import FastAPI

from src.api import create_app
from src.api.services import (
    ApiServices,
    DurableReportTaskService,
    LocalSnapshotQueryService,
    UnavailableMemoryApiService,
)
from src.core import AppSettings, load_settings
from src.orchestration import RedisReportJobQueue
from src.repositories import (
    DuckDBDatabase,
    ReportJobRepository,
    ReportRepository,
)


def create_production_application(
    settings: AppSettings | None = None,
) -> FastAPI:
    """Create the durable API boundary without loading model credentials."""

    resolved = settings or load_settings()
    database = DuckDBDatabase(resolved.storage.duckdb_path)
    database.bootstrap()
    queue = RedisReportJobQueue(
        resolved.redis.url,
        queue_name=resolved.redis.report_queue_name,
    )
    services = ApiServices(
        report_tasks=DurableReportTaskService(
            ReportJobRepository(database),
            queue,
        ),
        reports=ReportRepository(database),
        memory=UnavailableMemoryApiService(),
        snapshots=LocalSnapshotQueryService(resolved.storage.snapshot_root),
    )
    return create_app(settings=resolved, services=services)
