"""Long-running single report Worker process."""

from __future__ import annotations

import signal

import structlog

from apps.worker.runtime import build_report_worker
from src.core import configure_logging, load_settings


def main() -> None:
    """Recover interrupted jobs and process the Redis queue serially."""

    settings = load_settings()
    configure_logging(settings.logging)
    logger = structlog.get_logger(__name__)
    worker = build_report_worker(settings)
    recovered = worker.recover_interrupted()
    running = True

    def stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    logger.info("report_worker_started", recovered_jobs=recovered)
    while running:
        worker.run_once(timeout_seconds=settings.redis.poll_timeout_seconds)
    logger.info("report_worker_stopped")


if __name__ == "__main__":
    main()
