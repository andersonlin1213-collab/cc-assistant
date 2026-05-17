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
        llm=MagicMock(),
        pid_file=pid_path,
        # Don't actually start the coordinator in this unit test — that's tested elsewhere
        # via the integration test. Pass start=False to skip.
        start=False,
        replay_pending=False,
        catchup_poll=False,
    )

    assert isinstance(handle, DaemonHandle)
    assert pid_path.exists()
    assert int(pid_path.read_text().strip()) == os.getpid()
    # Calling stop is idempotent and safe even when start=False
    handle.stop()
    assert not pid_path.exists()


def test_start_daemon_replays_stuck_intent_before_coordinator_starts(tmp_path):
    """A task left in blocked/ with intent=resume during a daemon outage is
    moved to doing/ as part of start_daemon, before the watcher starts."""
    tasks, skills, logs = _make_kanban(tmp_path)
    pid_path = logs / "agent.pid"

    from datetime import datetime
    from src.board.writer import write_task_file
    from src.models import Priority, Task, TaskIntent

    stuck = Task(
        id="800",
        title="stuck",
        priority=Priority.P1,
        created=datetime(2026, 4, 27, 9, 0),
        updated=datetime(2026, 4, 27, 9, 0),
        intent=TaskIntent.RESUME,
    )
    stuck_path = tasks / "blocked" / "800.md"
    write_task_file(stuck, stuck_path)

    handle = start_daemon(
        tasks_dir=tasks,
        skills_dir=skills,
        logs_dir=logs,
        llm=MagicMock(),
        pid_file=pid_path,
        start=False,  # don't start coordinator
        replay_pending=True,
        # Disable catchup_poll: this test focuses on replay's effect alone.
        # With it on, the moved-to-doing task would re-enter run_cycle with
        # a MagicMock LLM and the assertion target would shift.
        catchup_poll=False,
    )

    try:
        assert not stuck_path.exists(), "stuck task should have been moved out of blocked/"
        moved = tasks / "doing" / "800.md"
        assert moved.exists()
        from src.board.parser import parse_task_file
        assert parse_task_file(moved).intent is None
    finally:
        handle.stop()


def test_start_daemon_catchup_poll_processes_doing_save_missed_during_outage(tmp_path):
    """Real-world scenario from 5/3: daemon was offline 14h while user
    edited tasks/doing/002, 003, 007 to overwrite the placeholder with
    real replies. After daemon restart, the watcher only sees future
    events — those edits sat in `cycle_skipped` for the next 30-min
    poll interval. With catchup_poll=True, start_daemon runs on_poll()
    once, which processes the stale doing/ saves immediately.
    """
    from datetime import datetime
    from unittest.mock import AsyncMock
    from src.agent.llm.types import LLMResponse, TextBlock, Usage
    from src.board.writer import write_task_file
    from src.models import (
        ConversationEntry,
        ConversationRole,
        Priority,
        Task,
    )

    tasks, skills, logs = _make_kanban(tmp_path)
    pid_path = logs / "agent.pid"

    # Build a doing/ task whose last entry is a real (non-placeholder)
    # [我] reply — exactly the state of 002 after the user saved during
    # the outage.
    task = Task(
        id="900",
        title="missed-save",
        priority=Priority.P1,
        created=datetime(2026, 5, 3, 9, 0),
        updated=datetime(2026, 5, 3, 13, 14),
        auto_approve=True,
        conversation=[
            ConversationEntry(
                role=ConversationRole.AI,
                timestamp=datetime(2026, 5, 3, 8, 54),
                content="ack",
            ),
            ConversationEntry(
                role=ConversationRole.HUMAN,
                timestamp=datetime(2026, 5, 3, 13, 14),
                content="现在跑到哪里了？",
            ),
        ],
    )
    task_path = tasks / "doing" / "900-missed-save.md"
    write_task_file(task, task_path)

    llm = MagicMock()
    llm.chat = AsyncMock(return_value=LLMResponse(
        content=[TextBlock(text="ok, here's an update")],
        stop_reason="end_turn",
        usage=Usage(),
        model="claude-sonnet-4-6",
    ))

    handle = start_daemon(
        tasks_dir=tasks,
        skills_dir=skills,
        logs_dir=logs,
        llm=llm,
        pid_file=pid_path,
        start=False,
        replay_pending=False,
        catchup_poll=True,
    )

    try:
        # on_poll → run_cycle → llm.chat: the missed save was processed.
        llm.chat.assert_awaited_once()
    finally:
        handle.stop()


def test_start_daemon_catchup_poll_disabled_by_default_skips_doing_files(tmp_path):
    """Symmetric coverage: catchup_poll=False keeps the old behaviour
    (no boot-time scan), so callers — including the existing test suite
    — can opt out without surprise."""
    from datetime import datetime
    from unittest.mock import AsyncMock
    from src.board.writer import write_task_file
    from src.models import (
        ConversationEntry,
        ConversationRole,
        Priority,
        Task,
    )

    tasks, skills, logs = _make_kanban(tmp_path)
    pid_path = logs / "agent.pid"

    task = Task(
        id="901",
        title="no-catchup",
        priority=Priority.P1,
        created=datetime(2026, 5, 3, 9, 0),
        updated=datetime(2026, 5, 3, 13, 14),
        auto_approve=True,
        conversation=[
            ConversationEntry(
                role=ConversationRole.HUMAN,
                timestamp=datetime(2026, 5, 3, 13, 14),
                content="real reply",
            ),
        ],
    )
    write_task_file(task, tasks / "doing" / "901-no-catchup.md")

    llm = MagicMock()
    llm.chat = AsyncMock()

    handle = start_daemon(
        tasks_dir=tasks,
        skills_dir=skills,
        logs_dir=logs,
        llm=llm,
        pid_file=pid_path,
        start=False,
        replay_pending=False,
        catchup_poll=False,
    )

    try:
        llm.chat.assert_not_awaited()
    finally:
        handle.stop()


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
    """If the PID exists but the process no longer does, stop returns False
    AND the stale PID file is cleaned up so the next start can proceed."""
    pid_path = tmp_path / "agent.pid"
    pid_path.write_text("99999\n", encoding="utf-8")

    with patch("src.runner.os.kill", side_effect=ProcessLookupError):
        result = stop_daemon_by_pid_file(pid_path)

    assert result is False
    assert not pid_path.exists()


def test_stop_daemon_by_pid_file_cleans_stale_pid_on_windows_oserror(tmp_path):
    """On Windows, os.kill on a vanished PID raises OSError (errno 22 /
    winerror 87 ERROR_INVALID_PARAMETER), not ProcessLookupError. The stale
    PID file must still be cleaned up so subsequent starts work."""
    pid_path = tmp_path / "agent.pid"
    pid_path.write_text("99999\n", encoding="utf-8")

    with patch("src.runner.os.kill", side_effect=OSError(22, "ERROR_INVALID_PARAMETER")):
        result = stop_daemon_by_pid_file(pid_path)

    assert result is False
    assert not pid_path.exists()


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
