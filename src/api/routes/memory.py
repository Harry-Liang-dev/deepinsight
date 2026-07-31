"""Memory write, retrieval, and snapshot routes."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, status

from src.api.dependencies import get_memory_service, get_snapshot_service
from src.api.errors import not_found
from src.api.schemas import MemorySnapshotResponse
from src.api.services import MemoryApiService, SnapshotQueryService
from src.schemas import (
    MemorySearchRequest,
    MemorySearchResponse,
    MemoryWriteRequest,
    MemoryWriteResult,
)

router = APIRouter(prefix="/v1/memory", tags=["memory"])


@router.post(
    "/write",
    response_model=MemoryWriteResult,
    status_code=status.HTTP_201_CREATED,
)
async def write_memory(
    request: MemoryWriteRequest,
    memory_service: Annotated[MemoryApiService, Depends(get_memory_service)],
) -> MemoryWriteResult:
    """Write a structured Memory item through the application service."""
    return memory_service.write(request)


@router.post("/search", response_model=MemorySearchResponse)
async def search_memory(
    request: MemorySearchRequest,
    memory_service: Annotated[MemoryApiService, Depends(get_memory_service)],
) -> MemorySearchResponse:
    """Search Memory through the application service."""
    return memory_service.search(request)


@router.get(
    "/snapshot/{snapshot_date}",
    response_model=MemorySnapshotResponse,
)
async def get_memory_snapshot(
    snapshot_date: date,
    snapshot_service: Annotated[SnapshotQueryService, Depends(get_snapshot_service)],
) -> MemorySnapshotResponse:
    """Return metadata for a Memory snapshot."""
    snapshot = snapshot_service.get(snapshot_date)
    if snapshot is None:
        raise not_found(
            code="snapshot_not_found",
            message=f"Memory snapshot '{snapshot_date.isoformat()}' was not found.",
        )
    return snapshot
