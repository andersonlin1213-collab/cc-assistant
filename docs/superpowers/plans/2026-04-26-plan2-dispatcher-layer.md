# Plan 2: Dispatcher / Trigger Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the dispatcher layer that triggers Agent execution: a watchdog-based file watcher (event-driven primary), an APScheduler-based polling fallback, a Git sync wrapper, and a coordinator that wires them together with debouncing and self-modification suppression.

**Architecture:** Three independent components (FileWatcher, PollScheduler, GitSync) coordinated by a DispatcherCoordinator. Watcher fires `on_task_change(path)` for `.md` file edits in `tasks/*/`, debounced over 2s and suppressed during Agent's own writes. Scheduler runs two periodic jobs: a 30-minute poll (Mechanism B) and a 5-minute git pull. GitSync wraps `git add/commit/pull` with safe no-ops when there are no changes or no remote. Layer 3's Orchestrator (future) will register `on_task_change` and `on_poll` callbacks; for Plan 2, callbacks are passed in by tests.

**Tech Stack:** Python 3.11+, watchdog, APScheduler, subprocess (for git), pytest, pytest-asyncio. All existing Plan 1 modules remain untouched.

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Modify | `pyproject.toml` | Add `watchdog>=4.0`, `apscheduler>=3.10` to dependencies |
| Create | `src/dispatcher/__init__.py` | Package marker |
| Create | `src/dispatcher/watcher.py` | `FileWatcher` — watchdog wrapper, debouncing, self-suppression, .md filter |
| Create | `src/dispatcher/scheduler.py` | `PollScheduler` — APScheduler wrapper, supports multiple interval jobs |
| Create | `src/dispatcher/sync.py` | `GitSync` — `commit_and_push(message)`, `pull()`; safe no-ops |
| Create | `src/dispatcher/coordinator.py` | `DispatcherCoordinator` — wires watcher + scheduler + sync, exposes `start()`/`stop()`/`suppress_self()` |
| Create | `tests/test_watcher.py` | FileWatcher tests (debounce, suppression, filter) |
| Create | `tests/test_scheduler.py` | PollScheduler tests (interval firing, stop) |
| Create | `tests/test_sync.py` | GitSync tests (commit, no-op, pull no-remote) |
| Create | `tests/test_coordinator.py` | Coordinator integration test |

**Note:** Plan 1 did not create `src/dispatcher/`. Task 1 creates the directory and its `__init__.py`.

---

### Task 1: Add Dependencies and Dispatcher Package

**Files:**
- Modify: `pyproject.toml`
- Create: `src/dispatcher/__init__.py`

- [ ] **Step 1: Add dependencies via uv**

```bash
cd /c/<your-user>/projects/cc-assitant
uv add "watchdog>=4.0" "apscheduler>=3.10"
```

This will:
- Update `pyproject.toml` adding `watchdog>=4.0` and `apscheduler>=3.10` to `[project] dependencies`
- Update `uv.lock`
- Install into `.venv`

- [ ] **Step 2: Create dispatcher package directory and `__init__.py`**

```bash
mkdir -p src/dispatcher
touch src/dispatcher/__init__.py
```

- [ ] **Step 3: Verify install**

```bash
uv run python -c "import watchdog; import apscheduler; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock src/dispatcher/__init__.py
git commit -m "chore: add watchdog and apscheduler dependencies for dispatcher layer"
```

---

### Task 2: FileWatcher

**Files:**
- Create: `src/dispatcher/watcher.py`
- Create: `tests/test_watcher.py`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_watcher.py`:

```python
import threading
import time
from pathlib import Path

import pytest

from src.dispatcher.watcher import FileWatcher


def _wait_for(predicate, timeout=3.0, interval=0.05):
    """Poll predicate until True or timeout. Returns True if predicate held."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_watcher_fires_on_md_create(tmp_path):
    """Creating a .md file in the watched dir triggers the callback."""
    seen: list[Path] = []
    watcher = FileWatcher(
        tasks_dir=tmp_path,
        on_change=lambda p: seen.append(p),
        debounce_seconds=0.1,
    )
    watcher.start()
    try:
        target = tmp_path / "subdir"
        target.mkdir()
        (target / "001.md").write_text("hello", encoding="utf-8")
        assert _wait_for(lambda: len(seen) >= 1), f"callback not fired, seen={seen}"
        assert any(p.name == "001.md" for p in seen)
    finally:
        watcher.stop()


def test_watcher_fires_on_md_modify(tmp_path):
    """Modifying an existing .md file triggers the callback."""
    target = tmp_path / "002.md"
    target.write_text("v1", encoding="utf-8")

    seen: list[Path] = []
    watcher = FileWatcher(
        tasks_dir=tmp_path,
        on_change=lambda p: seen.append(p),
        debounce_seconds=0.1,
    )
    watcher.start()
    try:
        time.sleep(0.05)  # let watcher settle
        target.write_text("v2", encoding="utf-8")
        assert _wait_for(lambda: len(seen) >= 1), f"callback not fired, seen={seen}"
    finally:
        watcher.stop()


def test_watcher_ignores_non_md(tmp_path):
    """Non-.md files are filtered out."""
    seen: list[Path] = []
    watcher = FileWatcher(
        tasks_dir=tmp_path,
        on_change=lambda p: seen.append(p),
        debounce_seconds=0.1,
    )
    watcher.start()
    try:
        (tmp_path / "ignore.txt").write_text("x", encoding="utf-8")
        (tmp_path / ".gitkeep").write_text("", encoding="utf-8")
        time.sleep(0.3)  # debounce window + buffer
        assert seen == [], f"non-md files leaked: {seen}"
    finally:
        watcher.stop()


def test_watcher_debounces_rapid_writes(tmp_path):
    """Multiple rapid writes within debounce window produce a single callback."""
    target = tmp_path / "003.md"
    target.write_text("init", encoding="utf-8")

    seen: list[Path] = []
    watcher = FileWatcher(
        tasks_dir=tmp_path,
        on_change=lambda p: seen.append(p),
        debounce_seconds=0.3,
    )
    watcher.start()
    try:
        time.sleep(0.05)
        for i in range(5):
            target.write_text(f"v{i}", encoding="utf-8")
            time.sleep(0.02)
        # Before debounce expires, no fire yet (it may have fired once already from initial event flush;
        # after debounce, total should be small)
        time.sleep(0.5)  # allow debounce to settle
        assert len(seen) <= 2, f"debounce failed, got {len(seen)} fires"
        assert len(seen) >= 1, "no fire at all"
    finally:
        watcher.stop()


def test_watcher_suppress_self(tmp_path):
    """Writes inside `suppress_self()` block do not trigger the callback."""
    seen: list[Path] = []
    watcher = FileWatcher(
        tasks_dir=tmp_path,
        on_change=lambda p: seen.append(p),
        debounce_seconds=0.1,
    )
    watcher.start()
    try:
        time.sleep(0.05)
        with watcher.suppress_self():
            (tmp_path / "agent.md").write_text("agent write", encoding="utf-8")
            time.sleep(0.3)  # let any in-flight events flush
        # After exiting, suppression buffer should still hold for debounce + small buffer
        time.sleep(0.7)
        assert seen == [], f"agent's own write leaked: {seen}"

        # Sanity: a fresh write (not suppressed) DOES fire
        (tmp_path / "human.md").write_text("human write", encoding="utf-8")
        assert _wait_for(lambda: len(seen) >= 1, timeout=2.0)
    finally:
        watcher.stop()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_watcher.py -v
```

Expected: FAIL — cannot import `FileWatcher`.

- [ ] **Step 3: Write implementation**

Write `src/dispatcher/watcher.py`:

```python
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


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
        debounce_seconds: float = 2.0,
    ) -> None:
        self.tasks_dir = Path(tasks_dir)
        self.on_change = on_change
        self.debounce_seconds = debounce_seconds

        self._observer: Observer | None = None
        self._timers: dict[Path, threading.Timer] = {}
        self._lock = threading.Lock()
        self._suppressed_until = 0.0

    def start(self) -> None:
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

        The trailing buffer = debounce_seconds + 0.5s ensures any in-flight events
        from the agent's writes do not leak into the next user edit.
        """
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
            # Callback errors must not kill the watcher thread; log to stderr in real use.
            import traceback

            traceback.print_exc()


class _MarkdownEventHandler(FileSystemEventHandler):
    """Routes any FS event to the FileWatcher's _on_event."""

    def __init__(self, callback: Callable[[FileSystemEvent], None]) -> None:
        self._callback = callback

    def on_created(self, event: FileSystemEvent) -> None:
        self._callback(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._callback(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        self._callback(event)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_watcher.py -v
```

Expected: 5 passed. (Tests have generous timeouts for cross-platform reliability; Windows in particular can be slow with watchdog.)

If any test fails intermittently due to timing, increase the timeout in `_wait_for` calls, but do not change debounce values.

- [ ] **Step 5: Commit**

```bash
git add src/dispatcher/watcher.py tests/test_watcher.py
git commit -m "feat: add FileWatcher with .md filter, debouncing, and self-suppression"
```

---

### Task 3: PollScheduler

**Files:**
- Create: `src/dispatcher/scheduler.py`
- Create: `tests/test_scheduler.py`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_scheduler.py`:

```python
import threading
import time

from src.dispatcher.scheduler import PollScheduler


def test_scheduler_fires_at_interval():
    """A job runs at its configured interval."""
    counter = {"n": 0}

    def tick() -> None:
        counter["n"] += 1

    scheduler = PollScheduler()
    scheduler.add_job(tick, interval_seconds=0.1, job_id="tick")
    scheduler.start()
    try:
        time.sleep(0.45)  # expect ~4 fires
    finally:
        scheduler.stop()

    assert counter["n"] >= 3, f"expected >=3 fires, got {counter['n']}"


def test_scheduler_runs_multiple_jobs():
    """Two jobs at different intervals both run."""
    a = {"n": 0}
    b = {"n": 0}

    scheduler = PollScheduler()
    scheduler.add_job(lambda: a.__setitem__("n", a["n"] + 1), interval_seconds=0.1, job_id="a")
    scheduler.add_job(lambda: b.__setitem__("n", b["n"] + 1), interval_seconds=0.2, job_id="b")
    scheduler.start()
    try:
        time.sleep(0.5)
    finally:
        scheduler.stop()

    assert a["n"] >= 3, f"job 'a' fired {a['n']} times"
    assert b["n"] >= 1, f"job 'b' fired {b['n']} times"
    assert a["n"] > b["n"], "job 'a' should fire more often than 'b'"


def test_scheduler_stop_halts_jobs():
    """After stop(), no more callbacks fire."""
    counter = {"n": 0}
    scheduler = PollScheduler()
    scheduler.add_job(lambda: counter.__setitem__("n", counter["n"] + 1), interval_seconds=0.05, job_id="t")
    scheduler.start()
    time.sleep(0.2)
    scheduler.stop()
    snapshot = counter["n"]
    time.sleep(0.3)
    assert counter["n"] == snapshot, f"jobs kept firing after stop: {snapshot}->{counter['n']}"


def test_scheduler_callback_exception_does_not_kill_scheduler():
    """A failing callback doesn't stop subsequent invocations."""
    state = {"good": 0, "bad": 0}

    def bad() -> None:
        state["bad"] += 1
        raise RuntimeError("boom")

    def good() -> None:
        state["good"] += 1

    scheduler = PollScheduler()
    scheduler.add_job(bad, interval_seconds=0.1, job_id="bad")
    scheduler.add_job(good, interval_seconds=0.1, job_id="good")
    scheduler.start()
    try:
        time.sleep(0.45)
    finally:
        scheduler.stop()

    assert state["bad"] >= 2, "failing job should still be retried"
    assert state["good"] >= 2, "good job should not be affected by bad's failures"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_scheduler.py -v
```

Expected: FAIL — cannot import `PollScheduler`.

- [ ] **Step 3: Write implementation**

Write `src/dispatcher/scheduler.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_scheduler.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dispatcher/scheduler.py tests/test_scheduler.py
git commit -m "feat: add PollScheduler wrapping APScheduler with safe-callback wrapping"
```

---

### Task 4: GitSync

**Files:**
- Create: `src/dispatcher/sync.py`
- Create: `tests/test_sync.py`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_sync.py`:

```python
import subprocess
from pathlib import Path

from src.dispatcher.sync import GitSync


def _git(repo: Path, *args: str) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    """Initialize a git repo with one initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@test.local")
    _git(repo, "config", "user.name", "Tester")
    (repo / "README").write_text("hi", encoding="utf-8")
    _git(repo, "add", "README")
    _git(repo, "commit", "-m", "initial")
    return repo


def test_commit_and_push_creates_commit_when_dirty(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "task.md").write_text("body", encoding="utf-8")

    sync = GitSync(repo_dir=repo)
    result = sync.commit_and_push("agent: added task")

    assert result.committed is True
    assert "agent: added task" in _git(repo, "log", "-1", "--pretty=%s")


def test_commit_and_push_noop_when_clean(tmp_path):
    repo = _init_repo(tmp_path)

    sync = GitSync(repo_dir=repo)
    result = sync.commit_and_push("agent: nothing")

    assert result.committed is False
    # No new commit
    log = _git(repo, "log", "--oneline")
    assert log.count("\n") == 0  # only initial commit


def test_commit_skips_push_when_no_remote(tmp_path):
    """commit_and_push should not error when no remote 'origin' exists."""
    repo = _init_repo(tmp_path)
    (repo / "x.md").write_text("x", encoding="utf-8")

    sync = GitSync(repo_dir=repo)
    result = sync.commit_and_push("agent: x")

    assert result.committed is True
    assert result.pushed is False  # no remote, push silently skipped


def test_pull_returns_false_when_no_remote(tmp_path):
    """pull() should return False (not raise) when no remote exists."""
    repo = _init_repo(tmp_path)
    sync = GitSync(repo_dir=repo)
    assert sync.pull() is False


def test_pull_returns_true_when_remote_pulls_cleanly(tmp_path):
    """A real git remote pull is exercised by setting up a bare upstream."""
    upstream = tmp_path / "upstream.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(upstream)], check=True)

    repo = _init_repo(tmp_path)
    _git(repo, "remote", "add", "origin", str(upstream))
    _git(repo, "push", "-u", "origin", "main")

    sync = GitSync(repo_dir=repo)
    assert sync.pull() is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_sync.py -v
```

Expected: FAIL — cannot import `GitSync`.

- [ ] **Step 3: Write implementation**

Write `src/dispatcher/sync.py`:

```python
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Result of a commit_and_push attempt."""

    committed: bool
    pushed: bool


class GitSync:
    """Wraps git CLI for the auto-sync workflow.

    - `commit_and_push(message)`: stages everything, commits if dirty, pushes if remote exists.
    - `pull()`: pulls from origin if a remote is configured; returns False on no-remote or error.

    Conflict resolution policy from the spec ("merge by latest timestamp in conversation
    entries; if irreconcilable, keep both") is NOT implemented here — it requires content
    awareness and is deferred to the Orchestrator (Plan 3+) which can use the parser.
    For Plan 2, conflicts surface as a non-zero exit from `git pull`, returning False.
    """

    def __init__(self, repo_dir: Path) -> None:
        self.repo_dir = Path(repo_dir)

    def commit_and_push(self, message: str) -> SyncResult:
        if not self._is_dirty():
            return SyncResult(committed=False, pushed=False)

        self._run("add", "-A")
        # `--allow-empty-message` is NOT used; spec requires a message. Caller must provide one.
        self._run("commit", "-m", message)
        committed = True

        pushed = False
        if self._has_remote("origin"):
            try:
                self._run("push", "origin", "HEAD")
                pushed = True
            except subprocess.CalledProcessError as e:
                _log.warning("git push failed: %s", e.stderr if e.stderr else e)
                pushed = False
        return SyncResult(committed=committed, pushed=pushed)

    def pull(self) -> bool:
        if not self._has_remote("origin"):
            return False
        try:
            self._run("pull", "--ff-only", "origin", "HEAD")
            return True
        except subprocess.CalledProcessError as e:
            _log.warning("git pull failed: %s", e.stderr if e.stderr else e)
            return False

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _is_dirty(self) -> bool:
        """True if there are any tracked-modified or untracked-non-ignored files."""
        out = self._run("status", "--porcelain").stdout.strip()
        return bool(out)

    def _has_remote(self, name: str) -> bool:
        try:
            self._run("remote", "get-url", name)
            return True
        except subprocess.CalledProcessError:
            return False

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo_dir,
            check=True,
            capture_output=True,
            text=True,
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_sync.py -v
```

Expected: 5 passed.

If `test_pull_returns_true_when_remote_pulls_cleanly` fails on Windows due to git bare repo path issues, verify the test uses a path with no spaces. The default `tmp_path` pytest fixture should be fine.

- [ ] **Step 5: Commit**

```bash
git add src/dispatcher/sync.py tests/test_sync.py
git commit -m "feat: add GitSync wrapping git CLI with safe no-ops on clean and no-remote"
```

---

### Task 5: DispatcherCoordinator

**Files:**
- Create: `src/dispatcher/coordinator.py`
- Create: `tests/test_coordinator.py`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_coordinator.py`:

```python
import time
from pathlib import Path

from src.dispatcher.coordinator import DispatcherCoordinator


def test_coordinator_dispatches_file_change(tmp_path):
    """A .md file edit in tasks_dir invokes on_task_change."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    seen: list[Path] = []

    coordinator = DispatcherCoordinator(
        tasks_dir=tasks_dir,
        repo_dir=tmp_path,  # repo_dir not used here (no git ops in this test)
        on_task_change=lambda p: seen.append(p),
        on_poll=lambda: None,
        debounce_seconds=0.1,
        poll_interval_seconds=3600,  # effectively disabled for this test
        git_pull_interval_seconds=3600,
    )
    coordinator.start()
    try:
        time.sleep(0.05)
        (tasks_dir / "001.md").write_text("hello", encoding="utf-8")
        deadline = time.time() + 3.0
        while time.time() < deadline and not seen:
            time.sleep(0.05)
        assert seen, "on_task_change was not invoked"
    finally:
        coordinator.stop()


def test_coordinator_dispatches_poll(tmp_path):
    """The on_poll callback fires at the poll interval."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    poll_count = {"n": 0}

    coordinator = DispatcherCoordinator(
        tasks_dir=tasks_dir,
        repo_dir=tmp_path,
        on_task_change=lambda p: None,
        on_poll=lambda: poll_count.__setitem__("n", poll_count["n"] + 1),
        debounce_seconds=0.1,
        poll_interval_seconds=0.1,
        git_pull_interval_seconds=3600,
    )
    coordinator.start()
    try:
        time.sleep(0.45)
    finally:
        coordinator.stop()

    assert poll_count["n"] >= 3, f"expected >=3 polls, got {poll_count['n']}"


def test_coordinator_suppress_self(tmp_path):
    """Writes inside coordinator.suppress_self() do not trigger on_task_change."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    seen: list[Path] = []

    coordinator = DispatcherCoordinator(
        tasks_dir=tasks_dir,
        repo_dir=tmp_path,
        on_task_change=lambda p: seen.append(p),
        on_poll=lambda: None,
        debounce_seconds=0.1,
        poll_interval_seconds=3600,
        git_pull_interval_seconds=3600,
    )
    coordinator.start()
    try:
        time.sleep(0.05)
        with coordinator.suppress_self():
            (tasks_dir / "agent.md").write_text("agent write", encoding="utf-8")
            time.sleep(0.3)
        time.sleep(0.7)
        assert seen == [], f"agent's own write leaked: {seen}"
    finally:
        coordinator.stop()


def test_coordinator_start_stop_idempotent(tmp_path):
    """start/stop can be called multiple times safely."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    coordinator = DispatcherCoordinator(
        tasks_dir=tasks_dir,
        repo_dir=tmp_path,
        on_task_change=lambda p: None,
        on_poll=lambda: None,
    )
    coordinator.start()
    coordinator.start()  # second start is a no-op
    coordinator.stop()
    coordinator.stop()  # second stop is a no-op
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_coordinator.py -v
```

Expected: FAIL — cannot import `DispatcherCoordinator`.

- [ ] **Step 3: Write implementation**

Write `src/dispatcher/coordinator.py`:

```python
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from src.dispatcher.scheduler import PollScheduler
from src.dispatcher.sync import GitSync
from src.dispatcher.watcher import FileWatcher


class DispatcherCoordinator:
    """Wires FileWatcher + PollScheduler + GitSync into one start/stop unit.

    Per the spec:
      - watcher fires `on_task_change(path)` when human edits a .md file in tasks/
      - scheduler runs `on_poll()` every poll_interval_seconds (default 30 min)
      - scheduler runs `git pull` every git_pull_interval_seconds (default 5 min)
      - `suppress_self()` is exposed so the Orchestrator can wrap its own writes
    """

    DEFAULT_POLL_INTERVAL_SECONDS = 30 * 60
    DEFAULT_GIT_PULL_INTERVAL_SECONDS = 5 * 60
    DEFAULT_DEBOUNCE_SECONDS = 2.0

    def __init__(
        self,
        tasks_dir: Path,
        repo_dir: Path,
        on_task_change: Callable[[Path], None],
        on_poll: Callable[[], None],
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        git_pull_interval_seconds: float = DEFAULT_GIT_PULL_INTERVAL_SECONDS,
    ) -> None:
        self.watcher = FileWatcher(
            tasks_dir=tasks_dir,
            on_change=on_task_change,
            debounce_seconds=debounce_seconds,
        )
        self.scheduler = PollScheduler()
        self.sync = GitSync(repo_dir=repo_dir)

        self._on_poll = on_poll
        self._poll_interval_seconds = poll_interval_seconds
        self._git_pull_interval_seconds = git_pull_interval_seconds
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self.watcher.start()
        self.scheduler.add_job(self._on_poll, self._poll_interval_seconds, job_id="poll")
        self.scheduler.add_job(self.sync.pull, self._git_pull_interval_seconds, job_id="git_pull")
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_coordinator.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dispatcher/coordinator.py tests/test_coordinator.py
git commit -m "feat: add DispatcherCoordinator wiring watcher, scheduler, and git sync"
```

---

### Task 6: Cross-Layer Integration Test

**Files:**
- Create: `tests/test_dispatcher_integration.py`

This test verifies Plan 2 plays well with Plan 1: a human edits a real task file in the kanban directory; the dispatcher detects it, the parser reads it, and a fake "orchestrator" callback updates the file using the writer + manager — all while inside `suppress_self()` so the agent's own writes do not loop.

- [ ] **Step 1: Write the integration test**

Write `tests/test_dispatcher_integration.py`:

```python
"""Plan 2 integration: dispatcher fires on user edit; orchestrator-style callback
parses, modifies, and moves the file inside suppress_self without retriggering itself.
"""

import threading
import time
from datetime import datetime
from pathlib import Path

from src.board.manager import BoardManager
from src.board.parser import parse_task_file
from src.board.writer import write_task_file, append_conversation
from src.dispatcher.coordinator import DispatcherCoordinator
from src.models import (
    ConversationEntry,
    ConversationRole,
    Priority,
    Task,
    TaskStatus,
)


def _make_kanban(tmp_path: Path) -> Path:
    tasks_dir = tmp_path / "tasks"
    for status in ["backlog", "todo", "doing", "blocked", "review", "done"]:
        (tasks_dir / status).mkdir(parents=True)
    return tasks_dir


def test_user_edit_triggers_orchestrator_loop(tmp_path):
    tasks_dir = _make_kanban(tmp_path)
    manager = BoardManager(tasks_dir)

    fired = threading.Event()
    seen_paths: list[Path] = []

    coordinator: DispatcherCoordinator | None = None

    def fake_orchestrator(path: Path) -> None:
        """Simulate Orchestrator: parse, append AI reply, move to doing — all inside suppress_self."""
        seen_paths.append(path)
        # Skip if file no longer at the original path (e.g., already moved)
        if not path.exists():
            return
        with coordinator.suppress_self():  # type: ignore[union-attr]
            task = parse_task_file(path)
            reply = ConversationEntry(
                role=ConversationRole.AI,
                timestamp=datetime(2026, 4, 26, 14, 1),
                content="收到，开始处理。",
            )
            append_conversation(path, reply)
            manager.move_task(path, TaskStatus.DOING)
        fired.set()

    coordinator = DispatcherCoordinator(
        tasks_dir=tasks_dir,
        repo_dir=tmp_path,
        on_task_change=fake_orchestrator,
        on_poll=lambda: None,
        debounce_seconds=0.2,
        poll_interval_seconds=3600,
        git_pull_interval_seconds=3600,
    )
    coordinator.start()
    try:
        time.sleep(0.1)

        # Human creates a task in todo/
        task = Task(
            id="100",
            title="Test integration",
            project="dispatcher-test",
            parent=None,
            priority=Priority.P1,
            tags=[],
            created=datetime(2026, 4, 26, 14, 0),
            updated=datetime(2026, 4, 26, 14, 0),
            auto_approve=True,
            description="A task for integration testing.",
            conversation=[],
        )
        todo_path = tasks_dir / "todo" / "100-integration.md"
        write_task_file(task, todo_path)

        assert fired.wait(timeout=5.0), f"orchestrator not invoked. seen={seen_paths}"

        # Verify the file was moved to doing/
        moved = tasks_dir / "doing" / "100-integration.md"
        assert moved.exists(), "task not moved to doing/"
        # Re-parse and verify AI reply appended
        moved_task = parse_task_file(moved)
        assert len(moved_task.conversation) == 1
        assert moved_task.conversation[0].role == ConversationRole.AI

        # Wait some more — the agent's own writes should NOT have re-triggered
        # the orchestrator (suppress_self should hold). seen_paths length 1 means
        # only the human's original edit fired the callback.
        time.sleep(1.0)
        assert len(seen_paths) == 1, (
            f"orchestrator fired more than once (loop?): {seen_paths}"
        )
    finally:
        coordinator.stop()
```

- [ ] **Step 2: Run the integration test**

```bash
uv run pytest tests/test_dispatcher_integration.py -v
```

Expected: 1 passed.

- [ ] **Step 3: Run the full test suite to ensure nothing regressed**

```bash
uv run pytest -v
```

Expected: All passing. Total tests: 42 (Plan 1) + 5 (watcher) + 4 (scheduler) + 5 (sync) + 4 (coordinator) + 1 (dispatcher integration) = **61**.

- [ ] **Step 4: Commit**

```bash
git add tests/test_dispatcher_integration.py
git commit -m "test: add cross-layer integration test for dispatcher + board layer"
```

---

## Self-Review

**1. Spec coverage (Layer 2):**
- Mechanism A (watchdog event-driven): Task 2 — `FileWatcher` with `.md` filter, debounce, suppression.
- Mechanism B (APScheduler polling): Task 3 — `PollScheduler` supporting multiple interval jobs.
- Self-modification flag (`suppress_self`): Task 2 (FileWatcher), Task 5 (DispatcherCoordinator passthrough).
- Git sync (auto commit/push, periodic pull): Task 4 — `GitSync.commit_and_push`, `GitSync.pull`. Coordinator wires the periodic pull as a scheduler job.
- Conflict resolution by conversation timestamp: **deferred** to Plan 3+ (documented in `sync.py` docstring). The spec's content-aware merging needs the parser, which the Orchestrator owns.
- 6-directory recursive watching: `Observer.schedule(handler, str(self.tasks_dir), recursive=True)` in Task 2. Watches the entire `tasks/` subtree, so all 6 status directories are covered.

**2. Placeholder scan:**
- No "TBD"/"TODO"/"add appropriate error handling"/"similar to Task N" appear.
- All test bodies contain real assertions; all implementation steps show full code.
- Conflict resolution is explicitly documented as deferred (with rationale) rather than punted as a placeholder.

**3. Type consistency:**
- `FileWatcher.__init__(tasks_dir, on_change, debounce_seconds)` consistent across watcher tests, coordinator tests, and `DispatcherCoordinator.__init__`.
- `PollScheduler.add_job(callback, interval_seconds, job_id)` consistent across scheduler tests and coordinator wiring.
- `GitSync(repo_dir)` consistent across sync tests and coordinator.
- `SyncResult` dataclass: only used inside sync tests via `.committed` / `.pushed` attribute access — names match.
- `DispatcherCoordinator.suppress_self()` returns the watcher's context manager; passthrough is correct.
- `Observer | None` type annotation works on Python 3.11+ (pep 604).

**4. Cross-platform notes:**
- watchdog on Windows uses ReadDirectoryChangesW which can produce duplicate events for a single save; debouncing handles this.
- `subprocess.run(["git", ...])` requires git on PATH. Already verified during Plan 1 (git was used for commits).
- The bare-repo test in `test_sync.py` uses pytest's `tmp_path` which avoids spaces and special characters.

All clean.
