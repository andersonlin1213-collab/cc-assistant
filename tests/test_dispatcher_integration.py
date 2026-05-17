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
        on_task_change=fake_orchestrator,
        on_poll=lambda: None,
        debounce_seconds=0.2,
        poll_interval_seconds=3600,
    )
    coordinator.start()
    try:
        time.sleep(0.3)

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
