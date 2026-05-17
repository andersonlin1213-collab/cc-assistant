from __future__ import annotations

import logging
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

_log = logging.getLogger(__name__)


class PollScheduler:
    """Wraps APScheduler BackgroundScheduler to register multiple interval jobs.

    Used for the spec's two periodic responsibilities:
      - 30-min poll (Mechanism B fallback)
      - 5-min git pull
    """

    def __init__(self) -> None:
        # `misfire_grace_time=None` is APScheduler's "always run, never skip" setting.
        # `max_instances=1` prevents overlapping runs of the same job.
        self._scheduler = BackgroundScheduler(
            job_defaults={"misfire_grace_time": None, "max_instances": 1, "coalesce": True}
        )
        self._started = False

    def add_job(self, callback: Callable[[], None], interval_seconds: float, job_id: str) -> None:
        wrapped = _safe(callback)
        self._scheduler.add_job(
            wrapped,
            trigger=IntervalTrigger(seconds=interval_seconds),
            id=job_id,
            replace_existing=True,
        )

    def remove_job(self, job_id: str) -> None:
        try:
            self._scheduler.remove_job(job_id)
        except Exception:  # noqa: BLE001 — APScheduler raises JobLookupError; we don't want to depend on its exception class
            pass

    def start(self) -> None:
        if not self._started:
            self._scheduler.start()
            self._started = True

    def stop(self) -> None:
        if self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False


def _safe(fn: Callable[[], None]) -> Callable[[], None]:
    """Wrap a callback so exceptions are logged but never propagate to APScheduler.

    APScheduler will log unhandled job exceptions, but with `max_instances=1` a
    raised exception can interact with the executor in surprising ways. Catching
    here keeps each job independent.
    """

    def wrapper() -> None:
        try:
            fn()
        except Exception:  # noqa: BLE001
            _log.exception("scheduled job failed")

    return wrapper
