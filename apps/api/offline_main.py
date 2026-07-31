"""Ephemeral offline ASGI entry point for a no-credential local demo."""

from pathlib import Path
from tempfile import TemporaryDirectory

from apps.api.offline import create_offline_application
from src.core.logging_config import configure_logging
from src.core.settings import LoggingSettings

_data_directory = TemporaryDirectory(prefix="deepinsight-offline-")
configure_logging(LoggingSettings())
app = create_offline_application(Path(_data_directory.name))
