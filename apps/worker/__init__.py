"""Single-Worker production application package."""

from apps.worker.runtime import build_report_worker

__all__ = ["build_report_worker"]
