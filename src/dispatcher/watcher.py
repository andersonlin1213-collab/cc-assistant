from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


_log = logging.getLogger(__name__)


_IGNORE_PATH_FRAGMENTS = (
    "/.obsidian/",
    "\\.obsidian\\",          # Windows
    "/_attachments/",
    "\\_attachments\\",
    "/.trash/",
    "\\.trash\\",
    "/templates/",
    "\\templates\\",
)

_COLUMN_NAMES = frozenset(("backlog", "todo", "doing", "blocked", "review"))
_PROJECT_FOLDER_NAME = "projects"


def _is_ignored(path: Path) -> bool:
    p = str(path)
    if any(frag in p for frag in _IGNORE_PATH_FRAGMENTS):
        return True
    # Obsidian Sync conflict files: "<name> (conflict YYYY-MM-DD HH:MM:SS).md"
    if " (conflict " in path.name:
        return True
    # Whitelist: only .md files in a column subfolder count as tasks. Files
    # at the vault root (mobile Obsidian creates new notes there by default,
    # README.md, scratch drafts) are not tasks; ignore them so the daemon
    # doesn't spam `task_malformed` log entries on every save.
    parent_name = path.parent.name
    if parent_name in _COLUMN_NAMES:
        return False
    if parent_name == _PROJECT_FOLDER_NAME:
        # tasks/projects/<slug>.md — project cards. Routed to project_handler
        # by the factory's on_task_change wrapper, not orchestrator.run_cycle.
        return False
    # done/ has YYYY-MM subdirs — done/<month>/<file>.md is also a valid task.
    grandparent = path.parent.parent
    if grandparent != path.parent and grandparent.name == "done":
        return False
    return True


class FileWatcher:
    """Watch a directory tree for `.md` file changes and dispatch debounced callbacks.

    - Filters to `.md` files only.
    - Debounces consecutive events for the same path within `debounce_seconds`.
    - Supports `suppress_self()` context manager so the Agent's own writes
      do not retrigger the callback (per spec Layer 2 self-modification detection).
    """

    def __init__(
        self,
        tasks_dir: Path,
        on_change: Callable[[Path], None],
        debounce_seconds: float = 15.0,
    ) -> None:
        self.tasks_dir = Path(tasks_dir)
        self.on_change = on_change
        self.debounce_seconds = debounce_seconds

        self._observer: Observer | None = None
        self._timers: dict[Path, threading.Timer] = {}
        self._lock = threading.Lock()
        self._suppressed_until = 0.0

    def start(self) -> None:
        if self._observer is not None:
            return
        handler = _MarkdownEventHandler(self._on_event)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.tasks_dir), recursive=True)
        self._observer.start()

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2.0)
            self._observer = None
        with self._lock:
            for t in self._timers.values():
                t.cancel()
            self._timers.clear()

    @contextmanager
    def suppress_self(self) -> Iterator[None]:
        """Suppress callbacks for events arriving during and shortly after this block.

        Suppression starts on entry (set to infinity) so that debounce timers scheduled
        inside the block are also caught at fire time, regardless of how long the block
        runs (LLM calls can take minutes). The `finally` clause guarantees suppression
        is reset to a bounded trailing buffer (debounce_seconds + 0.5s) on exit.
        """
        self._suppressed_until = float("inf")
        try:
            yield
        finally:
            self._suppressed_until = time.time() + self.debounce_seconds + 0.5

    def _on_event(self, event: FileSystemEvent) -> None:
        if time.time() < self._suppressed_until:
            return
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix != ".md":
            return
        if _is_ignored(path):
            return

        with self._lock:
            existing = self._timers.pop(path, None)
            if existing is not None:
                existing.cancel()
            timer = threading.Timer(self.debounce_seconds, self._fire, args=[path])
            self._timers[path] = timer
            timer.daemon = True
            timer.start()

    def _fire(self, path: Path) -> None:
        with self._lock:
            self._timers.pop(path, None)
        # Re-check suppression at fire time in case it was set after the timer scheduled.
        if time.time() < self._suppressed_until:
            return
        try:
            self.on_change(path)
        except Exception:
            # Callback errors must not kill the watcher thread.
            _log.exception("watcher callback failed for %s", path)


class _MarkdownEventHandler(FileSystemEventHandler):
    """Routes any FS event to the FileWatcher's _on_event."""

    def __init__(self, callback: Callable[[FileSystemEvent], None]) -> None:
        self._callback = callback

    def on_created(self, event: FileSystemEvent) -> None:
        self._callback(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._callback(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        # The original src_path no longer exists; its callback may be a no-op.
        # Dispatch the destination path as well so renames within the tree are seen.
        self._callback(event)
        if not event.is_directory and getattr(event, "dest_path", None):
            from watchdog.events import FileModifiedEvent
            self._callback(FileModifiedEvent(event.dest_path))
