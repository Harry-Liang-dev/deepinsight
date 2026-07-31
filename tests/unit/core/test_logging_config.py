"""Tests for logging initialization."""

from __future__ import annotations

import logging

import structlog

from src.core.logging_config import configure_logging
from src.core.settings import LoggingSettings, LogLevel


def test_configure_logging_sets_requested_level() -> None:
    """Logging initialization should apply the validated level."""
    configure_logging(LoggingSettings(level=LogLevel.DEBUG))

    assert logging.getLogger().level == logging.DEBUG


def test_configure_logging_can_be_called_more_than_once() -> None:
    """Repeated initialization should replace the previous log level."""
    configure_logging(LoggingSettings(level=LogLevel.DEBUG))
    configure_logging(LoggingSettings(level=LogLevel.WARNING))

    assert logging.getLogger().level == logging.WARNING
    assert structlog.is_configured()
