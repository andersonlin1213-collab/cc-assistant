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
        on_task_change=lambda p: seen.append(p),
        on_poll=lambda: None,
        debounce_seconds=0.1,
        poll_interval_seconds=3600,  # effectively disabled for this test
    )
    (tasks_dir / "todo").mkdir()
    coordinator.start()
    try:
        time.sleep(0.05)
        (tasks_dir / "todo" / "001.md").write_text("hello", encoding="utf-8")
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
        on_task_change=lambda p: None,
        on_poll=lambda: poll_count.__setitem__("n", poll_count["n"] + 1),
        debounce_seconds=0.1,
        poll_interval_seconds=0.1,
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
        on_task_change=lambda p: seen.append(p),
        on_poll=lambda: None,
        debounce_seconds=0.1,
        poll_interval_seconds=3600,
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
        on_task_change=lambda p: None,
        on_poll=lambda: None,
    )
    coordinator.start()
    coordinator.start()  # second start is a no-op
    coordinator.stop()
    coordinator.stop()  # second stop is a no-op


def test_set_callbacks_updates_watcher_and_poll(tmp_path):
    """set_callbacks() replaces both the watcher's on_change and the poll callback."""
    from unittest.mock import MagicMock

    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    coord = DispatcherCoordinator(
        tasks_dir=tasks_dir,
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
