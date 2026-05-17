# Plan 3c: Orchestrator (Completion Promise Pattern)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Orchestrator that wires Layer 1 (board), Layer 2 (dispatcher), and Layer 3 (LLM + tools) into a working agent. Each cycle is fresh-context per the Completion Promise Pattern: parse task file → build messages from `skills/rules.md` + task → call LLM → execute tool calls in an inner loop → append final AI reply → decide next status → move file. Two virtual control tools (`mark_complete`, `mark_blocked`) let the LLM signal task-level decisions.

**Architecture:** Five small modules under `src/agent/`. `CycleState` is a per-cycle scratchpad capturing `mark_complete`/`mark_blocked` calls. `ToolBridge` advertises both regular tools (file_ops, shell) and the two control tools to the LLM, and dispatches `tool_use` blocks: control tools mutate `CycleState`, regular tools call `Tool.execute()`. `ContextBuilder` formats `(rules, task)` into the system + user messages the LLM sees. `Orchestrator.run_cycle(path)` runs one bounded LLM-tool loop, appends the final AI text to the task conversation inside `coordinator.suppress_self()`, decides next status from `CycleState` + `auto_approve` + current column, and moves the file. `Orchestrator.on_poll()` scans active tasks and runs cycles for any in `todo/` or `doing/`. A factory `build_orchestrator(...)` constructs the full graph and returns an `(orchestrator, coordinator)` pair the entry point can `start()`.

**Tech Stack:** Python 3.11+ asyncio. No new dependencies — uses existing `anthropic`, `pydantic`, `watchdog`, `apscheduler`. Tests use `unittest.mock.AsyncMock` for the LLM client.

**Out of scope (deferred):**
- CLI entry point (`cc-assistant run/stop/status`) — Plan 5.
- Multi-LLM provider switching at runtime — covered by existing factory; just exercised here.
- Sophisticated retry policies from `skills/rules.md` (timeout, network, auth) — deferred. MVP catches and logs exceptions, appends an `[AI] Error: ...` entry, and exits the cycle. Plan 4+ adds rule-driven retries.
- Subtask-level status updates — the LLM can edit subtasks via `file_ops` (writing the whole task file) but the orchestrator does not parse "what subtasks changed" or auto-advance based on subtasks-all-done. Status transitions are explicit via `mark_complete`/`mark_blocked` only. This keeps the protocol simple and predictable.
- Concurrency: cycles are processed serially (`for path in paths: await run_cycle(path)`). Plan 5 can switch to `asyncio.gather` once we understand contention patterns.

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `src/agent/cycle_state.py` | `CycleState` dataclass — per-cycle scratchpad for control-tool calls |
| Create | `src/agent/tool_bridge.py` | `ToolBridge` — advertises tools (regular + control), dispatches `tool_use` blocks |
| Create | `src/agent/context.py` | `ContextBuilder.build(rules, task) -> list[Message]` |
| Create | `src/agent/orchestrator.py` | `Orchestrator` — `run_cycle(path)` and `on_poll()` |
| Create | `src/agent/factory.py` | `build_orchestrator_and_coordinator(config_overrides=None)` factory |
| Create | `tests/test_cycle_state.py` | CycleState tests |
| Create | `tests/test_tool_bridge.py` | ToolBridge tests (definitions + dispatch + control tools) |
| Create | `tests/test_context_builder.py` | ContextBuilder tests |
| Create | `tests/test_orchestrator.py` | Orchestrator unit tests with mocked LLM |
| Create | `tests/test_orchestrator_integration.py` | End-to-end: real DispatcherCoordinator + Orchestrator + mocked LLM |

---

### Task 1: CycleState and ToolBridge

**Files:**
- Create: `src/agent/cycle_state.py`
- Create: `src/agent/tool_bridge.py`
- Create: `tests/test_cycle_state.py`
- Create: `tests/test_tool_bridge.py`

- [ ] **Step 1: Write the failing tests for CycleState**

Write `tests/test_cycle_state.py`:

```python
from src.agent.cycle_state import CycleState


def test_cycle_state_defaults():
    s = CycleState()
    assert s.marked_complete is False
    assert s.marked_blocked is False
    assert s.complete_reason == ""
    assert s.blocked_reason == ""


def test_cycle_state_mark_complete():
    s = CycleState()
    s.mark_complete("all good")
    assert s.marked_complete is True
    assert s.complete_reason == "all good"


def test_cycle_state_mark_blocked():
    s = CycleState()
    s.mark_blocked("need user input")
    assert s.marked_blocked is True
    assert s.blocked_reason == "need user input"


def test_cycle_state_both_marks_independent():
    """Both flags can technically be set; orchestrator decides which wins."""
    s = CycleState()
    s.mark_complete("done")
    s.mark_blocked("but also blocked?")
    assert s.marked_complete is True
    assert s.marked_blocked is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_cycle_state.py -v
```

Expected: FAIL — cannot import `CycleState`.

- [ ] **Step 3: Write CycleState implementation**

Write `src/agent/cycle_state.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CycleState:
    """Per-cycle scratchpad capturing control-tool calls.

    The Orchestrator constructs a fresh CycleState at the start of each cycle.
    Control tools (`mark_complete`, `mark_blocked`) mutate this state via the
    ToolBridge; the Orchestrator inspects it after the LLM loop terminates to
    decide the next TaskStatus.
    """

    marked_complete: bool = False
    marked_blocked: bool = False
    complete_reason: str = ""
    blocked_reason: str = ""

    def mark_complete(self, reason: str = "") -> None:
        self.marked_complete = True
        self.complete_reason = reason

    def mark_blocked(self, reason: str = "") -> None:
        self.marked_blocked = True
        self.blocked_reason = reason
```

- [ ] **Step 4: Run CycleState test**

```bash
uv run pytest tests/test_cycle_state.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Write the failing tests for ToolBridge**

Write `tests/test_tool_bridge.py`:

```python
from src.agent.cycle_state import CycleState
from src.agent.llm.types import ToolUseBlock
from src.agent.tool_bridge import ToolBridge
from src.tools.base import Tool, ToolResult


class FakeTool(Tool):
    name = "fake"
    description = "A fake tool"
    parameters_schema = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
    }
    risk_level = "low"

    async def execute(self, dry_run: bool = False, **params) -> ToolResult:
        return ToolResult(success=True, output=f"echo:{params['x']}")


def test_tool_definitions_include_regular_and_control():
    """ToolBridge advertises regular tools + control tools to the LLM."""
    bridge = ToolBridge(tools=[FakeTool()])
    defs = bridge.tool_definitions()

    names = {d.name for d in defs}
    assert "fake" in names
    assert "mark_complete" in names
    assert "mark_blocked" in names
    assert len(defs) == 3


async def test_dispatch_regular_tool_returns_tool_result():
    bridge = ToolBridge(tools=[FakeTool()])
    state = CycleState()

    tu = ToolUseBlock(id="call_1", name="fake", input={"x": "hi"})
    result = await bridge.dispatch(tu, state)

    assert result.success is True
    assert result.output == "echo:hi"
    # State unchanged for regular tools
    assert state.marked_complete is False
    assert state.marked_blocked is False


async def test_dispatch_mark_complete_sets_state():
    bridge = ToolBridge(tools=[FakeTool()])
    state = CycleState()

    tu = ToolUseBlock(id="call_2", name="mark_complete", input={"reason": "all done"})
    result = await bridge.dispatch(tu, state)

    assert result.success is True
    assert state.marked_complete is True
    assert state.complete_reason == "all done"


async def test_dispatch_mark_blocked_sets_state():
    bridge = ToolBridge(tools=[FakeTool()])
    state = CycleState()

    tu = ToolUseBlock(id="call_3", name="mark_blocked", input={"reason": "need approval"})
    result = await bridge.dispatch(tu, state)

    assert result.success is True
    assert state.marked_blocked is True
    assert state.blocked_reason == "need approval"


async def test_dispatch_unknown_tool_returns_error():
    bridge = ToolBridge(tools=[FakeTool()])
    state = CycleState()

    tu = ToolUseBlock(id="call_4", name="nonexistent", input={})
    result = await bridge.dispatch(tu, state)

    assert result.success is False
    assert result.error is not None
    assert "unknown tool" in result.error.lower()


async def test_dispatch_passes_dry_run():
    """Regular tool dispatch forwards the dry_run flag."""
    captured = {}

    class CaptureTool(Tool):
        name = "capture"
        description = "capture dry_run"
        parameters_schema = {"type": "object"}
        risk_level = "low"

        async def execute(self, dry_run: bool = False, **params) -> ToolResult:
            captured["dry_run"] = dry_run
            return ToolResult(success=True, output="captured")

    bridge = ToolBridge(tools=[CaptureTool()])
    state = CycleState()

    tu = ToolUseBlock(id="c", name="capture", input={})
    await bridge.dispatch(tu, state, dry_run=True)

    assert captured["dry_run"] is True
```

- [ ] **Step 6: Run ToolBridge test (will fail)**

```bash
uv run pytest tests/test_tool_bridge.py -v
```

Expected: FAIL — cannot import `ToolBridge`.

- [ ] **Step 7: Write ToolBridge implementation**

Write `src/agent/tool_bridge.py`:

```python
from __future__ import annotations

from typing import Optional

from src.agent.cycle_state import CycleState
from src.agent.llm.types import ToolDefinition, ToolUseBlock
from src.tools.base import Tool, ToolResult


_CONTROL_TOOL_DEFINITIONS = [
    ToolDefinition(
        name="mark_complete",
        description=(
            "Call when the task is fully done and ready for archival or human review. "
            "If the task's auto_approve is true, the task moves to done/. "
            "Otherwise it moves to review/ for human sign-off."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Brief summary of what was accomplished.",
                },
            },
            "required": ["reason"],
        },
    ),
    ToolDefinition(
        name="mark_blocked",
        description=(
            "Call when you cannot continue without human input or external action. "
            "The task moves to blocked/ until the human responds in the conversation."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "What you need from the human, specifically.",
                },
            },
            "required": ["reason"],
        },
    ),
]


class ToolBridge:
    """Translates between Tool instances and the LLM's ToolDefinition/ToolUseBlock world.

    Advertises both regular tools (file_ops, shell, ...) and two virtual control
    tools (`mark_complete`, `mark_blocked`) which exist only in the LLM's view.
    Control tool calls mutate the supplied CycleState; regular calls go through
    Tool.execute().
    """

    def __init__(self, tools: list[Tool]) -> None:
        self._tools: dict[str, Tool] = {t.name: t for t in tools}

    def tool_definitions(self) -> list[ToolDefinition]:
        regular = [
            ToolDefinition(
                name=t.name,
                description=t.description,
                input_schema=t.parameters_schema,
            )
            for t in self._tools.values()
        ]
        return regular + list(_CONTROL_TOOL_DEFINITIONS)

    async def dispatch(
        self,
        tool_use: ToolUseBlock,
        cycle_state: CycleState,
        dry_run: bool = False,
    ) -> ToolResult:
        name = tool_use.name
        params = tool_use.input or {}

        if name == "mark_complete":
            reason = str(params.get("reason", ""))
            cycle_state.mark_complete(reason)
            return ToolResult(success=True, output=f"task marked complete: {reason}")

        if name == "mark_blocked":
            reason = str(params.get("reason", ""))
            cycle_state.mark_blocked(reason)
            return ToolResult(success=True, output=f"task marked blocked: {reason}")

        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                success=False,
                output="",
                error=f"unknown tool: {name!r}",
            )

        return await tool.execute(dry_run=dry_run, **params)
```

- [ ] **Step 8: Run all Task 1 tests**

```bash
uv run pytest tests/test_cycle_state.py tests/test_tool_bridge.py -v
```

Expected: 4 + 6 = 10 passed.

- [ ] **Step 9: Commit**

```bash
git add src/agent/cycle_state.py src/agent/tool_bridge.py tests/test_cycle_state.py tests/test_tool_bridge.py
git commit -m "feat: add CycleState and ToolBridge with mark_complete/mark_blocked control tools"
```

---

### Task 2: ContextBuilder

**Files:**
- Create: `src/agent/context.py`
- Create: `tests/test_context_builder.py`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_context_builder.py`:

```python
from datetime import datetime

from src.agent.context import ContextBuilder
from src.models import (
    ConversationEntry,
    ConversationRole,
    Priority,
    Subtask,
    SubtaskStatus,
    Task,
)


def _make_task(**overrides) -> Task:
    defaults = dict(
        id="025",
        title="部署后端",
        project="cc-assistant",
        parent=None,
        priority=Priority.P1,
        tags=["devops"],
        created=datetime(2026, 4, 26, 14, 0),
        updated=datetime(2026, 4, 26, 14, 0),
        auto_approve=True,
        depends_on=[],
        instructions="",
        subtasks=[],
        description="把后端部署到生产。",
        conversation=[],
    )
    defaults.update(overrides)
    return Task(**defaults)


def test_build_returns_system_and_user_messages():
    builder = ContextBuilder()
    messages = builder.build(rules="# Rules\nBe careful.", task=_make_task())

    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[1].role == "user"


def test_system_message_includes_rules():
    builder = ContextBuilder()
    messages = builder.build(rules="# Custom Rules\n- Always commit.", task=_make_task())

    sys_text = messages[0].content
    assert isinstance(sys_text, str)
    assert "Custom Rules" in sys_text
    assert "Always commit." in sys_text


def test_system_message_explains_control_tools():
    """The system prompt must instruct the LLM about mark_complete and mark_blocked."""
    builder = ContextBuilder()
    messages = builder.build(rules="", task=_make_task())

    sys_text = messages[0].content
    assert "mark_complete" in sys_text
    assert "mark_blocked" in sys_text


def test_user_message_includes_task_metadata():
    builder = ContextBuilder()
    task = _make_task(
        id="025",
        title="部署后端",
        project="cc-assistant",
        priority=Priority.P0,
        tags=["devops", "urgent"],
        description="把后端部署到生产。",
    )
    messages = builder.build(rules="", task=task)

    user_text = messages[1].content
    assert isinstance(user_text, str)
    assert "025" in user_text
    assert "部署后端" in user_text
    assert "cc-assistant" in user_text
    assert "P0" in user_text
    assert "devops" in user_text
    assert "把后端部署到生产" in user_text


def test_user_message_includes_subtasks():
    builder = ContextBuilder()
    task = _make_task(
        subtasks=[
            Subtask(id="025-1", title="备份数据库", status=SubtaskStatus.DONE),
            Subtask(
                id="025-2",
                title="拉取代码",
                status=SubtaskStatus.BLOCKED,
                blocking_reason="需要确认分支",
            ),
        ]
    )
    messages = builder.build(rules="", task=task)

    user_text = messages[1].content
    assert "025-1" in user_text
    assert "备份数据库" in user_text
    assert "done" in user_text
    assert "025-2" in user_text
    assert "拉取代码" in user_text
    assert "blocked" in user_text
    assert "需要确认分支" in user_text


def test_user_message_includes_conversation_history():
    builder = ContextBuilder()
    task = _make_task(
        conversation=[
            ConversationEntry(
                role=ConversationRole.HUMAN,
                timestamp=datetime(2026, 4, 26, 14, 0),
                content="先备份数据库。",
            ),
            ConversationEntry(
                role=ConversationRole.AI,
                timestamp=datetime(2026, 4, 26, 14, 1),
                content="收到。",
            ),
        ]
    )
    messages = builder.build(rules="", task=task)

    user_text = messages[1].content
    assert "先备份数据库" in user_text
    assert "收到" in user_text
    # Roles should be visible
    assert "Human" in user_text or "human" in user_text.lower()
    assert "AI" in user_text or "ai" in user_text.lower()


def test_user_message_includes_task_instructions_when_present():
    """The Task.instructions field is task-level guidance overriding rules.md."""
    builder = ContextBuilder()
    task = _make_task(instructions="使用 Tailwind CSS。设计语言保持极简。")
    messages = builder.build(rules="", task=task)

    user_text = messages[1].content
    assert "Tailwind" in user_text
    assert "极简" in user_text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_context_builder.py -v
```

Expected: FAIL — cannot import `ContextBuilder`.

- [ ] **Step 3: Write implementation**

Write `src/agent/context.py`:

```python
from __future__ import annotations

from src.agent.llm.types import Message
from src.models import Task


_SYSTEM_AGENT_INSTRUCTIONS = """\
You are an autonomous AI agent processing one task per cycle. The user maintains
the task's status by editing a Markdown file; you respond by appending to its
conversation thread and (when applicable) by signaling completion or blocking.

Decide the next concrete action and use the available tools. Tools include local
file operations and shell execution; use them as needed.

Two control tools govern the task lifecycle — call them at the END of your work:
  - `mark_complete(reason)`: the task is done. The system will move it to done/
    (or review/ if auto_approve is false).
  - `mark_blocked(reason)`: you need human input or external action to proceed.
    The system will move the task to blocked/ until the human responds.

If neither control tool is called, the task remains in progress for the next
cycle. Be concise in your final reply — it is appended to the human-readable
conversation thread.
"""


class ContextBuilder:
    """Build the LLM messages list from rules + task per the Completion Promise Pattern.

    Each cycle reconstructs context from scratch: the system prompt is `rules.md`
    content plus generic agent instructions; the user message is the entire task
    state (metadata, description, subtasks, conversation history, optional
    task-level instructions).

    No prior LLM conversation is preserved across cycles.
    """

    def build(self, rules: str, task: Task) -> list[Message]:
        system_text = self._build_system(rules)
        user_text = self._build_user(task)
        return [
            Message(role="system", content=system_text),
            Message(role="user", content=user_text),
        ]

    @staticmethod
    def _build_system(rules: str) -> str:
        if rules.strip():
            return f"{rules.rstrip()}\n\n{_SYSTEM_AGENT_INSTRUCTIONS}"
        return _SYSTEM_AGENT_INSTRUCTIONS

    @staticmethod
    def _build_user(task: Task) -> str:
        lines: list[str] = []
        lines.append(f"# Task {task.id}: {task.title}")
        lines.append("")

        # Metadata block
        meta_lines = [f"- **Project:** {task.project or '(none)'}"]
        if task.parent:
            meta_lines.append(f"- **Parent:** {task.parent}")
        meta_lines.append(f"- **Priority:** {task.priority.value}")
        if task.tags:
            meta_lines.append(f"- **Tags:** {', '.join(task.tags)}")
        meta_lines.append(f"- **auto_approve:** {task.auto_approve}")
        lines.extend(meta_lines)
        lines.append("")

        # Task-level instructions (overrides rules.md for this task only)
        if task.instructions.strip():
            lines.append("## Task Instructions")
            lines.append(task.instructions.rstrip())
            lines.append("")

        # Description
        lines.append("## Description")
        lines.append(task.description.rstrip() if task.description else "(empty)")
        lines.append("")

        # Subtasks
        if task.subtasks:
            lines.append("## Subtasks")
            for sub in task.subtasks:
                tail = (
                    f" — blocked on: {sub.blocking_reason}"
                    if sub.blocking_reason
                    else ""
                )
                lines.append(f"- [{sub.status.value}] {sub.id}: {sub.title}{tail}")
            lines.append("")

        # Conversation history
        if task.conversation:
            lines.append("## Conversation")
            for entry in task.conversation:
                ts = entry.timestamp.strftime("%Y-%m-%d %H:%M")
                lines.append(f"### [{entry.role.value}] {ts}")
                lines.append(entry.content.rstrip())
                lines.append("")

        return "\n".join(lines).rstrip() + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_context_builder.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/agent/context.py tests/test_context_builder.py
git commit -m "feat: add ContextBuilder formatting rules + task into LLM messages"
```

---

### Task 3: Orchestrator core

**Files:**
- Create: `src/agent/orchestrator.py`
- Create: `tests/test_orchestrator.py`

The Orchestrator runs one cycle per call, with a bounded inner LLM/tool loop and a status decision at the end. Tests exercise every important branch with a mocked LLM.

- [ ] **Step 1: Write the failing tests**

Write `tests/test_orchestrator.py`:

```python
"""Orchestrator unit tests with a mocked LLM client and real Layer 1+3b modules."""

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.llm.types import (
    LLMResponse,
    Message,
    TextBlock,
    ToolUseBlock,
    Usage,
)
from src.agent.orchestrator import Orchestrator
from src.board.writer import write_task_file
from src.models import Priority, Task, TaskStatus
from src.tools.file_ops import FileOpsTool


def _kanban(tmp_path: Path) -> Path:
    tasks = tmp_path / "tasks"
    for s in ["backlog", "todo", "doing", "blocked", "review", "done"]:
        (tasks / s).mkdir(parents=True)
    return tasks


def _skills(tmp_path: Path, rules: str = "# Rules\n") -> Path:
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "rules.md").write_text(rules, encoding="utf-8")
    return skills


def _logs(tmp_path: Path) -> Path:
    logs = tmp_path / "logs"
    logs.mkdir()
    return logs


def _make_task(**overrides) -> Task:
    defaults = dict(
        id="100",
        title="Test",
        project="",
        parent=None,
        priority=Priority.P1,
        tags=[],
        created=datetime(2026, 4, 26, 14, 0),
        updated=datetime(2026, 4, 26, 14, 0),
        auto_approve=True,
        depends_on=[],
        instructions="",
        subtasks=[],
        description="A test task.",
        conversation=[],
    )
    defaults.update(overrides)
    return Task(**defaults)


def _llm_with_responses(*responses: LLMResponse):
    """Build a mocked LLMClient.chat that returns the given responses in order."""
    mock = MagicMock()
    mock.chat = AsyncMock(side_effect=list(responses))
    return mock


def _final_text(text: str = "All done.") -> LLMResponse:
    return LLMResponse(
        content=[TextBlock(text=text)],
        stop_reason="end_turn",
        usage=Usage(),
        model="claude-sonnet-4-6",
    )


def _tool_use(name: str, input_: dict, id_: str = "tu1", text: str = "") -> LLMResponse:
    content = [TextBlock(text=text)] if text else []
    content.append(ToolUseBlock(id=id_, name=name, input=input_))
    return LLMResponse(
        content=content,
        stop_reason="tool_use",
        usage=Usage(),
        model="claude-sonnet-4-6",
    )


@contextmanager
def _noop_suppress():
    yield


def _make_orchestrator(tmp_path: Path, llm) -> Orchestrator:
    return Orchestrator(
        tasks_dir=_kanban(tmp_path),
        skills_dir=_skills(tmp_path),
        logs_dir=_logs(tmp_path),
        llm=llm,
        tools=[FileOpsTool()],
        suppress_self=_noop_suppress,
        sync=MagicMock(commit_and_push=MagicMock(return_value=SimpleNamespace(committed=False, pushed=False))),
    )


# ------------------------------------------------------------------ #
# Test cases                                                         #
# ------------------------------------------------------------------ #


async def test_run_cycle_skips_when_path_missing(tmp_path):
    """A path that doesn't exist (e.g., already moved) is a no-op."""
    llm = _llm_with_responses(_final_text())
    orch = _make_orchestrator(tmp_path, llm)

    await orch.run_cycle(tmp_path / "tasks" / "todo" / "ghost.md")

    llm.chat.assert_not_called()


async def test_simple_text_cycle_appends_ai_reply(tmp_path):
    """A single end_turn response appends one AI conversation entry."""
    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-test.md"
    write_task_file(_make_task(id="100"), todo_path)

    llm = _llm_with_responses(_final_text("Acknowledged."))
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(todo_path)

    # File auto-advances todo -> doing on first cycle
    moved = (tasks_dir / "doing" / "100-test.md")
    assert moved.exists()
    from src.board.parser import parse_task_file
    parsed = parse_task_file(moved)
    assert len(parsed.conversation) == 1
    assert parsed.conversation[0].content == "Acknowledged."


async def test_tool_use_loop(tmp_path):
    """When the LLM calls a tool, the result is fed back and the cycle continues."""
    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-tool.md"
    write_task_file(_make_task(id="100"), todo_path)

    target = tmp_path / "scratch.txt"

    llm = _llm_with_responses(
        _tool_use(
            "file_ops",
            {"operation": "write", "path": str(target), "content": "hello"},
            text="I will write a file.",
        ),
        _final_text("Wrote the file."),
    )
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(todo_path)

    assert target.exists()
    assert target.read_text(encoding="utf-8") == "hello"
    assert llm.chat.call_count == 2


async def test_mark_complete_moves_to_done_when_auto_approve(tmp_path):
    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-mc.md"
    write_task_file(_make_task(id="100", auto_approve=True), todo_path)

    llm = _llm_with_responses(
        _tool_use("mark_complete", {"reason": "all done"}, text="Task complete."),
        _final_text("OK."),
    )
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(todo_path)

    # done/ uses monthly subdirs
    today = datetime.now().strftime("%Y-%m")
    done_path = tasks_dir / "done" / today / "100-mc.md"
    assert done_path.exists()
    assert not todo_path.exists()


async def test_mark_complete_moves_to_review_when_not_auto_approve(tmp_path):
    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-rev.md"
    write_task_file(_make_task(id="100", auto_approve=False), todo_path)

    llm = _llm_with_responses(
        _tool_use("mark_complete", {"reason": "needs review"}),
        _final_text("Submitted for review."),
    )
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(todo_path)

    review_path = tasks_dir / "review" / "100-rev.md"
    assert review_path.exists()
    assert not todo_path.exists()


async def test_mark_blocked_moves_to_blocked(tmp_path):
    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-block.md"
    write_task_file(_make_task(id="100"), todo_path)

    llm = _llm_with_responses(
        _tool_use("mark_blocked", {"reason": "need credentials"}),
        _final_text("Blocked."),
    )
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(todo_path)

    blocked_path = tasks_dir / "blocked" / "100-block.md"
    assert blocked_path.exists()


async def test_already_in_doing_stays_in_doing_when_no_marks(tmp_path):
    """A task already in doing/ that finishes a cycle without control tools stays put."""
    tasks_dir = orch_dir(tmp_path)
    doing_path = tasks_dir / "doing" / "100-stay.md"
    write_task_file(_make_task(id="100"), doing_path)

    llm = _llm_with_responses(_final_text("Still working."))
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(doing_path)

    assert doing_path.exists()  # still in doing/


async def test_terminal_states_are_skipped(tmp_path):
    """A task in done/ or review/ does NOT trigger an LLM call."""
    tasks_dir = orch_dir(tmp_path)
    review_path = tasks_dir / "review" / "100-rev.md"
    write_task_file(_make_task(id="100"), review_path)

    llm = _llm_with_responses(_final_text("Should not be called."))
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(review_path)

    llm.chat.assert_not_called()
    assert review_path.exists()


async def test_max_rounds_protects_against_infinite_loop(tmp_path):
    """If the LLM keeps calling tools forever, the cycle bails after MAX_TOOL_USE_ROUNDS."""
    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-loop.md"
    write_task_file(_make_task(id="100"), todo_path)

    target = tmp_path / "x.txt"

    # Always return tool_use, never end_turn — should be capped
    looping_response = _tool_use(
        "file_ops",
        {"operation": "write", "path": str(target), "content": "loop"},
    )
    # Provide enough responses to exceed the cap; the orchestrator should stop
    # before exhausting them.
    llm = MagicMock()
    llm.chat = AsyncMock(return_value=looping_response)
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(todo_path)

    # Should not exceed the documented cap (Orchestrator.MAX_TOOL_USE_ROUNDS)
    assert llm.chat.call_count <= Orchestrator.MAX_TOOL_USE_ROUNDS


# Helpers used in multiple tests above; kept at the bottom so the test bodies
# read top-to-bottom but can reference them. Pytest collects regardless of order.

def orch_dir(tmp_path: Path) -> Path:
    return _kanban(tmp_path)


def _make_orchestrator_for(tmp_path: Path, llm) -> Orchestrator:
    """Variant of _make_orchestrator that does NOT reuse already-created dirs."""
    skills = tmp_path / "skills"
    if not skills.exists():
        skills.mkdir()
        (skills / "rules.md").write_text("# Rules\n", encoding="utf-8")
    logs = tmp_path / "logs"
    if not logs.exists():
        logs.mkdir()

    return Orchestrator(
        tasks_dir=tmp_path / "tasks",
        skills_dir=skills,
        logs_dir=logs,
        llm=llm,
        tools=[FileOpsTool()],
        suppress_self=_noop_suppress,
        sync=MagicMock(commit_and_push=MagicMock(return_value=SimpleNamespace(committed=False, pushed=False))),
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_orchestrator.py -v
```

Expected: FAIL — cannot import `Orchestrator`.

- [ ] **Step 3: Write implementation**

Write `src/agent/orchestrator.py`:

```python
from __future__ import annotations

import logging
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from src.agent.context import ContextBuilder
from src.agent.cycle_state import CycleState
from src.agent.llm.base import LLMClient
from src.agent.llm.types import (
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from src.agent.tool_bridge import ToolBridge
from src.board.manager import BoardManager
from src.board.parser import parse_task_file
from src.board.writer import append_conversation
from src.dispatcher.sync import GitSync
from src.logging.structured import StructuredLogger
from src.models import (
    ConversationEntry,
    ConversationRole,
    LogEntry,
    Task,
    TaskStatus,
)
from src.rules.loader import RulesLoader
from src.tools.base import Tool


_log = logging.getLogger(__name__)


class Orchestrator:
    """Runs one Completion-Promise-Pattern cycle per call.

    Cycle = parse task -> build messages -> LLM-tool inner loop -> append AI reply
    -> decide next status -> move file -> commit. Each cycle reconstructs context
    from scratch (rules.md + task file); no LLM state is preserved across cycles.
    """

    MAX_TOOL_USE_ROUNDS = 10

    def __init__(
        self,
        tasks_dir: Path,
        skills_dir: Path,
        logs_dir: Path,
        llm: LLMClient,
        tools: list[Tool],
        suppress_self: Callable[[], AbstractContextManager],
        sync: GitSync,
    ) -> None:
        self.tasks_dir = tasks_dir
        self.manager = BoardManager(tasks_dir)
        self.rules = RulesLoader(skills_dir)
        self.logger = StructuredLogger(logs_dir)
        self.context_builder = ContextBuilder()
        self.bridge = ToolBridge(tools)
        self.llm = llm
        self.suppress_self = suppress_self
        self.sync = sync

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    async def run_cycle(self, path: Path) -> None:
        """Execute one cycle for the task at `path`. Idempotent and crash-safe.

        No-op if path does not exist (file may already have been moved by an
        earlier cycle) or if the task is in a terminal column (done/, review/).
        """
        if not path.exists():
            return

        current_status = self._status_from_path(path)
        if current_status in (TaskStatus.DONE, TaskStatus.REVIEW):
            return

        task = parse_task_file(path)
        self.logger.log(LogEntry(
            task_id=task.id, action="cycle_start",
            detail=f"status={current_status.value}",
        ))

        try:
            final_text, cycle_state = await self._run_llm_loop(task)
        except Exception as e:  # pylint: disable=broad-except
            self.logger.log(LogEntry(
                task_id=task.id, action="cycle_error",
                detail=str(e), status="error",
            ))
            final_text = f"[Error] {e}"
            cycle_state = CycleState()

        next_status = self._decide_next_status(current_status, task, cycle_state)

        # Mutate filesystem inside suppress_self to avoid retriggering ourselves.
        with self.suppress_self():
            self._append_ai_reply(path, final_text)
            new_path = path
            if next_status != current_status:
                new_path = self.manager.move_task(path, next_status)
            self.sync.commit_and_push(
                f"agent: {task.id} {current_status.value}->{next_status.value}"
            )

        self.logger.log(LogEntry(
            task_id=task.id, action="cycle_complete",
            detail=f"final_status={next_status.value} path={new_path}",
        ))

    async def on_poll(self) -> None:
        """Scheduled scan: run a cycle for each task in todo/ and doing/."""
        for status in (TaskStatus.TODO, TaskStatus.DOING):
            for path in self.manager.list_tasks(status):
                try:
                    await self.run_cycle(path)
                except Exception:  # pylint: disable=broad-except
                    self.logger.log_system(
                        action="poll_error",
                        detail=f"path={path}",
                        status="error",
                    )

    # ------------------------------------------------------------------ #
    # Internals                                                          #
    # ------------------------------------------------------------------ #

    async def _run_llm_loop(self, task: Task) -> tuple[str, CycleState]:
        rules = self.rules.load()
        messages = self.context_builder.build(rules, task)
        tool_defs = self.bridge.tool_definitions()
        cycle_state = CycleState()

        final_text = ""
        for _ in range(self.MAX_TOOL_USE_ROUNDS):
            response = await self.llm.chat(messages, tools=tool_defs)
            self.logger.log(LogEntry(
                task_id=task.id, action="llm_call",
                detail=f"stop_reason={response.stop_reason}",
            ))

            if response.stop_reason != "tool_use":
                final_text = self._extract_text(response.content)
                break

            # tool_use round: execute each tool, append assistant + tool_result messages
            tool_use_blocks = [
                b for b in response.content if isinstance(b, ToolUseBlock)
            ]
            if not tool_use_blocks:
                final_text = self._extract_text(response.content)
                break

            messages.append(Message(role="assistant", content=response.content))

            tool_result_blocks: list = []
            for tu in tool_use_blocks:
                result = await self.bridge.dispatch(tu, cycle_state)
                self.logger.log(LogEntry(
                    task_id=task.id, action="tool_exec", tool=tu.name,
                    detail=result.output[:200] if result.success else (result.error or ""),
                    status="success" if result.success else "error",
                ))
                tool_result_blocks.append(
                    ToolResultBlock(
                        tool_use_id=tu.id,
                        content=result.output if result.success else (result.error or ""),
                        is_error=not result.success,
                    )
                )
            messages.append(Message(role="user", content=tool_result_blocks))
        else:
            # Loop exited via for-else (no break) — hit the cap
            final_text = (
                "[Cycle exceeded MAX_TOOL_USE_ROUNDS; bailing out — "
                "consider mark_blocked or mark_complete next time.]"
            )
            self.logger.log(LogEntry(
                task_id=task.id, action="cycle_capped",
                detail=f"rounds={self.MAX_TOOL_USE_ROUNDS}",
                status="error",
            ))

        return final_text, cycle_state

    @staticmethod
    def _extract_text(blocks) -> str:
        parts: list[str] = []
        for b in blocks:
            if isinstance(b, TextBlock):
                parts.append(b.text)
        return "\n\n".join(parts).strip() or "(no reply)"

    def _status_from_path(self, path: Path) -> TaskStatus:
        # Walk up parents until we hit one of the six column names.
        column_names = {s.value for s in TaskStatus}
        for parent in path.parents:
            if parent.name in column_names:
                return TaskStatus(parent.name)
        # Default to DOING if we can't tell — the file will end up there anyway.
        return TaskStatus.DOING

    @staticmethod
    def _decide_next_status(
        current: TaskStatus, task: Task, state: CycleState
    ) -> TaskStatus:
        # Explicit signals win
        if state.marked_blocked:
            return TaskStatus.BLOCKED
        if state.marked_complete:
            return TaskStatus.DONE if task.auto_approve else TaskStatus.REVIEW
        # Auto-advance todo -> doing on first cycle
        if current == TaskStatus.TODO:
            return TaskStatus.DOING
        # Otherwise stay where we are
        return current

    def _append_ai_reply(self, path: Path, text: str) -> None:
        entry = ConversationEntry(
            role=ConversationRole.AI,
            timestamp=datetime.now(),
            content=text,
        )
        append_conversation(path, entry)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_orchestrator.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add Orchestrator with bounded LLM-tool loop and status transitions"
```

---

### Task 4: Factory and end-to-end integration

**Files:**
- Create: `src/agent/factory.py`
- Create: `tests/test_orchestrator_integration.py`

The factory builds the full graph (Orchestrator + DispatcherCoordinator) and wires their callbacks together. The integration test exercises the entire stack with a mocked LLM: a real DispatcherCoordinator, real BoardManager, real parser/writer, real RulesLoader, real ToolBridge with FileOpsTool, but a mocked `LLMClient`.

- [ ] **Step 1: Write the failing tests**

Write `tests/test_orchestrator_integration.py`:

```python
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
        repo_dir=tmp_path,
        llm=llm,
        debounce_seconds=0.2,
        poll_interval_seconds=3600,
        git_pull_interval_seconds=3600,
    )

    coordinator.start()
    try:
        time.sleep(0.3)  # let watchdog settle on Windows
        # Human creates the task in todo/
        todo_path = tasks_dir / "todo" / "200-integ.md"
        write_task_file(_make_task(id="200", auto_approve=True), todo_path)

        # Wait for dispatcher to fire and orchestrator to process
        deadline = time.time() + 15.0
        today = datetime.now().strftime("%Y-%m")
        done_path = tasks_dir / "done" / today / "200-integ.md"
        while time.time() < deadline:
            if done_path.exists():
                break
            await asyncio.sleep(0.2)

        assert done_path.exists(), (
            f"task did not land in done/ after 15s. "
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_orchestrator_integration.py -v
```

Expected: FAIL — cannot import `build_orchestrator_and_coordinator`.

- [ ] **Step 3: Write factory implementation**

Write `src/agent/factory.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Optional

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

    The coordinator's `on_task_change` invokes `orchestrator.run_cycle`; its
    `on_poll` invokes `orchestrator.on_poll`. The orchestrator's writes are
    wrapped in `coordinator.suppress_self()` so the agent never reacts to its
    own filesystem changes.

    The `repo_dir` is used by GitSync — it is the root of the git repository
    that contains tasks_dir. For most setups, repo_dir is the project root.

    Two-step construction is required because Orchestrator needs the
    coordinator's `suppress_self` and `sync`, and the coordinator needs the
    orchestrator's `run_cycle` and `on_poll` callbacks. We construct the
    coordinator FIRST with placeholder callbacks, then build the orchestrator
    against the coordinator's already-constructed `suppress_self` and `sync`,
    then re-wire the coordinator's callbacks to the real orchestrator methods.
    """
    if tools is None:
        tools = [cls() for cls in ALL_TOOLS]

    # First-pass construction with placeholder callbacks
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

    # Re-wire coordinator callbacks to real orchestrator methods.
    # FileWatcher.on_change is set on the watcher; we replace it.
    coordinator.watcher.on_change = lambda p: _run_async(orchestrator.run_cycle(p))
    coordinator._on_poll = lambda: _run_async(orchestrator.on_poll())

    return orchestrator, coordinator


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

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_orchestrator_integration.py -v
```

Expected: 1 passed (may take up to 15s due to watchdog timing).

- [ ] **Step 5: Run full suite**

```bash
uv run pytest -v
```

Expected: all tests pass. Cumulative count after Plans 1+2+3a+3b+3c:
111 (previous) + 4 (cycle_state) + 6 (tool_bridge) + 7 (context) + 9 (orchestrator) + 1 (integration) = **138 passed, 1 skipped**.

- [ ] **Step 6: Commit**

```bash
git add src/agent/factory.py tests/test_orchestrator_integration.py
git commit -m "feat: add factory and end-to-end integration test for Orchestrator + Dispatcher"
```

---

## Self-Review

**1. Spec coverage (Layer 3 — Orchestrator portion):**
- Orchestrator decides next action and dispatches to tools: Task 3 — `run_cycle` runs an LLM-tool inner loop; control tools route via ToolBridge.
- Orchestrator writes results back to task file: Task 3 — `_append_ai_reply`.
- Orchestrator updates subtask statuses: NOT directly. The LLM updates subtasks via `file_ops.write` to rewrite the task file. The orchestrator does not auto-advance task status from "all subtasks done"; it relies on `mark_complete`. This is documented in the "Out of scope" section.
- Orchestrator moves task file: Task 3 — `_decide_next_status` + `manager.move_task`.
- Orchestrator does not execute work itself, only delegates: ToolBridge handles dispatch.
- Completion Promise Pattern (fresh context per cycle): Task 2 — ContextBuilder; Task 3 — `_run_llm_loop` rebuilds messages every call.
- Concurrency: serial in MVP. Documented in "Out of scope".

**2. Placeholder scan:**
- No "TBD" / "TODO" / "fill in details" / "similar to Task N".
- Test bodies have real assertions.
- Implementation steps include full code.
- Out-of-scope items (subtask auto-advance, retry rules, parallel cycles) are explicitly listed at the top with rationale, not buried as placeholders.

**3. Type consistency:**
- `Orchestrator.__init__` parameters match those used in tests (`tasks_dir`, `skills_dir`, `logs_dir`, `llm`, `tools`, `suppress_self`, `sync`) — verified across `_make_orchestrator_for` helper and the factory.
- `CycleState.mark_complete(reason)` / `mark_blocked(reason)` consistent in cycle_state.py, tool_bridge.py, and orchestrator.py.
- `ToolBridge.dispatch(tool_use, cycle_state, dry_run=False)` consistent in test and orchestrator caller.
- `ContextBuilder.build(rules, task) -> list[Message]` consistent in test and orchestrator caller.
- `Orchestrator.MAX_TOOL_USE_ROUNDS` referenced in test 9 — same name as in the class.
- `_run_async` runs `asyncio.run()` per call; the integration test runs in pytest-asyncio, which uses its own loop, but the dispatcher fires callbacks on watchdog/scheduler threads which have NO ambient loop, making `asyncio.run()` safe.

**4. Cross-platform:**
- Path handling via `pathlib.Path` throughout.
- Time-sensitive integration test uses 15s deadline and 0.3s startup delay (Windows watchdog).
- All file I/O explicitly uses `encoding="utf-8"`.

**5. Wire-up correctness:**
- The factory uses two-step construction because `Orchestrator` needs `coordinator.suppress_self` (a method bound to `coordinator.watcher`) and `coordinator.sync`. Building coordinator first → building orchestrator with those refs → rewiring coordinator's callbacks last is the only safe order. This is the same pattern delegate's controller uses.
- `_run_async` uses `asyncio.run()` per invocation — correct for sync threads dispatching async coroutines, and matches the Completion Promise (one fresh event loop per cycle).

All clean.
