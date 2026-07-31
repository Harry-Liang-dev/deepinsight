"""ASGI application entry point for local and container execution."""

from src.api import create_app
from src.core.logging_config import configure_logging
from src.core.settings import load_settings

settings = load_settings()
configure_logging(settings.logging)
app = create_app(settings=settings)
