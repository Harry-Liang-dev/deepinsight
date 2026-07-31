"""Health-check routes."""

from typing import Annotated

from fastapi import APIRouter, Depends

from src.api.dependencies import get_settings
from src.api.schemas import HealthResponse
from src.core.settings import AppSettings

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check(
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> HealthResponse:
    """Return application liveness and environment information."""
    return HealthResponse(environment=settings.env)
