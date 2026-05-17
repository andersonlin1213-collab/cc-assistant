"""Plan 3c integration:
Real DispatcherCoordinator + real Orchestrator + mocked LLM.

Human writes a task in todo/ -> dispatcher fires -> orchestrator processes ->
file moves to done/ (or review/) -> no infinite loop.
"""

import asyncio
import threading
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.factory import build_orchestrator_and_coordinator
from src.agent.llm.types import LLMResponse, TextBlock, ToolUseBlock, Usage
from src.board.parser import parse_task_file
from src.board.writer import write_task_file
from src.models import Priority, Task, TaskStatus


def _make_kanban(tmp_path: Path) -> tuple[Path, Path, Path]:
    tasks = tmp_path / "tasks"
    for s in ["backlog", "todo", "doing", "blocked", "review", "done"]:
        (tasks / s).mkdir(parents=True)
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "rules.md").write_text("# Rules\nBe careful.\n", encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()
    return tasks, skills, logs


def _final(text: str) -> LLMResponse:
    return LLMResponse(
        content=[TextBlock(text=text)],
        stop_reason="end_turn",
        usage=Usage(),
        model="claude-sonnet-4-6",
    )


def _mark_complete(reason: str = "all done") -> LLMResponse:
    return LLMResponse(
        content=[
            TextBlock(text="Task accomplished."),
            ToolUseBlock(id="t1", name="mark_complete", input={"reason": reason}),
        ],
        stop_reason="tool_use",
        usage=Usage(),
        model="claude-sonnet-4-6",
    )


def _make_task(**overrides) -> Task:
    defaults = dict(
        id="200",
        title="Integration test task",
        project="cc-assistant",
        parent=None,
        priority=Priority.P1,
        tags=[],
        created=datetime(2026, 4, 26, 14, 0),
        updated=datetime(2026, 4, 26, 14, 0),
        auto_approve=True,
        depends_on=[],
        instructions="",
        subtasks=[],
        description="A task for integration testing.",
        conversation=[],
    )
    defaults.update(overrides)
    return Task(**defaults)


async def test_human_edit_drives_task_to_done(tmp_path):
    tasks_dir, skills_dir, logs_dir = _make_kanban(tmp_path)

    llm = MagicMock()
    llm.chat = AsyncMock(side_effect=[_mark_complete("ok"), _final("acknowledged")])

    orchestrator, coordinator = build_orchestrator_and_coordinator(
        tasks_dir=tasks_dir,
        skills_dir=skills_dir,
        logs_dir=logs_dir,
        llm=llm,
        debounce_seconds=0.2,
        poll_interval_seconds=3600,
    )

    coordinator.start()
    try:
        time.sleep(0.5)  # let watchdog settle on Windows
        # Human creates the task in todo/
        todo_path = tasks_dir / "todo" / "200-integ.md"
        write_task_file(_make_task(id="200", auto_approve=True), todo_path)

        # Wait for dispatcher to fire and orchestrator to process
        deadline = time.time() + 20.0
        today = datetime.now().strftime("%Y-%m")
        done_path = tasks_dir / "done" / today / "200-integ.md"
        while time.time() < deadline:
            if done_path.exists():
                break
            await asyncio.sleep(0.2)

        assert done_path.exists(), (
            f"task did not land in done/ after 20s. "
            f"todo exists: {todo_path.exists()}; "
            f"doing dir: {list((tasks_dir / 'doing').iterdir())}"
        )

        # Verify LLM was called and the AI reply was appended
        assert llm.chat.call_count >= 1
        parsed = parse_task_file(done_path)
        assert any(
            "acknowledged" in entry.content.lower() or "accomplished" in entry.content.lower()
            for entry in parsed.conversation
        ), f"no AI reply found. conversation={[e.content for e in parsed.conversation]}"
    finally:
        coordinator.stop()


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
    # No sync attribute should exist on the orchestrator any more
    assert not hasattr(orch, "sync")
