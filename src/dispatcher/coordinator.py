from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from src.dispatcher.scheduler import PollScheduler
from src.dispatcher.watcher import FileWatcher


class DispatcherCoordinator:
    """Wires FileWatcher + PollScheduler into one start/stop unit.

    Per the spec:
      - watcher fires `on_task_change(path)` when human edits a .md file in tasks/
      - scheduler runs `on_poll()` every poll_interval_seconds (default 30 min)
      - `suppress_self()` is exposed so the Orchestrator can wrap its own writes
    """

    DEFAULT_POLL_INTERVAL_SECONDS = 30 * 60
    # 15s absorbs Obsidian Sync's mid-typing partial uploads from mobile.
    # See `Config.debounce_seconds` for the full rationale; this is the
    # value used when the dispatcher is built without explicit config
    # (test paths, one-off invocations).
    DEFAULT_DEBOUNCE_SECONDS = 15.0

    def __init__(
        self,
        tasks_dir: Path,
        on_task_change: Callable[[Path], None],
        on_poll: Callable[[], None],
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        self.watcher = FileWatcher(
            tasks_dir=tasks_dir,
            on_change=on_task_change,
            debounce_seconds=debounce_seconds,
        )
        self.scheduler = PollScheduler()

        self._on_poll = on_poll
        self._poll_interval_seconds = poll_interval_seconds
        self._started = False

    def set_callbacks(
        self,
        on_task_change: Callable[[Path], None],
        on_poll: Callable[[], None],
    ) -> None:
        """Replace both the file-change callback and the poll callback.

        Used by the factory after orchestrator construction. The watcher's
        on_change is updated directly (it is checked at every event); the poll
        callback is stored and read whenever start() schedules its job.

        Safe to call while the coordinator is running — relies on the GIL
        for atomic attribute writes; revisit if running on free-threaded CPython.
        """
        self.watcher.on_change = on_task_change
        self._on_poll = on_poll

    def start(self) -> None:
        if self._started:
            return
        self.watcher.start()
        self.scheduler.add_job(self._on_poll, self._poll_interval_seconds, job_id="poll")
        self.scheduler.start()
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self.watcher.stop()
        self.scheduler.stop()
        self._started = False

    @contextmanager
    def suppress_self(self) -> Iterator[None]:
        """Pass-through to the watcher's suppress_self for use by Orchestrator writes."""
        with self.watcher.suppress_self():
            yield
