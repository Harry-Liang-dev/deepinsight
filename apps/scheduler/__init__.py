"""Single Phase One report Scheduler application."""

from apps.scheduler.jobs import submit_daily_reports

__all__ = ["submit_daily_reports"]
