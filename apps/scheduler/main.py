"""Long-running single Scheduler process."""

from __future__ import annotations

import structlog
from apscheduler.schedulers.blocking import BlockingScheduler

from apps.scheduler.jobs import submit_daily_reports
from src.core import configure_logging, load_settings


def main() -> None:
    """Start the configured daily UTC report schedule."""

    settings = load_settings()
    configure_logging(settings.logging)
    logger = structlog.get_logger(__name__)
    if not settings.scheduler.enabled:
        logger.warning("scheduler_disabled")
        return
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        submit_daily_reports,
        "cron",
        args=[settings],
        hour=settings.scheduler.report_hour_utc,
        minute=settings.scheduler.report_minute_utc,
        max_instances=1,
        coalesce=True,
        id="daily_single_asset_reports",
        replace_existing=True,
    )
    logger.info(
        "scheduler_started",
        hour_utc=settings.scheduler.report_hour_utc,
        minute_utc=settings.scheduler.report_minute_utc,
    )
    scheduler.start()


if __name__ == "__main__":
    main()
