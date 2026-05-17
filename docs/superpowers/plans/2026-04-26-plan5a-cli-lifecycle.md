# Plan 5a: CLI + Lifecycle Hardening

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a usable command-line entry point (`cc-assistant run|stop|status`, plus `run --dry-run`) that turns the existing library into a daemon you can actually start, monitor, and stop. Also resolve the two important review items deferred from Plans 2 and 3c — concurrent-cycle race protection and the factory's monkey-patched callback wiring.

**Architecture:** Three small new modules glue the existing library together without changing any layer's contract. `src/lifecycle.py` is a tiny PID-file helper. `src/runner.py` builds the orchestrator + coordinator, manages the PID file, installs SIGINT/SIGTERM handlers, and blocks on a stop-event. `src/cli.py` is an argparse front-end that dispatches `run`, `stop`, and `status` subcommands. Two cross-cutting fixes round it out: an in-flight `set` + `threading.Lock` inside `Orchestrator.run_cycle` (per-path mutex), and a public `DispatcherCoordinator.set_callbacks(on_task_change, on_poll)` method that replaces the factory's previous attribute monkey-patching.

**Tech Stack:** Python 3.11+ stdlib (argparse, signal, threading), existing project dependencies. No new third-party libraries.

**Out of scope (deferred):**
- Web UI (Plan 5b).
- OpenAI / Ollama clients (Plan 5c).
- Background-service installers (NSSM on Windows, systemd unit on Linux). The CLI runs in the foreground; production deployment can wrap it later.
- Live log streaming / tail in `status`. The MVP shows the last N JSONL lines and exits.

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Modify | `src/agent/orchestrator.py` | Add `_in_flight` set + `_in_flight_lock`; guard at top of `run_cycle`; add `dry_run` flag plumbed through |
| Modify | `src/agent/tool_bridge.py` | (no change — already accepts `dry_run`) |
| Modify | `src/dispatcher/coordinator.py` | Add public `set_callbacks(on_task_change, on_poll)` method |
| Modify | `src/agent/factory.py` | Use `coordinator.set_callbacks(...)` instead of attribute access; add `build_orchestrator_only(...)` |
| Create | `src/agent/_noop_sync.py` | `_NoopSync` for non-coordinator paths (dry-run / status) |
| Create | `src/lifecycle.py` | PID file write/read/remove + signal-driven stop event |
| Create | `src/runner.py` | `start_daemon` / `stop_daemon` / `run_one_dry_cycle` |
| Create | `src/cli.py` | argparse front-end with `run`, `stop`, `status` subcommands |
| Modify | `pyproject.toml` | Add `[project.scripts]` mapping `cc-assistant` → `src.cli:main` |
| Modify | `tests/test_orchestrator.py` | Tests for in-flight lock + dry_run path (added at end) |
| Modify | `tests/test_coordinator.py` | Tests for `set_callbacks` (added at end) |
| Modify | `tests/test_orchestrator_integration.py` | Update factory call site if signature changed (no tests removed) |
| Create | `tests/test_lifecycle.py` | PID helper tests |
| Create | `tests/test_runner.py` | Daemon start/stop tests with mocked coordinator |
| Create | `tests/test_cli.py` | CLI argparse + status output tests |

---

### Task 1: Orchestrator In-Flight Lock

**Files:**
- Modify: `src/agent/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

Resolves Plan 3c review **Issue 1**: two threads (watchdog observer + APScheduler worker) could call `run_cycle` on the same path concurrently and clobber each other's writes. Add a per-path mutex.

- [ ] **Step 1: Add the failing tests at the END of `tests/test_orchestrator.py`**

Append to `tests/test_orchestrator.py`:

```python
async def test_run_cycle_skips_when_path_already_in_flight(tmp_path):
    """If the same path is already being processed, a second concurrent call returns immediately."""
    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-inflight.md"
    write_task_file(_make_task(id="100"), todo_path)

    llm = _llm_with_responses(_final_text("ack"))
    orch = _make_orchestrator_for(tmp_path, llm)

    # Pre-populate the in-flight set as if another thread were already processing.
    orch._in_flight.add(str(todo_path))

    await orch.run_cycle(todo_path)

    # LLM should NOT have been called — the second concurrent call returns early.
    llm.chat.assert_not_called()


async def test_run_cycle_releases_in_flight_on_normal_exit(tmp_path):
    """After a successful cycle, the path is removed from in_flight so the next run can proceed."""
    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-release.md"
    write_task_file(_make_task(id="100"), todo_path)

    llm = _llm_with_responses(_final_text("done"))
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(todo_path)

    assert str(todo_path) not in orch._in_flight


async def test_run_cycle_releases_in_flight_on_exception(tmp_path):
    """Even if the LLM raises, the in-flight entry is removed."""
    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-err.md"
    write_task_file(_make_task(id="100"), todo_path)

    llm = MagicMock()
    llm.chat = AsyncMock(side_effect=RuntimeError("boom"))
    orch = _make_orchestrator_for(tmp_path, llm)

    # The Orchestrator catches LLM exceptions internally; cycle should not raise.
    await orch.run_cycle(todo_path)

    assert str(todo_path) not in orch._in_flight
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_orchestrator.py -v
```

Expected: 3 new tests FAIL — `Orchestrator` has no `_in_flight` attribute.

- [ ] **Step 3: Modify `src/agent/orchestrator.py`**

In `src/agent/orchestrator.py`, make these targeted changes:

**Change 1:** Add `import threading` near the top imports (line 5 area):

```python
import logging
import threading                      # ADD THIS LINE
from contextlib import AbstractContextManager
```

**Change 2:** In `Orchestrator.__init__`, after `self.sync = sync`, add:

```python
        self.sync = sync
        # Per-path mutex: prevents concurrent cycles for the same task file
        # when watchdog and the scheduler both fire simultaneously.
        self._in_flight: set[str] = set()
        self._in_flight_lock = threading.Lock()
```

**Change 3:** Wrap the body of `run_cycle` with the in-flight guard. Replace the current method body:

**Before (the existing method body, after the `if not path.exists(): return` check):**
```python
    async def run_cycle(self, path: Path) -> None:
        if not path.exists():
            return

        current_status = self._status_from_path(path)
        if current_status in (TaskStatus.DONE, TaskStatus.REVIEW):
            return

        task = parse_task_file(path)
        # ...rest of the method...
```

**After:**
```python
    async def run_cycle(self, path: Path) -> None:
        if not path.exists():
            return

        key = str(path)
        with self._in_flight_lock:
            if key in self._in_flight:
                return  # another thread is already processing this path
            self._in_flight.add(key)

        try:
            current_status = self._status_from_path(path)
            if current_status in (TaskStatus.DONE, TaskStatus.REVIEW):
                return

            task = parse_task_file(path)
            # ...rest of the method body unchanged...
        finally:
            with self._in_flight_lock:
                self._in_flight.discard(key)
```

The whole existing run_cycle body that came after `if not path.exists(): return` becomes the contents of the `try:` block. The `finally:` releases the lock entry no matter what — including the early-return for terminal status.

**IMPORTANT:** Do NOT change any other behavior in `run_cycle`. The `try:` body is the existing code, only the indentation and the surrounding lock are new.

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_orchestrator.py -v
```

Expected: all orchestrator tests pass (the previous 10 + the 3 new = 13).

- [ ] **Step 5: Commit**

```bash
git add src/agent/orchestrator.py tests/test_orchestrator.py
git commit -m "fix(orchestrator): add per-path mutex to prevent concurrent cycle races"
```

---

### Task 2: Orchestrator Dry-Run Mode

**Files:**
- Modify: `src/agent/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

Add a `dry_run: bool = False` flag to `run_cycle`. When True: tools dispatch with `dry_run=True` (no side effects), and the orchestrator skips appending the AI reply, file move, and git commit. The dry-run report is logged to JSONL only.

- [ ] **Step 1: Append the failing test to `tests/test_orchestrator.py`**

```python
async def test_run_cycle_dry_run_does_not_mutate_state(tmp_path):
    """dry_run=True: tools get dry_run flag, no file move, no commit, no AI reply append."""
    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-dry.md"
    write_task_file(_make_task(id="100"), todo_path)

    scratch = tmp_path / "scratch.txt"

    llm = _llm_with_responses(
        _tool_use(
            "file_ops",
            {"operation": "write", "path": str(scratch), "content": "should-not-write"},
        ),
        _final_text("planned"),
    )
    sync_mock = MagicMock(commit_and_push=MagicMock(
        return_value=SimpleNamespace(committed=False, pushed=False)
    ))

    skills = tmp_path / "skills"
    if not skills.exists():
        skills.mkdir()
        (skills / "rules.md").write_text("# Rules\n", encoding="utf-8")
    logs = tmp_path / "logs"
    if not logs.exists():
        logs.mkdir()

    orch = Orchestrator(
        tasks_dir=tmp_path / "tasks",
        skills_dir=skills,
        logs_dir=logs,
        llm=llm,
        tools=[FileOpsTool()],
        suppress_self=_noop_suppress,
        sync=sync_mock,
    )

    await orch.run_cycle(todo_path, dry_run=True)

    # 1. File NOT moved out of todo/
    assert todo_path.exists()
    assert not (tasks_dir / "doing" / "100-dry.md").exists()

    # 2. Tool's dry_run prevented the actual write
    assert not scratch.exists()

    # 3. No commit
    sync_mock.commit_and_push.assert_not_called()

    # 4. No AI reply appended (conversation is unchanged)
    from src.board.parser import parse_task_file
    parsed = parse_task_file(todo_path)
    assert len(parsed.conversation) == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_orchestrator.py::test_run_cycle_dry_run_does_not_mutate_state -v
```

Expected: FAIL — `run_cycle` does not accept `dry_run` parameter.

- [ ] **Step 3: Modify `src/agent/orchestrator.py`**

**Change 1:** Update the `run_cycle` signature:

**Before:**
```python
    async def run_cycle(self, path: Path) -> None:
```

**After:**
```python
    async def run_cycle(self, path: Path, dry_run: bool = False) -> None:
```

**Change 2:** Update the call to `_run_llm_loop` to pass `dry_run`:

**Before:**
```python
        try:
            final_text, cycle_state = await self._run_llm_loop(task)
        except Exception as e:  # pylint: disable=broad-except
```

**After:**
```python
        try:
            final_text, cycle_state = await self._run_llm_loop(task, dry_run=dry_run)
        except Exception as e:  # pylint: disable=broad-except
```

**Change 3:** Update `_run_llm_loop` signature and bridge dispatch:

**Before:**
```python
    async def _run_llm_loop(self, task: Task) -> tuple[str, CycleState]:
        rules = self.rules.load()
        messages = self.context_builder.build(rules, task)
        tool_defs = self.bridge.tool_definitions()
        cycle_state = CycleState()

        final_text = ""
        for _ in range(self.MAX_TOOL_USE_ROUNDS):
            response = await self.llm.chat(messages, tools=tool_defs)
            ...
            for tu in tool_use_blocks:
                result = await self.bridge.dispatch(tu, cycle_state)
```

**After:**
```python
    async def _run_llm_loop(
        self, task: Task, dry_run: bool = False
    ) -> tuple[str, CycleState]:
        rules = self.rules.load()
        messages = self.context_builder.build(rules, task)
        tool_defs = self.bridge.tool_definitions()
        cycle_state = CycleState()

        final_text = ""
        for _ in range(self.MAX_TOOL_USE_ROUNDS):
            response = await self.llm.chat(messages, tools=tool_defs)
            ...
            for tu in tool_use_blocks:
                result = await self.bridge.dispatch(tu, cycle_state, dry_run=dry_run)
```

(Only two lines change in `_run_llm_loop`: the signature, and the `bridge.dispatch` call.)

**Change 4:** Short-circuit the mutation block in `run_cycle` when `dry_run=True`. Find this section:

**Before:**
```python
        if llm_failed:
            next_status = current_status
        else:
            next_status = self._decide_next_status(current_status, task, cycle_state)

        # Mutate filesystem inside suppress_self to avoid retriggering ourselves.
        new_path = path
        try:
            with self.suppress_self():
                self._append_ai_reply(path, final_text)
                if next_status != current_status:
                    new_path = self.manager.move_task(path, next_status)
                self.sync.commit_and_push(
                    f"agent: {task.id} {current_status.value}->{next_status.value}"
                )
        except Exception as e:  # pylint: disable=broad-except
            self.logger.log(LogEntry(
                task_id=task.id, action="cycle_error",
                detail=f"fs_mutation_failed: {e}", status="error",
            ))
            raise

        self.logger.log(LogEntry(
            task_id=task.id, action="cycle_complete",
            detail=f"final_status={next_status.value} path={new_path}",
        ))
```

**After:**
```python
        if llm_failed:
            next_status = current_status
        else:
            next_status = self._decide_next_status(current_status, task, cycle_state)

        if dry_run:
            self.logger.log(LogEntry(
                task_id=task.id, action="cycle_dry_run_complete",
                detail=(
                    f"would_move={current_status.value}->{next_status.value} "
                    f"would_append=[{final_text[:80]}]"
                ),
            ))
            return

        # Mutate filesystem inside suppress_self to avoid retriggering ourselves.
        new_path = path
        try:
            with self.suppress_self():
                self._append_ai_reply(path, final_text)
                if next_status != current_status:
                    new_path = self.manager.move_task(path, next_status)
                self.sync.commit_and_push(
                    f"agent: {task.id} {current_status.value}->{next_status.value}"
                )
        except Exception as e:  # pylint: disable=broad-except
            self.logger.log(LogEntry(
                task_id=task.id, action="cycle_error",
                detail=f"fs_mutation_failed: {e}", status="error",
            ))
            raise

        self.logger.log(LogEntry(
            task_id=task.id, action="cycle_complete",
            detail=f"final_status={next_status.value} path={new_path}",
        ))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_orchestrator.py -v
```

Expected: all 14 tests pass (13 previous + 1 new).

- [ ] **Step 5: Commit**

```bash
git add src/agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): add dry_run mode that skips writes, moves, and commits"
```

---

### Task 3: DispatcherCoordinator.set_callbacks()

**Files:**
- Modify: `src/dispatcher/coordinator.py`
- Modify: `tests/test_coordinator.py`

Resolves Plan 3c review **Issue 3**: factory currently does `coordinator.watcher.on_change = ...` and `coordinator._on_poll = ...`. Replace with a public `set_callbacks(on_task_change, on_poll)` method.

- [ ] **Step 1: Append the failing test to `tests/test_coordinator.py`**

```python
def test_set_callbacks_updates_watcher_and_poll(tmp_path):
    """set_callbacks() replaces both the watcher's on_change and the poll callback."""
    from unittest.mock import MagicMock

    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    coord = DispatcherCoordinator(
        tasks_dir=tasks_dir,
        repo_dir=tmp_path,
        on_task_change=lambda p: None,
        on_poll=lambda: None,
    )

    new_change = MagicMock()
    new_poll = MagicMock()
    coord.set_callbacks(on_task_change=new_change, on_poll=new_poll)

    # Watcher's on_change is the new callable
    assert coord.watcher.on_change is new_change
    # Poll callback (used when scheduler.add_job runs) is the new callable
    assert coord._on_poll is new_poll
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_coordinator.py::test_set_callbacks_updates_watcher_and_poll -v
```

Expected: FAIL — `DispatcherCoordinator` has no `set_callbacks` method.

- [ ] **Step 3: Modify `src/dispatcher/coordinator.py`**

Add the new method to the `DispatcherCoordinator` class. Insert after `__init__` and before `start`:

```python
    def set_callbacks(
        self,
        on_task_change: Callable[[Path], None],
        on_poll: Callable[[], None],
    ) -> None:
        """Replace both the file-change callback and the poll callback.

        Used by the factory after orchestrator construction. The watcher's
        on_change is updated directly (it is checked at every event); the poll
        callback is stored and read whenever start() schedules its job.
        """
        self.watcher.on_change = on_task_change
        self._on_poll = on_poll
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_coordinator.py -v
```

Expected: 5 passed (4 previous + 1 new).

- [ ] **Step 5: Commit**

```bash
git add src/dispatcher/coordinator.py tests/test_coordinator.py
git commit -m "refactor(coordinator): add public set_callbacks method (replaces monkey-patching)"
```

---

### Task 4: NoopSync + factory `build_orchestrator_only`

**Files:**
- Create: `src/agent/_noop_sync.py`
- Modify: `src/agent/factory.py`
- Modify: `tests/test_orchestrator_integration.py`

A `_NoopSync` lets us build an Orchestrator without a coordinator — needed for `cc-assistant run --dry-run` and `cc-assistant status`. The factory gets a sibling `build_orchestrator_only(...)` for these one-shot paths and is updated to use `set_callbacks` from Task 3.

- [ ] **Step 1: Append a failing test to `tests/test_orchestrator_integration.py`**

```python
def test_build_orchestrator_only_returns_usable_orchestrator(tmp_path):
    """build_orchestrator_only constructs an Orchestrator without a coordinator."""
    from unittest.mock import MagicMock

    from src.agent.factory import build_orchestrator_only

    tasks_dir, skills_dir, logs_dir = _make_kanban(tmp_path)

    orch = build_orchestrator_only(
        tasks_dir=tasks_dir,
        skills_dir=skills_dir,
        logs_dir=logs_dir,
        llm=MagicMock(),
    )

    assert orch is not None
    # NoopSync.commit_and_push is callable and returns a SyncResult-like object
    result = orch.sync.commit_and_push("test")
    assert result.committed is False
    assert result.pushed is False
    # NoopSync.pull is callable and returns False
    assert orch.sync.pull() is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_orchestrator_integration.py::test_build_orchestrator_only_returns_usable_orchestrator -v
```

Expected: FAIL — cannot import `build_orchestrator_only`.

- [ ] **Step 3: Write `src/agent/_noop_sync.py`**

```python
from __future__ import annotations

from src.dispatcher.sync import SyncResult


class NoopSync:
    """A drop-in replacement for GitSync that performs no operations.

    Used by the dry-run / status code paths where there is no coordinator and
    no real repository sync should occur. Has the same `commit_and_push` and
    `pull` interface as `GitSync` so callers don't need to special-case it.
    """

    def commit_and_push(self, message: str) -> SyncResult:  # noqa: ARG002 — kept for parity
        return SyncResult(committed=False, pushed=False)

    def pull(self) -> bool:
        return False
```

- [ ] **Step 4: Modify `src/agent/factory.py` to use set_callbacks and add build_orchestrator_only**

Replace the contents of `src/agent/factory.py` entirely:

```python
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from src.agent._noop_sync import NoopSync
from src.agent.llm.base import LLMClient
from src.agent.orchestrator import Orchestrator
from src.dispatcher.coordinator import DispatcherCoordinator
from src.tools import ALL_TOOLS


def build_orchestrator_and_coordinator(
    tasks_dir: Path,
    skills_dir: Path,
    logs_dir: Path,
    repo_dir: Path,
    llm: LLMClient,
    debounce_seconds: float = DispatcherCoordinator.DEFAULT_DEBOUNCE_SECONDS,
    poll_interval_seconds: float = DispatcherCoordinator.DEFAULT_POLL_INTERVAL_SECONDS,
    git_pull_interval_seconds: float = DispatcherCoordinator.DEFAULT_GIT_PULL_INTERVAL_SECONDS,
    tools: Optional[list] = None,
) -> tuple[Orchestrator, DispatcherCoordinator]:
    """Wire Orchestrator + DispatcherCoordinator into a runnable pair.

    Two-step construction:
      1. Build the coordinator with placeholder callbacks (Orchestrator depends on
         coordinator.suppress_self and coordinator.sync).
      2. Build the orchestrator using those.
      3. Re-wire the coordinator's callbacks to real orchestrator methods via the
         public `set_callbacks` API.
    """
    if tools is None:
        tools = [cls() for cls in ALL_TOOLS]

    coordinator = DispatcherCoordinator(
        tasks_dir=tasks_dir,
        repo_dir=repo_dir,
        on_task_change=lambda p: None,
        on_poll=lambda: None,
        debounce_seconds=debounce_seconds,
        poll_interval_seconds=poll_interval_seconds,
        git_pull_interval_seconds=git_pull_interval_seconds,
    )

    orchestrator = Orchestrator(
        tasks_dir=tasks_dir,
        skills_dir=skills_dir,
        logs_dir=logs_dir,
        llm=llm,
        tools=tools,
        suppress_self=coordinator.suppress_self,
        sync=coordinator.sync,
    )

    coordinator.set_callbacks(
        on_task_change=lambda p: _run_async(orchestrator.run_cycle(p)),
        on_poll=lambda: _run_async(orchestrator.on_poll()),
    )

    return orchestrator, coordinator


def build_orchestrator_only(
    tasks_dir: Path,
    skills_dir: Path,
    logs_dir: Path,
    llm: LLMClient,
    tools: Optional[list] = None,
) -> Orchestrator:
    """Build an Orchestrator without a coordinator.

    Used for one-shot paths (cc-assistant run --dry-run, cc-assistant status)
    that do not need watchdog/scheduler/git sync. `suppress_self` is a no-op
    context manager; `sync` is a NoopSync.
    """
    if tools is None:
        tools = [cls() for cls in ALL_TOOLS]

    return Orchestrator(
        tasks_dir=tasks_dir,
        skills_dir=skills_dir,
        logs_dir=logs_dir,
        llm=llm,
        tools=tools,
        suppress_self=_noop_suppress,
        sync=NoopSync(),
    )


@contextmanager
def _noop_suppress() -> Iterator[None]:
    yield


def _run_async(coro) -> None:
    """Run an async coroutine to completion in a fresh event loop.

    The watcher's callback runs in the watchdog observer thread (sync); the
    scheduler's callback runs in an APScheduler worker thread (sync). We need
    to drive an async coroutine to completion from sync code, which means a
    fresh event loop per invocation. This is fine for the cycle-per-event
    pattern (Completion Promise) — no ambient loop is shared across cycles.
    """
    import asyncio

    asyncio.run(coro)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/test_orchestrator_integration.py -v
```

Expected: 2 passed (the original integration test + the new `build_orchestrator_only` test).

- [ ] **Step 6: Run full suite to ensure no regressions**

```bash
uv run pytest -v
```

Expected: 178 passed, 1 skipped (was 176 + 1 + 2 new from Tasks 1, 2, 4 after subtracting the in-flight + dry_run tests already counted).
Actual final number is whatever shows; the important thing is **no failures**.

- [ ] **Step 7: Commit**

```bash
git add src/agent/_noop_sync.py src/agent/factory.py tests/test_orchestrator_integration.py
git commit -m "feat(factory): add build_orchestrator_only and switch to set_callbacks"
```

---

### Task 5: Lifecycle (PID file)

**Files:**
- Create: `src/lifecycle.py`
- Create: `tests/test_lifecycle.py`

PID-file helpers used by `cc-assistant run/stop/status`. Plus a small `make_stop_event(*signals)` helper that wires `signal.signal` to a `threading.Event` for clean shutdown.

- [ ] **Step 1: Write the failing tests**

Write `tests/test_lifecycle.py`:

```python
import os
from pathlib import Path

from src.lifecycle import read_pid, remove_pid, write_pid


def test_write_and_read_pid(tmp_path):
    pid_path = tmp_path / "agent.pid"
    write_pid(pid_path, 12345)

    assert pid_path.exists()
    assert read_pid(pid_path) == 12345


def test_read_missing_pid_returns_none(tmp_path):
    assert read_pid(tmp_path / "nope.pid") is None


def test_read_garbage_pid_returns_none(tmp_path):
    pid_path = tmp_path / "agent.pid"
    pid_path.write_text("not a number\n", encoding="utf-8")

    assert read_pid(pid_path) is None


def test_remove_pid_removes_file(tmp_path):
    pid_path = tmp_path / "agent.pid"
    write_pid(pid_path, 100)

    remove_pid(pid_path)

    assert not pid_path.exists()


def test_remove_pid_missing_is_noop(tmp_path):
    """Removing a non-existent PID file does not raise."""
    remove_pid(tmp_path / "missing.pid")  # should not raise


def test_write_pid_creates_parent_dirs(tmp_path):
    """write_pid creates the parent directory if needed."""
    pid_path = tmp_path / "deep" / "logs" / "agent.pid"
    write_pid(pid_path, 999)

    assert pid_path.exists()
    assert read_pid(pid_path) == 999


def test_write_pid_uses_current_process_when_no_pid_arg(tmp_path):
    """write_pid() with no pid arg defaults to os.getpid()."""
    pid_path = tmp_path / "agent.pid"
    write_pid(pid_path)

    assert read_pid(pid_path) == os.getpid()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_lifecycle.py -v
```

Expected: FAIL — cannot import from `src.lifecycle`.

- [ ] **Step 3: Write implementation**

Write `src/lifecycle.py`:

```python
from __future__ import annotations

import os
import signal
import threading
from pathlib import Path
from typing import Optional


def write_pid(path: Path, pid: Optional[int] = None) -> None:
    """Write the PID to `path`, creating parent directories as needed.

    Defaults to the current process PID. Overwrites any existing file.
    """
    if pid is None:
        pid = os.getpid()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\n", encoding="utf-8")


def read_pid(path: Path) -> Optional[int]:
    """Return the PID stored at `path`, or None if the file is missing or unparseable."""
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8").strip()
        return int(content)
    except (OSError, ValueError):
        return None


def remove_pid(path: Path) -> None:
    """Remove the PID file. No-op if it does not exist."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def make_stop_event(*signals: int) -> threading.Event:
    """Install handlers for the given signals that set a returned threading.Event.

    Default signals: SIGINT and SIGTERM. Use this in the daemon entry point to
    block on `event.wait()` and shut down cleanly when a signal arrives.

    On Windows, SIGTERM is delivered as a "best effort" — the actual termination
    semantics differ from POSIX. SIGINT (Ctrl+C) works reliably.
    """
    event = threading.Event()

    def _handler(_signum, _frame):
        event.set()

    sigs = signals or (signal.SIGINT, signal.SIGTERM)
    for s in sigs:
        try:
            signal.signal(s, _handler)
        except (OSError, ValueError):
            # Some signals are not supported on Windows or in certain contexts (threads).
            pass
    return event
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_lifecycle.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/lifecycle.py tests/test_lifecycle.py
git commit -m "feat(lifecycle): add PID file helpers and signal-driven stop event"
```

---

### Task 6: Runner

**Files:**
- Create: `src/runner.py`
- Create: `tests/test_runner.py`

The runner glues the factory + lifecycle together. `start_daemon(...)` builds the orchestrator + coordinator, writes the PID file, returns a `(orchestrator, coordinator, stop_callable)` triple. `run_one_dry_cycle(...)` is the one-shot dry-run path. `stop_daemon` reads the PID file and signals the running daemon.

- [ ] **Step 1: Write the failing tests**

Write `tests/test_runner.py`:

```python
import os
import signal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.runner import (
    DaemonHandle,
    run_one_dry_cycle,
    start_daemon,
    stop_daemon_by_pid_file,
)


def _make_kanban(tmp_path: Path) -> tuple[Path, Path, Path]:
    tasks = tmp_path / "tasks"
    for s in ["backlog", "todo", "doing", "blocked", "review", "done"]:
        (tasks / s).mkdir(parents=True)
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "rules.md").write_text("# Rules\n", encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()
    return tasks, skills, logs


def test_start_daemon_writes_pid_and_returns_handle(tmp_path):
    tasks, skills, logs = _make_kanban(tmp_path)
    pid_path = logs / "agent.pid"

    handle = start_daemon(
        tasks_dir=tasks,
        skills_dir=skills,
        logs_dir=logs,
        repo_dir=tmp_path,
        llm=MagicMock(),
        pid_file=pid_path,
        # Don't actually start the coordinator in this unit test — that's tested elsewhere
        # via the integration test. Pass start=False to skip.
        start=False,
    )

    assert isinstance(handle, DaemonHandle)
    assert pid_path.exists()
    assert int(pid_path.read_text().strip()) == os.getpid()
    # Calling stop is idempotent and safe even when start=False
    handle.stop()
    assert not pid_path.exists()


def test_stop_daemon_by_pid_file_sends_signal(tmp_path):
    """stop_daemon_by_pid_file reads the PID and calls os.kill with SIGTERM."""
    pid_path = tmp_path / "agent.pid"
    pid_path.write_text("99999\n", encoding="utf-8")

    with patch("src.runner.os.kill") as mock_kill:
        result = stop_daemon_by_pid_file(pid_path)

    assert result is True
    mock_kill.assert_called_once()
    args, _ = mock_kill.call_args
    assert args[0] == 99999
    assert args[1] in (signal.SIGTERM, signal.SIGINT)


def test_stop_daemon_by_pid_file_returns_false_when_no_pid(tmp_path):
    """If no PID file exists, stop returns False without raising."""
    result = stop_daemon_by_pid_file(tmp_path / "missing.pid")
    assert result is False


def test_stop_daemon_by_pid_file_returns_false_when_process_gone(tmp_path):
    """If the PID exists but the process no longer does, stop returns False."""
    pid_path = tmp_path / "agent.pid"
    pid_path.write_text("99999\n", encoding="utf-8")

    with patch("src.runner.os.kill", side_effect=ProcessLookupError):
        result = stop_daemon_by_pid_file(pid_path)

    assert result is False


async def test_run_one_dry_cycle_invokes_orchestrator_with_dry_run(tmp_path):
    """run_one_dry_cycle builds an orchestrator-only and calls run_cycle(path, dry_run=True)."""
    tasks, skills, logs = _make_kanban(tmp_path)

    # Create a real task file so run_cycle does not early-return on missing file.
    from src.board.writer import write_task_file
    from src.models import Priority, Task
    from datetime import datetime

    task = Task(
        id="200",
        title="dry-test",
        priority=Priority.P1,
        created=datetime(2026, 4, 26, 14, 0),
        updated=datetime(2026, 4, 26, 14, 0),
    )
    target_path = tasks / "todo" / "200-dry-test.md"
    write_task_file(task, target_path)

    # Mock LLM to return a single end_turn response
    from src.agent.llm.types import LLMResponse, TextBlock, Usage
    llm = MagicMock()
    llm.chat = AsyncMock(return_value=LLMResponse(
        content=[TextBlock(text="dry plan")],
        stop_reason="end_turn",
        usage=Usage(),
        model="claude-sonnet-4-6",
    ))

    await run_one_dry_cycle(
        tasks_dir=tasks,
        skills_dir=skills,
        logs_dir=logs,
        llm=llm,
        target_path=target_path,
    )

    # File should NOT have been moved (dry-run)
    assert target_path.exists()
    # LLM was called once
    llm.chat.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_runner.py -v
```

Expected: FAIL — cannot import from `src.runner`.

- [ ] **Step 3: Write implementation**

Write `src/runner.py`:

```python
from __future__ import annotations

import os
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.agent.factory import (
    build_orchestrator_and_coordinator,
    build_orchestrator_only,
)
from src.agent.llm.base import LLMClient
from src.agent.orchestrator import Orchestrator
from src.dispatcher.coordinator import DispatcherCoordinator
from src.lifecycle import read_pid, remove_pid, write_pid


@dataclass
class DaemonHandle:
    """Returned by start_daemon. Call `stop()` to shut down cleanly."""

    orchestrator: Orchestrator
    coordinator: DispatcherCoordinator
    pid_file: Path

    def stop(self) -> None:
        try:
            self.coordinator.stop()
        finally:
            remove_pid(self.pid_file)


def start_daemon(
    tasks_dir: Path,
    skills_dir: Path,
    logs_dir: Path,
    repo_dir: Path,
    llm: LLMClient,
    pid_file: Path,
    start: bool = True,
) -> DaemonHandle:
    """Build orchestrator + coordinator, write the PID file, optionally start.

    `start=True` (default) calls coordinator.start(), beginning watchdog +
    scheduler immediately. `start=False` is for tests that want to inspect the
    handle without firing real timers.
    """
    orchestrator, coordinator = build_orchestrator_and_coordinator(
        tasks_dir=tasks_dir,
        skills_dir=skills_dir,
        logs_dir=logs_dir,
        repo_dir=repo_dir,
        llm=llm,
    )

    write_pid(pid_file)

    if start:
        coordinator.start()

    return DaemonHandle(
        orchestrator=orchestrator,
        coordinator=coordinator,
        pid_file=pid_file,
    )


def stop_daemon_by_pid_file(pid_file: Path) -> bool:
    """Read the PID file and send SIGTERM to the process.

    Returns True if a signal was sent successfully.
    Returns False if the PID file is missing, unparseable, or the process is gone.
    """
    pid = read_pid(pid_file)
    if pid is None:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except ProcessLookupError:
        # Process already gone — clean up stale PID file
        remove_pid(pid_file)
        return False
    except OSError:
        return False


async def run_one_dry_cycle(
    tasks_dir: Path,
    skills_dir: Path,
    logs_dir: Path,
    llm: LLMClient,
    target_path: Optional[Path] = None,
) -> None:
    """One-shot dry-run: build an orchestrator-only and call run_cycle(dry_run=True).

    If `target_path` is given, dry-run that single task. Otherwise, dry-run every
    active task (todo/ + doing/) once.
    """
    orchestrator = build_orchestrator_only(
        tasks_dir=tasks_dir,
        skills_dir=skills_dir,
        logs_dir=logs_dir,
        llm=llm,
    )

    if target_path is not None:
        await orchestrator.run_cycle(target_path, dry_run=True)
        return

    from src.models import TaskStatus

    for status in (TaskStatus.TODO, TaskStatus.DOING):
        for path in orchestrator.manager.list_tasks(status):
            await orchestrator.run_cycle(path, dry_run=True)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_runner.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/runner.py tests/test_runner.py
git commit -m "feat(runner): add start_daemon, stop_daemon_by_pid_file, run_one_dry_cycle"
```

---

### Task 7: CLI

**Files:**
- Create: `src/cli.py`
- Create: `tests/test_cli.py`

argparse front-end. Subcommands: `run`, `stop`, `status`. `run` takes `--dry-run [PATH]`. `status` reads PID + active task counts + last 10 lines of `agent.jsonl`.

- [ ] **Step 1: Write the failing tests**

Write `tests/test_cli.py`:

```python
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.cli import build_parser, cmd_status


def test_parser_has_run_subcommand():
    parser = build_parser()
    args = parser.parse_args(["run"])
    assert args.command == "run"
    assert args.dry_run is False


def test_parser_run_dry_run_flag():
    parser = build_parser()
    args = parser.parse_args(["run", "--dry-run"])
    assert args.command == "run"
    assert args.dry_run is True
    assert args.target is None


def test_parser_run_dry_run_with_target(tmp_path):
    parser = build_parser()
    args = parser.parse_args(["run", "--dry-run", "tasks/todo/001-x.md"])
    assert args.dry_run is True
    assert args.target == "tasks/todo/001-x.md"


def test_parser_has_stop_subcommand():
    parser = build_parser()
    args = parser.parse_args(["stop"])
    assert args.command == "stop"


def test_parser_has_status_subcommand():
    parser = build_parser()
    args = parser.parse_args(["status"])
    assert args.command == "status"


def test_status_reports_not_running_when_no_pid_file(tmp_path, capsys):
    """`cc-assistant status` prints 'not running' when no PID file exists."""
    cmd_status(
        pid_file=tmp_path / "agent.pid",
        tasks_dir=tmp_path / "tasks",
        logs_dir=tmp_path / "logs",
    )

    captured = capsys.readouterr()
    assert "not running" in captured.out.lower()


def test_status_reports_running_with_pid(tmp_path, capsys):
    """When PID file exists and process exists, status prints PID + active counts."""
    pid_file = tmp_path / "agent.pid"
    pid_file.write_text("12345\n", encoding="utf-8")

    tasks_dir = tmp_path / "tasks"
    for s in ["backlog", "todo", "doing", "blocked", "review", "done"]:
        (tasks_dir / s).mkdir(parents=True)
    # Add a couple of fake task files
    (tasks_dir / "todo" / "1.md").write_text("---\nid: \"1\"\n---\n", encoding="utf-8")
    (tasks_dir / "doing" / "2.md").write_text("---\nid: \"2\"\n---\n", encoding="utf-8")
    (tasks_dir / "doing" / "3.md").write_text("---\nid: \"3\"\n---\n", encoding="utf-8")

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "agent.jsonl").write_text(
        json.dumps({"ts": "2026-04-26T10:00", "action": "startup", "task_id": "_system",
                    "detail": "agent up", "duration_ms": 0, "status": "success"}) + "\n",
        encoding="utf-8",
    )

    with patch("src.cli.os.kill") as mock_kill:
        # os.kill(pid, 0) is the standard "is the process alive?" check.
        mock_kill.return_value = None
        cmd_status(pid_file=pid_file, tasks_dir=tasks_dir, logs_dir=logs_dir)

    captured = capsys.readouterr()
    assert "12345" in captured.out
    assert "todo" in captured.out
    # Active counts shown
    assert "1" in captured.out  # 1 todo
    assert "2" in captured.out  # 2 doing
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_cli.py -v
```

Expected: FAIL — cannot import from `src.cli`.

- [ ] **Step 3: Write implementation**

Write `src/cli.py`:

```python
from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import Optional

from src.config import config
from src.lifecycle import make_stop_event, read_pid


def build_parser() -> argparse.ArgumentParser:
    """Build the cc-assistant CLI argparse parser."""
    parser = argparse.ArgumentParser(
        prog="cc-assistant",
        description="Local AI Task Automation Agent — kanban-driven daemon.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Start the agent daemon (foreground).")
    p_run.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate one cycle (or all active tasks) without writing or committing.",
    )
    p_run.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Path to a single task file (used with --dry-run). Default: all active tasks.",
    )

    sub.add_parser("stop", help="Send SIGTERM to the running agent (reads logs/agent.pid).")
    sub.add_parser("status", help="Print agent status: PID, active task counts, recent log lines.")

    return parser


def cmd_run(dry_run: bool, target: Optional[str]) -> int:
    from src.agent.llm.factory import get_llm_client

    llm = get_llm_client()
    pid_file = config.logs_dir / "agent.pid"

    if dry_run:
        from src.runner import run_one_dry_cycle

        target_path = Path(target) if target else None
        asyncio.run(run_one_dry_cycle(
            tasks_dir=config.tasks_dir,
            skills_dir=config.skills_dir,
            logs_dir=config.logs_dir,
            llm=llm,
            target_path=target_path,
        ))
        print("dry-run complete (see logs/agent.jsonl for details)")
        return 0

    from src.runner import start_daemon

    handle = start_daemon(
        tasks_dir=config.tasks_dir,
        skills_dir=config.skills_dir,
        logs_dir=config.logs_dir,
        repo_dir=Path("."),
        llm=llm,
        pid_file=pid_file,
    )
    print(f"cc-assistant running (pid={os.getpid()}). Ctrl-C to stop.")

    stop_event = make_stop_event()
    try:
        stop_event.wait()
    finally:
        handle.stop()

    print("cc-assistant stopped.")
    return 0


def cmd_stop() -> int:
    from src.runner import stop_daemon_by_pid_file

    pid_file = config.logs_dir / "agent.pid"
    if stop_daemon_by_pid_file(pid_file):
        print(f"signal sent to pid {read_pid(pid_file)}")
        return 0
    print("no running daemon found")
    return 1


def cmd_status(
    pid_file: Path,
    tasks_dir: Path,
    logs_dir: Path,
) -> int:
    pid = read_pid(pid_file)
    if pid is None:
        print("cc-assistant: not running (no PID file)")
        return 0

    # Probe whether the process is alive: os.kill(pid, 0) raises if not.
    alive = True
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError, OSError):
        alive = False

    if not alive:
        print(f"cc-assistant: stale PID file at {pid_file} (pid {pid} not running)")
        return 0

    print(f"cc-assistant: running (pid={pid})")
    print()
    print("Active tasks by column:")
    column_names = ["backlog", "todo", "doing", "blocked", "review"]
    for name in column_names:
        d = tasks_dir / name
        count = sum(1 for _ in d.glob("*.md")) if d.exists() else 0
        print(f"  {name:<10} {count}")

    # Recent system log lines
    agent_log = logs_dir / "agent.jsonl"
    if agent_log.exists():
        print()
        print("Recent agent log:")
        lines = agent_log.read_text(encoding="utf-8").strip().split("\n")
        for line in lines[-10:]:
            print(f"  {line}")

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        return cmd_run(dry_run=args.dry_run, target=args.target)
    if args.command == "stop":
        return cmd_stop()
    if args.command == "status":
        return cmd_status(
            pid_file=config.logs_dir / "agent.pid",
            tasks_dir=config.tasks_dir,
            logs_dir=config.logs_dir,
        )
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_cli.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/cli.py tests/test_cli.py
git commit -m "feat(cli): add cc-assistant run/stop/status entry point with --dry-run"
```

---

### Task 8: Entry Point + Smoke Test

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/test_cli_entrypoint.py`

Wire the script entry point so `uv run cc-assistant` and `cc-assistant` (after `pip install`) both work.

- [ ] **Step 1: Add `[project.scripts]` section to `pyproject.toml`**

After the existing `[project.optional-dependencies]` section in `pyproject.toml`, add:

```toml
[project.scripts]
cc-assistant = "src.cli:main"
```

The full ordering of `pyproject.toml` after this change is `[project]` → `[project.optional-dependencies]` → `[project.scripts]` → `[tool.pytest.ini_options]`.

- [ ] **Step 2: Re-install the project in development mode so the script is picked up**

```bash
uv sync --all-extras
```

- [ ] **Step 3: Smoke-test the entry point**

```bash
uv run cc-assistant --help
```

Expected: argparse usage banner with the three subcommands listed.

```bash
uv run cc-assistant status
```

Expected: either "not running (no PID file)" (fresh project) or a status report. No traceback.

- [ ] **Step 4: Write the smoke test**

Write `tests/test_cli_entrypoint.py`:

```python
"""Smoke test that verifies the cc-assistant entry point is wired correctly."""

import subprocess


def test_cli_help_runs():
    """`uv run cc-assistant --help` exits 0 and prints subcommand names."""
    result = subprocess.run(
        ["uv", "run", "cc-assistant", "--help"],
        capture_output=True,
        text=True,
        cwd=".",
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "run" in result.stdout
    assert "stop" in result.stdout
    assert "status" in result.stdout


def test_cli_status_runs_without_error():
    """`uv run cc-assistant status` exits 0 even when no daemon is running."""
    result = subprocess.run(
        ["uv", "run", "cc-assistant", "status"],
        capture_output=True,
        text=True,
        cwd=".",
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "cc-assistant" in result.stdout.lower()
```

- [ ] **Step 5: Run the smoke test**

```bash
uv run pytest tests/test_cli_entrypoint.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Run the full suite**

```bash
uv run pytest -v
```

Expected: cumulative count from all prior plans + Plan 5a tests. After Plans 1+2+3+4+5a:
- 176 (after Plan 4) + 3 (orchestrator new) + 1 (orchestrator dry_run) + 1 (coordinator) + 1 (factory) + 7 (lifecycle) + 5 (runner) + 7 (cli) + 2 (cli entrypoint) = **203 passed, 1 skipped** (approximately).

The exact count depends on whether subagents added extra assertions in earlier tasks; the important thing is **no failures**.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock tests/test_cli_entrypoint.py
git commit -m "feat: wire cc-assistant console entry point and smoke-test it"
```

---

## Self-Review

**1. Spec coverage (CLI / lifecycle portion of Layer 4 + 5):**
- `cc-assistant run` (foreground daemon): Tasks 6 + 7 (`start_daemon` + `cmd_run`).
- `cc-assistant run --dry-run [target]`: Task 2 (orchestrator dry_run mode) + Task 6 (`run_one_dry_cycle`) + Task 7 (`cmd_run` dispatch).
- `cc-assistant stop`: Tasks 6 (`stop_daemon_by_pid_file`) + 7 (`cmd_stop`).
- `cc-assistant status`: Task 7 (`cmd_status`).
- PID file management: Task 5 (`src/lifecycle.py`).
- Signal handling: Task 5 (`make_stop_event`) + Task 7 (`cmd_run`).
- Per-path mutex (Plan 3c review Issue 1): Task 1.
- `set_callbacks()` refactor (Plan 3c review Issue 3): Task 3.
- `[project.scripts]` entry point: Task 8.

**2. Placeholder scan:**
- No "TBD" / "TODO" / "fill in details" / "similar to Task N".
- Test bodies have real assertions.
- Implementation steps include full code or precise change instructions ("Before/After" diffs).
- The "cumulative count" prediction in Task 8 Step 6 acknowledges it is approximate — that's documentation, not a placeholder.

**3. Type consistency:**
- `Orchestrator.run_cycle(self, path: Path, dry_run: bool = False)` consistent in orchestrator.py and all callers (factory, runner, integration test).
- `DispatcherCoordinator.set_callbacks(on_task_change, on_poll)` consistent in coordinator.py, factory.py, and the new test.
- `DaemonHandle` dataclass with `orchestrator`, `coordinator`, `pid_file` consistent in runner.py and tests.
- `cmd_status(pid_file, tasks_dir, logs_dir)` signature consistent between the test and `cli.main`.
- `NoopSync.commit_and_push` returns `SyncResult` (the existing dataclass from `src/dispatcher/sync.py`); tests assert on `.committed` and `.pushed` attributes.

**4. Cross-platform:**
- Signal handling on Windows: SIGTERM behaves differently than POSIX. `make_stop_event` wraps `signal.signal` in try/except so unsupported signals don't crash.
- Path handling via `pathlib.Path` throughout.
- `os.kill(pid, 0)` for liveness probing works on both POSIX and Windows.

**5. Backward compatibility:**
- `Orchestrator.run_cycle(path)` still works (the `dry_run` parameter has a default of False).
- `DispatcherCoordinator.set_callbacks` is purely additive — the original constructor still accepts `on_task_change` and `on_poll`.
- The factory's `build_orchestrator_and_coordinator` keeps the same signature; only the internal wiring changes.
- The factory's `_run_async` helper moved out of `factory.py` (it's still defined inside `factory.py`), so the existing integration test still works.

All clean.
