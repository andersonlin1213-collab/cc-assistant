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


def is_pid_alive(pid: int) -> bool:
    """Return True if a process with `pid` is currently running.

    Use this instead of `os.kill(pid, 0)`. Two reasons:
      1. On Windows, `os.kill(pid, sig)` is implemented via `TerminateProcess`
         and the sig=0 idiom is platform-specific in subtle ways.
      2. `os.kill(pid, 0)` raises PermissionError when probing a process owned
         by another session, even if alive — leading to a false "stale" report
         under Windows multi-session / Task Scheduler scenarios.

    `psutil.pid_exists` handles both correctly and is already used by
    `cmd_run`'s already-running guard, so this keeps the codebase consistent.
    """
    if pid <= 0:
        return False
    import psutil
    return psutil.pid_exists(pid)


def make_stop_event(*signals: int) -> threading.Event:
    """Install handlers for the given signals that set a returned threading.Event.

    Default signals: SIGINT and SIGTERM. Use this in the daemon entry point to
    block on `event.wait()` and shut down cleanly when a signal arrives.

    The returned Event also carries a `signum` attribute (initially None,
    set to the integer signal number when a handler fires). Callers can
    inspect it after `wait()` returns to derive a conventional Unix exit
    code (`128 + signum`).

    On Windows, SIGTERM is delivered as a "best effort" — the actual termination
    semantics differ from POSIX. SIGINT (Ctrl+C) works reliably.
    """
    event = threading.Event()
    event.signum = None  # type: ignore[attr-defined]

    def _handler(signum, _frame):
        event.signum = signum  # type: ignore[attr-defined]
        event.set()

    sigs = signals or (signal.SIGINT, signal.SIGTERM)
    for s in sigs:
        try:
            signal.signal(s, _handler)
        except (OSError, ValueError):
            # Some signals are not supported on Windows or in certain contexts (threads).
            pass
    return event
