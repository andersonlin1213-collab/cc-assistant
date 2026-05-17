from __future__ import annotations

import asyncio
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
from src.logging.structured import rotate_old_logs


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
    llm: LLMClient,
    pid_file: Path,
    start: bool = True,
    replay_pending: bool = True,
    catchup_poll: bool = True,
) -> DaemonHandle:
    """Build orchestrator + coordinator, write the PID file, optionally start.

    `start=True` (default) calls coordinator.start(), beginning watchdog +
    scheduler immediately. `start=False` is for tests that want to inspect the
    handle without firing real timers.

    `replay_pending=True` (default) catches up any task whose `intent` was
    set while the daemon was offline (e.g. user changed intent on phone via
    Obsidian Sync). Runs once before the coordinator starts so the watcher
    doesn't race with the replay's own writes.

    `catchup_poll=True` (default) runs `on_poll()` once at startup, scanning
    todo/+doing/ and firing `run_cycle` per task. This closes the second
    daemon-outage gap that `replay_pending_intents` doesn't cover: file
    saves that landed while the daemon was down. Without this, the watcher
    only sees *future* events and the user has to wait up to
    `poll_interval_minutes` (default 30) for the scheduled poll to notice.
    Observed in practice on 5/3 — daemon died 14h, user's mid-day edits to
    002/003/007 sat in `cycle_skipped` until manual `touch` woke each.
    Cycles whose tasks are in placeholder-pending state cost nothing
    (run_cycle short-circuits before the LLM call), so the worst case is
    a parse + status-check pass over every active task at boot.
    """
    # Rotate stale per-task log files into logs/archive/<YYYY-MM>/ before
    # the daemon starts emitting new entries. Inactive task histories stay
    # accessible (just one directory deeper) and the working `logs/` dir
    # doesn't grow unbounded across months of dogfood. Return value is
    # advisory only — print to stderr if any moved so the operator sees it.
    rotated = rotate_old_logs(logs_dir)
    if rotated > 0:
        print(
            f"[start_daemon] archived {rotated} stale log file(s) under "
            f"{logs_dir}/archive/",
            flush=True,
        )

    orchestrator, coordinator = build_orchestrator_and_coordinator(
        tasks_dir=tasks_dir,
        skills_dir=skills_dir,
        logs_dir=logs_dir,
        llm=llm,
    )

    write_pid(pid_file)

    if replay_pending:
        asyncio.run(orchestrator.replay_pending_intents())

    if catchup_poll:
        asyncio.run(orchestrator.on_poll())

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

    A stale PID (process no longer exists) always cleans up the PID file. On
    Windows, os.kill on a vanished PID raises OSError(errno=22, winerror=87
    ERROR_INVALID_PARAMETER) rather than ProcessLookupError, so we treat both
    the same. The trade-off: a Unix PermissionError on a process we don't own
    would also be treated as stale; in practice the daemon is started by the
    same user that stops it, so this case is irrelevant.
    """
    pid = read_pid(pid_file)
    if pid is None:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except (ProcessLookupError, OSError):
        remove_pid(pid_file)
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
