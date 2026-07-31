"""Explicit structlog initialization for application processes."""

from __future__ import annotations

import logging

import structlog
from structlog.typing import Processor

from src.core.settings import LoggingSettings, LogLevel


def _numeric_log_level(level: LogLevel) -> int:
    """Convert the validated log level to its stdlib numeric value."""

    return {
        LogLevel.DEBUG: logging.DEBUG,
        LogLevel.INFO: logging.INFO,
        LogLevel.WARNING: logging.WARNING,
        LogLevel.ERROR: logging.ERROR,
        LogLevel.CRITICAL: logging.CRITICAL,
    }[level]


def configure_logging(settings: LoggingSettings) -> None:
    """Configure stdlib logging and structlog for the current process.

    Args:
        settings: Validated application logging settings.
    """

    numeric_level = _numeric_log_level(settings.level)
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.JSONRenderer(),
    ]

    logging.basicConfig(level=numeric_level, format="%(message)s", force=True)
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
