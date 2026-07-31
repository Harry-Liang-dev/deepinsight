"""FastAPI application factory."""

from fastapi import FastAPI

from src.api.errors import register_error_handlers
from src.api.routes import health, memory, phase2, reports
from src.api.services import ApiServices, default_api_services
from src.core.settings import AppSettings, load_settings


def create_app(
    *,
    settings: AppSettings | None = None,
    services: ApiServices | None = None,
) -> FastAPI:
    """Create an isolated DeepInsight API application.

    Args:
        settings: Optional settings override, primarily for tests.
        services: Optional application-service container.

    Returns:
        A configured FastAPI application.
    """
    resolved_settings = settings or load_settings()
    resolved_services = services or default_api_services()

    application = FastAPI(
        title="DeepInsight API",
        version="0.1.0",
    )
    application.state.settings = resolved_settings
    application.state.api_services = resolved_services

    register_error_handlers(application)
    application.include_router(health.router)
    application.include_router(reports.router)
    application.include_router(memory.router)
    application.include_router(phase2.router)
    return application
