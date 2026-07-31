"""FastAPI dependency providers for API-level services."""

from typing import cast

from fastapi import Request

from src.api.services import (
    ApiServices,
    MemoryApiService,
    ReportQueryService,
    ReportTaskService,
    SnapshotQueryService,
)
from src.core.settings import AppSettings


async def get_settings(request: Request) -> AppSettings:
    """Return settings attached to the current application."""
    return cast(AppSettings, request.app.state.settings)


async def get_api_services(request: Request) -> ApiServices:
    """Return the API service container attached to the application."""
    return cast(ApiServices, request.app.state.api_services)


async def get_report_task_service(request: Request) -> ReportTaskService:
    """Return the report task application service."""
    services = cast(ApiServices, request.app.state.api_services)
    return services.report_tasks


async def get_report_query_service(request: Request) -> ReportQueryService:
    """Return the report query application service."""
    services = cast(ApiServices, request.app.state.api_services)
    return services.reports


async def get_memory_service(request: Request) -> MemoryApiService:
    """Return the Memory application service."""
    services = cast(ApiServices, request.app.state.api_services)
    return services.memory


async def get_snapshot_service(request: Request) -> SnapshotQueryService:
    """Return the snapshot query application service."""
    services = cast(ApiServices, request.app.state.api_services)
    return services.snapshots
