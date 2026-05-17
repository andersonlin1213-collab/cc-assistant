# Plan 5b — Obsidian-as-UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the original Plan 5b's FastAPI mobile Web UI with an Obsidian vault rooted at `tasks/`. Add eight Task model fields, an `intent`-driven mechanical column-move path, watcher hardening for vault noise, deep-link notifications, and retire the git auto-sync subsystem.

**Architecture:** The cc-assistant daemon is unchanged in its core loop. New behavior layers on at three places: (1) `Task` model + parser/writer round-trip the eight new fields; (2) `Orchestrator.run_cycle` short-circuits on `who != claude` and on non-null `intent`, the latter performing a mechanical move + intent clear without invoking the LLM; (3) `FileWatcher` ignores `.obsidian/`, `_attachments/`, conflict files, and similar Obsidian-generated noise. Sync (`src/dispatcher/sync.py`) is removed; Obsidian Sync replaces git as the cross-device transport for `tasks/`.

**Tech Stack:** Python 3.11+, pydantic, watchdog, python-frontmatter, pytest, pytest-asyncio. New optional dep: `psutil` (for the desktop-Obsidian process check).

**Reference Spec:** `docs/superpowers/specs/2026-04-27-plan-5b-obsidian-design.md`

---

## File Map

**Modify:**
- `src/models.py` — add `Who`, `TaskType`, `TaskIntent` enums + 8 fields on `Task`
- `src/board/parser.py` — read 8 new keys with defaults
- `src/board/writer.py` — emit 8 new keys in fixed order
- `src/agent/orchestrator.py` — `who` filter + `intent` mechanical path; remove `sync` parameter
- `src/agent/factory.py` — drop `sync` wiring
- `src/agent/context.py` — surface `measure`, `why`, `source_files` in user message
- `src/dispatcher/watcher.py` — add `IGNORE_PATTERNS` substring filter
- `src/dispatcher/coordinator.py` — drop `repo_dir`, `git_pull_interval_seconds`, `GitSync`, `pull` job
- `src/cli.py` — startup health checks (vault initialized, Obsidian process)
- `src/tools/notifier.py` — accept optional `deep_link` param; emit markdown msgtype when set
- `src/config.py` — add `obsidian_vault_name`
- `tasks/templates/default.md` — include all 8 new fields with sane defaults
- `.gitignore` (repo root) — add `tasks/_attachments/`

**Create:**
- `tasks/.gitignore` — ignore Obsidian per-device state
- `tasks/README.md` — landing page when opening vault
- `tasks/views.base` — Bases configuration for kanban + filter views

**Delete:**
- `src/dispatcher/sync.py`
- `src/agent/_noop_sync.py`
- `tests/test_sync.py`

**Test files modified:**
- `tests/test_models.py`
- `tests/test_parser.py`
- `tests/test_writer.py`
- `tests/test_manager.py`
- `tests/test_watcher.py`
- `tests/test_orchestrator.py`
- `tests/test_orchestrator_integration.py`
- `tests/test_context_builder.py`
- `tests/test_tool_notifier.py`
- `tests/test_dispatcher_integration.py`
- `tests/test_cli.py` / `tests/test_cli_entrypoint.py`

**Test files created:**
- `tests/fixtures/task_with_new_fields.md`

---

## Task 1: Extend Task Model with 8 New Fields

**Files:**
- Modify: `src/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_models.py`:

```python
from src.models import Task, Who, TaskType, TaskIntent
from datetime import datetime


def test_task_defaults_for_new_fields():
    t = Task(
        id="999",
        title="t",
        created=datetime(2026, 4, 27, 9, 0),
        updated=datetime(2026, 4, 27, 9, 0),
    )
    assert t.who == Who.CLAUDE
    assert t.when is None
    assert t.type is None
    assert t.intent is None
    assert t.measure == ""
    assert t.why == ""
    assert t.source_files == []
    assert t.status_reason is None


def test_task_accepts_new_field_values():
    t = Task(
        id="999",
        title="t",
        created=datetime(2026, 4, 27, 9, 0),
        updated=datetime(2026, 4, 27, 9, 0),
        who=Who.HUMAN,
        when="今晚",
        type=TaskType.COMPLEX,
        intent=TaskIntent.RESUME,
        measure="1) tests pass\n2) PR merged",
        why="秋招",
        source_files=["src/a.py", "docs/b.md"],
        status_reason="等用户回应",
    )
    assert t.who == Who.HUMAN
    assert t.when == "今晚"
    assert t.type == TaskType.COMPLEX
    assert t.intent == TaskIntent.RESUME
    assert t.measure == "1) tests pass\n2) PR merged"
    assert t.why == "秋招"
    assert t.source_files == ["src/a.py", "docs/b.md"]
    assert t.status_reason == "等用户回应"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py::test_task_defaults_for_new_fields tests/test_models.py::test_task_accepts_new_field_values -v`
Expected: FAIL with `ImportError: cannot import name 'Who'` (and similar).

- [ ] **Step 3: Write minimal implementation**

In `src/models.py`, add three enums and extend `Task`:

```python
class Who(str, Enum):
    CLAUDE = "claude"
    HUMAN = "human"
    BOTH = "both"


class TaskType(str, Enum):
    SIMPLE = "simple"
    COMPLEX = "complex"


class TaskIntent(str, Enum):
    RESUME = "resume"
    APPROVE = "approve"
    REJECT = "reject"
    PAUSE = "pause"
```

Add to `class Task(BaseModel)`, after `instructions: str = ""` and before `subtasks`:

```python
    who: Who = Who.CLAUDE
    when: Optional[str] = None
    type: Optional[TaskType] = None
    intent: Optional[TaskIntent] = None
    measure: str = ""
    why: str = ""
    source_files: list[str] = Field(default_factory=list)
    status_reason: Optional[str] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/models.py tests/test_models.py
git commit -m "feat(models): add Who/TaskType/TaskIntent enums and 8 new Task fields"
```

---

## Task 2: Parser Reads New Fields

**Files:**
- Modify: `src/board/parser.py`
- Create: `tests/fixtures/task_with_new_fields.md`
- Test: `tests/test_parser.py`

- [ ] **Step 1: Create the fixture file**

Create `tests/fixtures/task_with_new_fields.md`:

```markdown
---
id: "300"
title: 测试新字段
project: pf
parent: null
priority: P1
tags: [a, b]
who: human
when: 本周日
type: complex
intent: null
created: 2026-04-27 10:00
updated: 2026-04-27 10:00
auto_approve: true
depends_on: []
measure: |
  1) 第一条
  2) 第二条
why: 因为
source_files:
  - src/a.py
  - docs/b.md
status_reason: 等用户
instructions: ""
subtasks: []
---

## 任务描述
desc

## 对话
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_parser.py`:

```python
from pathlib import Path
from src.board.parser import parse_task_file
from src.models import Who, TaskType


FIXTURES = Path(__file__).parent / "fixtures"


def test_parser_reads_new_fields():
    task = parse_task_file(FIXTURES / "task_with_new_fields.md")
    assert task.who == Who.HUMAN
    assert task.when == "本周日"
    assert task.type == TaskType.COMPLEX
    assert task.intent is None
    assert task.measure.strip().startswith("1) 第一条")
    assert task.why == "因为"
    assert task.source_files == ["src/a.py", "docs/b.md"]
    assert task.status_reason == "等用户"


def test_parser_falls_back_to_defaults_when_new_fields_missing():
    """Old task files without new fields still parse with defaults."""
    text = """\
---
id: "100"
title: 旧任务
project: ""
parent: null
priority: P1
tags: []
created: 2026-04-26 10:00
updated: 2026-04-26 10:00
auto_approve: true
depends_on: []
instructions: ""
subtasks: []
---

## 任务描述
old

## 对话
"""
    from src.board.parser import parse_task_string
    task = parse_task_string(text)
    assert task.who == Who.CLAUDE
    assert task.when is None
    assert task.type is None
    assert task.intent is None
    assert task.measure == ""
    assert task.why == ""
    assert task.source_files == []
    assert task.status_reason is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_parser.py::test_parser_reads_new_fields tests/test_parser.py::test_parser_falls_back_to_defaults_when_new_fields_missing -v`
Expected: FAIL — Task constructor receives no new-field values.

- [ ] **Step 4: Write minimal implementation**

In `src/board/parser.py`, update the import line:

```python
from src.models import (
    ConversationEntry,
    ConversationRole,
    Priority,
    Subtask,
    SubtaskStatus,
    Task,
    TaskIntent,
    TaskType,
    Who,
)
```

Inside `parse_task_string`, after the `parent_value` line and before the `return Task(...)` call, parse the eight new fields:

```python
    who_value = meta.get("who", "claude") or "claude"
    type_value = meta.get("type")
    intent_value = meta.get("intent")
    source_files = meta.get("source_files", []) or []
    when_value = meta.get("when")
    if when_value == "":
        when_value = None
    status_reason_value = meta.get("status_reason")
    if status_reason_value == "":
        status_reason_value = None
```

Then in the `return Task(...)` call, add:

```python
        who=Who(str(who_value)),
        when=when_value if when_value is None else str(when_value),
        type=TaskType(str(type_value)) if type_value not in (None, "", "null") else None,
        intent=TaskIntent(str(intent_value)) if intent_value not in (None, "", "null") else None,
        measure=str(meta.get("measure", "") or ""),
        why=str(meta.get("why", "") or ""),
        source_files=[str(p) for p in source_files],
        status_reason=status_reason_value if status_reason_value is None else str(status_reason_value),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_parser.py -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/board/parser.py tests/test_parser.py tests/fixtures/task_with_new_fields.md
git commit -m "feat(parser): read 8 new Task fields with defaults for missing keys"
```

---

## Task 3: Writer Emits New Fields with Fixed Order

**Files:**
- Modify: `src/board/writer.py`
- Test: `tests/test_writer.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_writer.py`:

```python
from datetime import datetime
from pathlib import Path
from src.board.parser import parse_task_file
from src.board.writer import write_task_file
from src.models import Task, Who, TaskType, TaskIntent


def test_writer_round_trips_new_fields(tmp_path: Path):
    task = Task(
        id="400",
        title="round trip",
        created=datetime(2026, 4, 27, 9, 0),
        updated=datetime(2026, 4, 27, 10, 0),
        who=Who.BOTH,
        when="明天",
        type=TaskType.SIMPLE,
        intent=TaskIntent.APPROVE,
        measure="1) a\n2) b",
        why="动机",
        source_files=["src/x.py", "docs/y.md"],
        status_reason="阻塞原因",
    )
    target = tmp_path / "400-rt.md"
    write_task_file(task, target)

    reloaded = parse_task_file(target)
    assert reloaded.who == Who.BOTH
    assert reloaded.when == "明天"
    assert reloaded.type == TaskType.SIMPLE
    assert reloaded.intent == TaskIntent.APPROVE
    assert reloaded.measure.strip() == "1) a\n2) b"
    assert reloaded.why == "动机"
    assert reloaded.source_files == ["src/x.py", "docs/y.md"]
    assert reloaded.status_reason == "阻塞原因"


def test_writer_emits_fields_in_fixed_order(tmp_path: Path):
    task = Task(
        id="401",
        title="order",
        created=datetime(2026, 4, 27, 9, 0),
        updated=datetime(2026, 4, 27, 9, 0),
    )
    target = tmp_path / "401.md"
    write_task_file(task, target)
    text = target.read_text(encoding="utf-8")

    expected_order = [
        "id:", "title:", "project:", "parent:", "priority:", "tags:",
        "who:", "when:", "type:", "intent:",
        "created:", "updated:", "auto_approve:", "depends_on:",
        "measure:", "why:", "source_files:", "status_reason:",
        "instructions:", "subtasks:",
    ]
    last_index = -1
    for key in expected_order:
        idx = text.find("\n" + key)
        assert idx > last_index, f"key {key!r} out of order in:\n{text}"
        last_index = idx
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_writer.py -v`
Expected: FAIL — writer does not emit the new keys.

- [ ] **Step 3: Write minimal implementation**

Replace the body of `write_task_file` in `src/board/writer.py` with the new fixed-order emission. The full function:

```python
def write_task_file(task: Task, path: Path) -> None:
    """Write a Task model to a Markdown file."""
    lines: list[str] = []

    lines.append("---")
    lines.append(f'id: "{task.id}"')
    lines.append(f"title: {_quote_yaml_string(task.title)}")
    lines.append(f"project: {_quote_yaml_string(task.project)}")
    if task.parent is not None:
        lines.append(f"parent: {_quote_yaml_string(task.parent)}")
    else:
        lines.append("parent: null")
    lines.append(f"priority: {task.priority.value}")
    lines.append(f"tags: [{', '.join(task.tags)}]")

    # Plan 5b: who / when / type / intent
    lines.append(f"who: {task.who.value}")
    if task.when is None:
        lines.append("when: null")
    else:
        lines.append(f"when: {_quote_yaml_string(task.when)}")
    lines.append(f"type: {task.type.value if task.type else 'null'}")
    lines.append(f"intent: {task.intent.value if task.intent else 'null'}")

    lines.append(f"created: {_format_dt(task.created)}")
    lines.append(f"updated: {_format_dt(task.updated)}")
    lines.append(f"auto_approve: {'true' if task.auto_approve else 'false'}")
    lines.append(f"depends_on: [{', '.join(task.depends_on)}]")

    # Plan 5b: measure / why / source_files / status_reason
    if task.measure:
        if "\n" in task.measure:
            lines.append("measure: |")
            for line in task.measure.split("\n"):
                lines.append(f"  {line}")
        else:
            lines.append(f"measure: {_quote_yaml_string(task.measure)}")
    else:
        lines.append('measure: ""')
    if task.why:
        if "\n" in task.why:
            lines.append("why: |")
            for line in task.why.split("\n"):
                lines.append(f"  {line}")
        else:
            lines.append(f"why: {_quote_yaml_string(task.why)}")
    else:
        lines.append('why: ""')
    if task.source_files:
        lines.append("source_files:")
        for sf in task.source_files:
            lines.append(f"  - {_quote_yaml_string(sf)}")
    else:
        lines.append("source_files: []")
    if task.status_reason is None:
        lines.append("status_reason: null")
    else:
        lines.append(f"status_reason: {_quote_yaml_string(task.status_reason)}")

    if task.instructions:
        if "\n" in task.instructions:
            lines.append("instructions: |")
            for line in task.instructions.split("\n"):
                lines.append(f"  {line}")
        else:
            lines.append(f"instructions: {_quote_yaml_string(task.instructions)}")
    else:
        lines.append('instructions: ""')

    if task.subtasks:
        lines.append("subtasks:")
        for sub in task.subtasks:
            lines.append(f'  - id: "{sub.id}"')
            lines.append(f"    title: {_quote_yaml_string(sub.title)}")
            lines.append(f"    status: {sub.status.value}")
            if sub.blocking_reason:
                lines.append(f"    blocking_reason: {_quote_yaml_string(sub.blocking_reason)}")
    else:
        lines.append("subtasks: []")

    lines.append("---")
    lines.append("")

    lines.append("## 任务描述")
    lines.append(task.description)
    lines.append("")

    lines.append("## 对话")
    lines.append("")
    for entry in task.conversation:
        lines.append(_format_conversation_entry(entry))

    path.write_text("\n".join(lines), encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_writer.py tests/test_parser.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/board/writer.py tests/test_writer.py
git commit -m "feat(writer): emit 8 new Task fields in fixed frontmatter order"
```

---

## Task 4: Update Default Template

**Files:**
- Modify: `tasks/templates/default.md`

- [ ] **Step 1: Replace template content**

Overwrite `tasks/templates/default.md` with:

```markdown
---
id: ""
title: ""
project: ""
parent: null
priority: P1
tags: []
who: human
when: null
type: null
intent: null
created: ""
updated: ""
auto_approve: true
depends_on: []
measure: ""
why: ""
source_files: []
status_reason: null
instructions: ""
subtasks: []
---

## 任务描述


## 对话
```

- [ ] **Step 2: Verify the template parses cleanly**

Run a one-off in Python:

```bash
python -c "from src.board.parser import parse_task_file; from pathlib import Path; t = parse_task_file(Path('tasks/templates/default.md')); print(t.who.value, t.priority.value)"
```
Expected output: `human P1` (or a parse error if the template is malformed).

- [ ] **Step 3: Commit**

```bash
git add tasks/templates/default.md
git commit -m "feat(template): default.md includes 8 new Plan 5b fields"
```

---

## Task 5: BoardManager Adds intent-Driven Move Helpers

**Files:**
- Modify: `src/board/manager.py`
- Test: `tests/test_manager.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_manager.py`:

```python
from src.board.manager import BoardManager
from src.models import TaskIntent, TaskStatus


@pytest.fixture
def empty_board(tmp_path):
    for col in ("backlog", "todo", "doing", "blocked", "review", "done"):
        (tmp_path / col).mkdir()
    return BoardManager(tmp_path)


def _seed(board_root, column, name="x.md", content="x"):
    path = board_root / column / name
    path.write_text(content, encoding="utf-8")
    return path


def test_target_for_intent_resume_from_blocked():
    assert BoardManager.target_status_for_intent(
        TaskIntent.RESUME, TaskStatus.BLOCKED
    ) == TaskStatus.DOING


def test_target_for_intent_approve_from_review():
    assert BoardManager.target_status_for_intent(
        TaskIntent.APPROVE, TaskStatus.REVIEW
    ) == TaskStatus.DONE


def test_target_for_intent_reject_from_review():
    assert BoardManager.target_status_for_intent(
        TaskIntent.REJECT, TaskStatus.REVIEW
    ) == TaskStatus.TODO


def test_target_for_intent_pause_from_doing():
    assert BoardManager.target_status_for_intent(
        TaskIntent.PAUSE, TaskStatus.DOING
    ) == TaskStatus.BACKLOG


def test_target_for_intent_invalid_combo_returns_none():
    # resume from todo is meaningless
    assert BoardManager.target_status_for_intent(
        TaskIntent.RESUME, TaskStatus.TODO
    ) is None
```

(`pytest` and the existing `empty_board` fixture style are already in `tests/test_manager.py`; if `pytest` is not imported at the top of the file, add `import pytest`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_manager.py -v -k intent`
Expected: FAIL — `target_status_for_intent` not defined.

- [ ] **Step 3: Write minimal implementation**

Append to `src/board/manager.py`:

```python
from src.models import TaskIntent
```

(adjust the existing `from src.models import TaskStatus` to include TaskIntent in one line.)

Inside `class BoardManager`, add the static lookup:

```python
    _INTENT_TARGET = {
        (TaskIntent.RESUME, TaskStatus.BLOCKED): TaskStatus.DOING,
        (TaskIntent.APPROVE, TaskStatus.REVIEW): TaskStatus.DONE,
        (TaskIntent.REJECT, TaskStatus.REVIEW): TaskStatus.TODO,
        (TaskIntent.PAUSE, TaskStatus.DOING): TaskStatus.BACKLOG,
    }

    @classmethod
    def target_status_for_intent(
        cls, intent: TaskIntent, current: TaskStatus
    ) -> "TaskStatus | None":
        """Return the target column for an intent applied at the current column.

        Returns None if the (intent, current) combination is not valid (e.g. user
        set intent: resume on a task already in todo/). Caller should clear the
        intent and log a warning in that case.
        """
        return cls._INTENT_TARGET.get((intent, current))
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_manager.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/board/manager.py tests/test_manager.py
git commit -m "feat(board): BoardManager.target_status_for_intent maps intent+column to target"
```

---

## Task 6: Orchestrator intent Mechanical Path + who Filter

**Files:**
- Modify: `src/agent/orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_orchestrator.py`. The test setup mirrors the existing helpers in that file (a fake LLM, a tmp tasks_dir, etc.). The new tests exercise the short-circuit paths:

```python
from datetime import datetime
from src.agent.orchestrator import Orchestrator
from src.board.writer import write_task_file
from src.models import Task, TaskIntent, TaskStatus, Who


def _seed_task(tasks_dir, column, task_id="500", **overrides):
    """Write a Task into the given column folder; returns the path."""
    base = dict(
        id=task_id,
        title=f"task-{task_id}",
        created=datetime(2026, 4, 27, 9, 0),
        updated=datetime(2026, 4, 27, 9, 0),
    )
    base.update(overrides)
    task = Task(**base)
    path = tasks_dir / column / f"{task_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_task_file(task, path)
    return path


@pytest.mark.asyncio
async def test_orchestrator_skips_when_who_is_human(orchestrator_factory, tmp_path):
    # `orchestrator_factory` is the existing fixture that returns an Orchestrator
    # bound to tmp_path. If your test file uses a different name, adapt this.
    orch = orchestrator_factory()
    path = _seed_task(tmp_path, "todo", who=Who.HUMAN)

    await orch.run_cycle(path)

    # Task remains in todo (no LLM, no move)
    assert path.exists()


@pytest.mark.asyncio
async def test_orchestrator_resumes_blocked_to_doing_via_intent(
    orchestrator_factory, tmp_path
):
    orch = orchestrator_factory()
    path = _seed_task(tmp_path, "blocked", intent=TaskIntent.RESUME)

    await orch.run_cycle(path)

    assert not path.exists()
    moved = tmp_path / "doing" / "500.md"
    assert moved.exists()
    # intent should be cleared after the move
    from src.board.parser import parse_task_file
    reloaded = parse_task_file(moved)
    assert reloaded.intent is None


@pytest.mark.asyncio
async def test_orchestrator_clears_invalid_intent_combo(
    orchestrator_factory, tmp_path
):
    orch = orchestrator_factory()
    # resume from todo is invalid
    path = _seed_task(tmp_path, "todo", intent=TaskIntent.RESUME, who=Who.HUMAN)

    await orch.run_cycle(path)

    # File stays put
    assert path.exists()
    # intent is cleared
    from src.board.parser import parse_task_file
    reloaded = parse_task_file(path)
    assert reloaded.intent is None
```

If `orchestrator_factory` is not the actual fixture name in `tests/test_orchestrator.py`, find the existing fixture/helper that builds an Orchestrator with a fake LLM and use that name instead. Do not write a new fixture from scratch unless none exists.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator.py -v -k "skips_when_who_is_human or resumes_blocked or clears_invalid_intent"`
Expected: FAIL — `run_cycle` does not yet special-case `who` or `intent`.

- [ ] **Step 3: Write minimal implementation**

In `src/agent/orchestrator.py`:

(a) Update the import block:

```python
from src.models import (
    ConversationEntry,
    ConversationRole,
    LogEntry,
    Task,
    TaskIntent,
    TaskStatus,
    Who,
)
```

(b) Restructure the head of `run_cycle` so parse + Plan 5b checks happen **before** the existing DONE/REVIEW short-circuit (otherwise `intent: approve` on a review/ task would never fire). Replace the block:

```python
        try:
            current_status = self._status_from_path(path)
            if current_status in (TaskStatus.DONE, TaskStatus.REVIEW):
                return

            task = parse_task_file(path)
            self.logger.log(LogEntry(
                task_id=task.id, action="cycle_start",
                detail=f"status={current_status.value}",
            ))
```

with:

```python
        try:
            current_status = self._status_from_path(path)
            task = parse_task_file(path)

            # Plan 5b: intent mechanical action — no LLM call.
            # Must run BEFORE the DONE/REVIEW short-circuit so that
            # `intent: approve` on review/ and similar combos can fire.
            if task.intent is not None:
                self._apply_intent(path, task, current_status)
                return

            # Plan 5b: skip cycle when task is not assigned to AI.
            if task.who != Who.CLAUDE:
                self.logger.log(LogEntry(
                    task_id=task.id, action="cycle_skipped",
                    detail=f"who={task.who.value}",
                ))
                return

            if current_status in (TaskStatus.DONE, TaskStatus.REVIEW):
                return

            self.logger.log(LogEntry(
                task_id=task.id, action="cycle_start",
                detail=f"status={current_status.value}",
            ))
```

(c) Add the `_apply_intent` method below `_decide_next_status`:

```python
    def _apply_intent(
        self, path: Path, task: Task, current_status: TaskStatus
    ) -> None:
        """Mechanical action: clear intent, move file if combo is valid, log.

        No LLM call. No conversation append. Pure file shuffling driven by the
        user's frontmatter edit.
        """
        from src.board.writer import write_task_file

        target = self.manager.target_status_for_intent(task.intent, current_status)
        intent_value = task.intent.value
        task.intent = None

        with self.suppress_self():
            write_task_file(task, path)
            if target is None:
                self.logger.log(LogEntry(
                    task_id=task.id,
                    action="intent_invalid",
                    detail=f"intent={intent_value} from={current_status.value}",
                    status="error",
                ))
                return
            new_path = self.manager.move_task(path, target)
            self.logger.log(LogEntry(
                task_id=task.id,
                action="intent_applied",
                detail=(
                    f"intent={intent_value} "
                    f"{current_status.value}->{target.value} path={new_path}"
                ),
            ))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_orchestrator.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): intent mechanical path and who-filter short-circuits"
```

---

## Task 7: Watcher IGNORE_PATTERNS

**Files:**
- Modify: `src/dispatcher/watcher.py`
- Test: `tests/test_watcher.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_watcher.py`:

```python
def test_watcher_ignores_obsidian_internal_files(tmp_path):
    """Files inside .obsidian/, _attachments/, .trash/, templates/, and
    Obsidian Sync conflict files must not trigger the callback."""
    from src.dispatcher.watcher import FileWatcher

    seen: list[Path] = []
    w = FileWatcher(tmp_path, on_change=lambda p: seen.append(p), debounce_seconds=0.1)
    w.start()
    try:
        for col in ("doing", ".obsidian", "_attachments", ".trash", "templates"):
            (tmp_path / col).mkdir(parents=True, exist_ok=True)
        # legitimate edit
        (tmp_path / "doing" / "025.md").write_text("a", encoding="utf-8")
        # noise edits — should be ignored
        (tmp_path / ".obsidian" / "workspace.json").write_text("a", encoding="utf-8")
        (tmp_path / "_attachments" / "img.png").write_text("a", encoding="utf-8")
        (tmp_path / ".trash" / "old.md").write_text("a", encoding="utf-8")
        (tmp_path / "templates" / "default.md").write_text("a", encoding="utf-8")
        # Obsidian Sync conflict file
        (tmp_path / "doing" / "025 (conflict 2026-04-27 12:00).md").write_text(
            "a", encoding="utf-8"
        )

        time.sleep(0.5)
    finally:
        w.stop()

    seen_names = [p.name for p in seen]
    assert "025.md" in seen_names
    # Everything else must be filtered out
    for noise in (
        "workspace.json", "img.png", "old.md", "default.md",
        "025 (conflict 2026-04-27 12:00).md",
    ):
        assert noise not in seen_names, f"watcher should ignore {noise}"
```

(`time` and `Path` imports likely already exist in `tests/test_watcher.py`. Add if missing.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_watcher.py -v -k ignores_obsidian`
Expected: FAIL — at least one of the noise files leaks through.

- [ ] **Step 3: Write minimal implementation**

In `src/dispatcher/watcher.py`, add a module-level constant near the top (after imports):

```python
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


def _is_ignored(path: Path) -> bool:
    p = str(path)
    if any(frag in p for frag in _IGNORE_PATH_FRAGMENTS):
        return True
    # Obsidian Sync conflict files: "<name> (conflict YYYY-MM-DD HH:MM:SS).md"
    if " (conflict " in path.name:
        return True
    return False
```

In `FileWatcher._on_event`, after the existing `.md` suffix check, add:

```python
        if _is_ignored(path):
            return
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_watcher.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dispatcher/watcher.py tests/test_watcher.py
git commit -m "feat(watcher): ignore .obsidian/, _attachments/, conflict files, and templates"
```

---

## Task 8: Surface measure / why / source_files in LLM Context

**Files:**
- Modify: `src/agent/context.py`
- Test: `tests/test_context_builder.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_context_builder.py`:

```python
from datetime import datetime
from src.agent.context import ContextBuilder
from src.models import Task, Who


def _bare_task(**overrides):
    base = dict(
        id="600", title="ctx",
        created=datetime(2026, 4, 27, 9, 0),
        updated=datetime(2026, 4, 27, 9, 0),
    )
    base.update(overrides)
    return Task(**base)


def test_context_includes_why_section():
    task = _bare_task(why="为了秋招用")
    msgs = ContextBuilder().build("rules", task)
    user_text = msgs[1].content
    assert "## Motivation (why)" in user_text
    assert "为了秋招用" in user_text


def test_context_includes_measure_section():
    task = _bare_task(measure="1) 部署成功\n2) lighthouse >= 90")
    msgs = ContextBuilder().build("rules", task)
    user_text = msgs[1].content
    assert "## Success Criteria (measure)" in user_text
    assert "1) 部署成功" in user_text


def test_context_includes_source_files_list():
    task = _bare_task(source_files=["src/a.py", "docs/b.md"])
    msgs = ContextBuilder().build("rules", task)
    user_text = msgs[1].content
    assert "## Source Files" in user_text
    assert "src/a.py" in user_text
    assert "docs/b.md" in user_text


def test_context_omits_empty_new_sections():
    task = _bare_task()
    msgs = ContextBuilder().build("rules", task)
    user_text = msgs[1].content
    assert "## Motivation" not in user_text
    assert "## Success Criteria" not in user_text
    assert "## Source Files" not in user_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_context_builder.py -v -k "why_section or measure_section or source_files_list or omits_empty"`
Expected: FAIL — `_build_user` does not emit these sections.

- [ ] **Step 3: Write minimal implementation**

In `src/agent/context.py`, inside `_build_user`, after the existing "Description" block and before "Subtasks":

```python
        if task.why and task.why.strip():
            lines.append("## Motivation (why)")
            lines.append(task.why.rstrip())
            lines.append("")

        if task.measure and task.measure.strip():
            lines.append("## Success Criteria (measure)")
            lines.append(task.measure.rstrip())
            lines.append("Self-check against each item before calling mark_complete.")
            lines.append("")

        if task.source_files:
            lines.append("## Source Files")
            lines.append("These files are pre-read context for this task:")
            for sf in task.source_files:
                lines.append(f"- `{sf}`")
            lines.append("")
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_context_builder.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent/context.py tests/test_context_builder.py
git commit -m "feat(context): surface why/measure/source_files in LLM user message"
```

---

## Task 9: Notifier Deep-Link Support

**Files:**
- Modify: `src/tools/notifier.py`
- Test: `tests/test_tool_notifier.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tool_notifier.py`:

```python
import pytest
from src.tools.notifier import NotifierTool


@pytest.mark.asyncio
async def test_notifier_sends_markdown_msgtype_when_deep_link_provided(
    httpx_mock_transport,  # existing fixture; if name differs, adapt
):
    seen_payloads: list[dict] = []

    def capture(request):
        import json
        seen_payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"errcode": 0})

    transport = httpx.MockTransport(capture)
    tool = NotifierTool(webhook_url="http://test", transport=transport)
    result = await tool.execute(
        message="任务被卡住",
        deep_link="obsidian://open?vault=cc-assistant&file=blocked/036.md",
    )
    assert result.success
    payload = seen_payloads[0]
    assert payload["msgtype"] == "markdown"
    content = payload["markdown"]["content"]
    assert "任务被卡住" in content
    assert "obsidian://open?vault=cc-assistant&file=blocked/036.md" in content


@pytest.mark.asyncio
async def test_notifier_falls_back_to_text_when_no_deep_link():
    import httpx, json
    seen: list[dict] = []
    transport = httpx.MockTransport(
        lambda r: (seen.append(json.loads(r.content)),
                   httpx.Response(200, json={"errcode": 0}))[1]
    )
    tool = NotifierTool(webhook_url="http://test", transport=transport)
    result = await tool.execute(message="hi")
    assert result.success
    assert seen[0]["msgtype"] == "text"
```

(If the existing test file already imports `httpx` and `json` and has helpers, use those instead of adding redundant imports. Match style of existing tests there.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tool_notifier.py -v -k "deep_link or markdown_msgtype or falls_back_to_text"`
Expected: FAIL — `deep_link` parameter not accepted; payload always uses `msgtype: text`.

- [ ] **Step 3: Write minimal implementation**

In `src/tools/notifier.py`:

(a) Extend `parameters_schema`:

```python
    parameters_schema = {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
            "mentioned": {
                "type": "array",
                "description": "Optional list of WeChat user IDs to mention.",
            },
            "deep_link": {
                "type": "string",
                "description": (
                    "Optional URL — when set, the notification is sent as a "
                    "markdown message with the link inlined."
                ),
            },
        },
        "required": ["message"],
    }
```

(b) Replace the body construction in `execute`:

```python
        deep_link = params.get("deep_link")
        body: dict[str, Any]
        if deep_link:
            md_content = f"{message}\n\n[打开任务]({deep_link})"
            body = {
                "msgtype": "markdown",
                "markdown": {"content": md_content},
            }
        else:
            body = {
                "msgtype": "text",
                "text": {"content": message},
            }
            mentioned = params.get("mentioned")
            if mentioned:
                body["text"]["mentioned_list"] = list(mentioned)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_tool_notifier.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tools/notifier.py tests/test_tool_notifier.py
git commit -m "feat(notifier): deep_link parameter sends markdown msgtype with inline link"
```

---

## Task 10: Retire src/dispatcher/sync.py

**Files:**
- Delete: `src/dispatcher/sync.py`
- Delete: `src/agent/_noop_sync.py`
- Delete: `tests/test_sync.py`
- Modify: `src/agent/orchestrator.py`
- Modify: `src/agent/factory.py`
- Modify: `src/dispatcher/coordinator.py`
- Modify: `tests/test_orchestrator.py` / `tests/test_orchestrator_integration.py` / `tests/test_dispatcher_integration.py` (any file that constructs Orchestrator or Coordinator with sync/repo_dir args)

- [ ] **Step 1: Remove `sync` from Orchestrator construction and `commit_and_push` call**

In `src/agent/orchestrator.py`:

(a) Remove the import:

```python
# DELETE this line:
from src.dispatcher.sync import GitSync
```

(b) Remove the `sync` parameter from `__init__`:

```python
    def __init__(
        self,
        tasks_dir: Path,
        skills_dir: Path,
        logs_dir: Path,
        llm: LLMClient,
        tools: list[Tool],
        suppress_self: Callable[[], AbstractContextManager],
    ) -> None:
        self.tasks_dir = tasks_dir
        # ... existing assignments ...
        # DELETE: self.sync = sync
```

(c) In `run_cycle`, remove the line:

```python
                    self.sync.commit_and_push(
                        f"agent: {task.id} {current_status.value}->{next_status.value}"
                    )
```

- [ ] **Step 2: Remove sync from Coordinator and factory**

In `src/dispatcher/coordinator.py`:

(a) Remove `from src.dispatcher.sync import GitSync`.
(b) Remove `repo_dir`, `git_pull_interval_seconds`, `DEFAULT_GIT_PULL_INTERVAL_SECONDS` from class.
(c) Delete `self.sync = GitSync(...)` from `__init__`.
(d) Delete the `git_pull` job registration in `start`:

```python
        # DELETE:
        self.scheduler.add_job(self.sync.pull, self._git_pull_interval_seconds, job_id="git_pull")
```

In `src/agent/factory.py`:

(a) Delete `from src.agent._noop_sync import NoopSync`.
(b) Drop the `repo_dir` parameter from `build_orchestrator_and_coordinator` and remove `repo_dir=...` from the `DispatcherCoordinator(...)` call.
(c) Drop `git_pull_interval_seconds` from the signature and the call.
(d) Drop `sync=...` from the `Orchestrator(...)` call (both factories).

- [ ] **Step 3: Delete the dead files**

```bash
git rm src/dispatcher/sync.py
git rm src/agent/_noop_sync.py
git rm tests/test_sync.py
```

- [ ] **Step 4: Adjust callers**

In `src/cli.py`, find any call to `build_orchestrator_and_coordinator(...)` that passes `repo_dir=` and remove that argument.

In test files, search for places that construct Orchestrator or Coordinator with `sync=` or `repo_dir=` and remove those:

```bash
grep -rn "repo_dir=\|sync=NoopSync\|sync=GitSync" src/ tests/
```

Each match: drop the kwarg.

- [ ] **Step 5: Run the full test suite**

Run: `pytest -q`
Expected: all tests PASS. Total count drops by however many `test_sync.py` tests existed (replace nothing).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: remove src/dispatcher/sync.py and git auto-sync from daemon

Obsidian Sync replaces git as the cross-device transport for tasks/.
Drops GitSync, NoopSync, the git_pull scheduled job, and repo_dir wiring
from the orchestrator/coordinator/factory call chains."
```

---

## Task 11: Vault Initialization Files

**Files:**
- Create: `tasks/.gitignore`
- Create: `tasks/README.md`
- Modify: `.gitignore` (repo root)

- [ ] **Step 1: Create tasks/.gitignore**

Write `tasks/.gitignore`:

```
.obsidian/workspace.json
.obsidian/workspace-mobile.json
.obsidian/cache
.trash/
```

- [ ] **Step 2: Create tasks/README.md**

Write `tasks/README.md`:

```markdown
# cc-assistant 任务看板

这是 cc-assistant 的 Obsidian vault。

- 看板视图：打开 `views.base`。
- 新任务：从 `templates/default.md` 复制到 `backlog/` 或 `todo/`。
- 状态由所在文件夹决定：`backlog/` `todo/` `doing/` `blocked/` `review/` `done/`。

## 在手机上换列

不要拖文件，直接改 frontmatter 的 `intent` 字段：

| 当前列 | 设 intent | daemon 移动到 |
|---|---|---|
| `blocked/` | `resume` | `doing/` |
| `review/` | `approve` | `done/YYYY-MM/` |
| `review/` | `reject` | `todo/` |
| `doing/` | `pause` | `backlog/` |

设完保存即可，daemon 会清掉 intent 并完成移动。

## 这个 vault 由谁同步

- markdown 任务文件：Obsidian Sync（云中转）
- `.obsidian/` 配置 / `views.base`：进 git，跨设备复现
- `_attachments/`：Obsidian Sync（不进 git）
```

- [ ] **Step 3: Append to repo-root .gitignore**

Append the following block to the existing `.gitignore` at repo root (do not duplicate existing entries):

```
# Plan 5b: attachments handled by Obsidian Sync, not git
tasks/_attachments/
```

- [ ] **Step 4: Commit**

```bash
git add tasks/.gitignore tasks/README.md .gitignore
git commit -m "chore(vault): seed tasks/.gitignore, README, and exclude _attachments"
```

---

## Task 12: Bases Configuration File

**Files:**
- Create: `tasks/views.base`

- [ ] **Step 1: Write the Bases YAML**

Write `tasks/views.base`. This is the shipped default; the user adjusts in Obsidian if they want.

```yaml
filters:
  not:
    file.folder.contains:
      - "templates"
      - "_attachments"

formulas:
  status: file.folder

views:
  - type: board
    name: 看板
    group_by: status
    columns:
      - backlog
      - todo
      - doing
      - blocked
      - review
      - done
    sort:
      - priority
      - "-created"
    card:
      title: title
      badges:
        - priority
        - who
      footer: when

  - type: list
    name: 谁等我
    filter:
      or:
        - status_reason.is_not_empty: true
        - who:
            in:
              - human
              - both
    sort:
      - priority

  - type: list
    name: 按 project
    group_by: project
    filter:
      not:
        status: done

  - type: list
    name: 本周
    filter:
      when.contains_any:
        - "今天"
        - "明天"
        - "本周"
        - "本周日"
```

**Note:** Bases syntax is still evolving. If Obsidian on first open reports a parse error, adjust the keys to match the current Bases docs (https://help.obsidian.md/bases). The four views are the contract; their exact YAML syntax is not.

- [ ] **Step 2: Verify (manual)**

Open `tasks/` in Obsidian desktop. Open `views.base`. Confirm at least the 看板 view renders without errors. Adjust YAML and repeat until it parses.

- [ ] **Step 3: Commit**

```bash
git add tasks/views.base
git commit -m "feat(vault): ship default Bases views (看板/谁等我/按 project/本周)"
```

---

## Task 13: CLI Startup Health Checks

**Files:**
- Modify: `src/cli.py`
- Modify: `src/config.py`
- Modify: `pyproject.toml` (add `psutil`)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Add psutil to dependencies**

In `pyproject.toml`, under `[project] dependencies`, append `"psutil>=5.9"` (or whatever the existing version pin style is). Then:

```bash
uv sync
```

- [ ] **Step 2: Add `obsidian_vault_name` to config**

In `src/config.py`, after `wechat_webhook_url`, add:

```python
    # Obsidian
    obsidian_vault_name: str = "cc-assistant"
    obsidian_check_process: bool = True   # set false in tests / headless setups
```

- [ ] **Step 3: Write the failing test**

Append to `tests/test_cli.py`:

```python
def test_cli_run_warns_when_vault_not_initialized(tmp_path, monkeypatch, capsys):
    """If tasks/.obsidian/ does not exist, cmd_run logs a warning but proceeds."""
    from src import cli
    # tasks dir exists but .obsidian/ does not
    (tmp_path / "tasks" / "todo").mkdir(parents=True)
    monkeypatch.setattr(cli.config, "tasks_dir", tmp_path / "tasks")
    monkeypatch.setattr(cli.config, "obsidian_check_process", False)

    warnings = cli.run_startup_checks(cli.config)
    assert any("vault not initialized" in w.lower() for w in warnings)


def test_cli_run_no_warning_when_vault_initialized(tmp_path, monkeypatch):
    from src import cli
    (tmp_path / "tasks" / ".obsidian").mkdir(parents=True)
    (tmp_path / "tasks" / "todo").mkdir()
    monkeypatch.setattr(cli.config, "tasks_dir", tmp_path / "tasks")
    monkeypatch.setattr(cli.config, "obsidian_check_process", False)

    warnings = cli.run_startup_checks(cli.config)
    assert not any("vault not initialized" in w.lower() for w in warnings)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v -k "warns_when_vault_not_initialized or no_warning_when_vault_initialized"`
Expected: FAIL — `cli.run_startup_checks` does not exist.

- [ ] **Step 5: Write minimal implementation**

In `src/cli.py`, add a top-level helper:

```python
def run_startup_checks(cfg) -> list[str]:
    """Return a list of human-readable warnings; empty if all OK.

    Plan 5b: ensure (a) the Obsidian vault is initialized at tasks/.obsidian/,
    and (b) the Obsidian desktop process is running so Sync can land bytes.
    Both checks are warnings, not failures — the daemon is allowed to start
    without Obsidian (e.g. for dry-run or headless testing).
    """
    warnings: list[str] = []
    vault_marker = cfg.tasks_dir / ".obsidian"
    if not vault_marker.exists():
        warnings.append(
            "Vault not initialized: open `tasks/` in Obsidian once to create "
            ".obsidian/ before relying on Sync."
        )
    if cfg.obsidian_check_process:
        try:
            import psutil
            running = any(
                "obsidian" in (p.info.get("name") or "").lower()
                for p in psutil.process_iter(["name"])
            )
            if not running:
                warnings.append(
                    "Obsidian desktop process not detected; Obsidian Sync "
                    "cannot land changes on disk while the app is closed."
                )
        except Exception:
            # psutil failures should not block startup
            pass
    return warnings
```

In `cmd_run` (the function `cc-assistant run` dispatches to), after the existing pre-flight code and before `start_daemon(...)`, insert:

```python
    for w in run_startup_checks(config):
        print(f"[warn] {w}", file=sys.stderr)
```

(`config` is already imported at module top per existing code; `sys` may need `import sys` added.)

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_cli.py -v`
Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/cli.py src/config.py tests/test_cli.py pyproject.toml uv.lock
git commit -m "feat(cli): startup checks for vault init and Obsidian process"
```

---

## Task 14: Wire deep_link Into Orchestrator's Block Notifications

**Files:**
- Modify: `src/agent/tool_bridge.py` or wherever the orchestrator builds notifier args (locate via grep)
- Test: existing orchestrator tests

This task connects the new `deep_link` parameter from Task 9 to the actual notification path.

- [ ] **Step 1: Locate where notifier is invoked from the orchestrator path**

Run: `grep -rn "notifier" src/agent src/tools tests/ | grep -v __pycache__`

Expected: a tool-call site (likely the LLM emits a `notifier` tool call). The orchestrator does not call notifier directly — the LLM does, via `ToolBridge.dispatch`. There is no orchestrator-side wrapper to change.

**Conclusion:** the `deep_link` is filled in by the LLM when it decides to send a notification. To make this work in practice, the system prompt or `rules.md` must mention that `deep_link` exists and what URL to use. Update the rules-loading or system prompt accordingly.

- [ ] **Step 2: Document `deep_link` usage in skills/rules.md**

Open `skills/rules.md` (Plan 4 created this; if absent, create with at least the section below). Add a new section, e.g. between the existing routing table and failure table:

```markdown
## 通知规则

当你调用 `notifier` 工具且任务即将进入 `blocked/` 或 `review/`，**总是**附带 `deep_link` 参数，格式：

    obsidian://open?vault=<vault_name>&file=<column>/<task_id>-<slug>.md

`vault_name` 来自配置（默认 `cc-assistant`）。这样手机收到通知时点击就能跳到任务卡片。
```

**Note:** the LLM does not know the runtime `vault_name`. Either (a) inject it into the system prompt at context build time, or (b) hardcode `cc-assistant` in the rules. The simpler v1 path is (b). If the user later changes vault names, update `rules.md`.

- [ ] **Step 3: Add a vault-name snippet to ContextBuilder system prompt**

In `src/agent/context.py`, edit `_build_system` to interpolate the vault name:

```python
    @staticmethod
    def _build_system(rules: str, vault_name: str = "cc-assistant") -> str:
        prefix = f"_(Obsidian vault name: `{vault_name}`)_\n\n"
        if rules.strip():
            return prefix + f"{rules.rstrip()}\n\n{_SYSTEM_AGENT_INSTRUCTIONS}"
        return prefix + _SYSTEM_AGENT_INSTRUCTIONS
```

And update `build` to accept and forward it:

```python
    def build(self, rules: str, task: Task, vault_name: str = "cc-assistant") -> list[Message]:
        system_text = self._build_system(rules, vault_name)
        user_text = self._build_user(task)
        return [
            Message(role="system", content=system_text),
            Message(role="user", content=user_text),
        ]
```

In `src/agent/orchestrator.py`, where `context_builder.build(rules, task)` is called (inside `_run_llm_loop`), pass the vault name from config:

```python
        from src.config import config
        messages = self.context_builder.build(rules, task, vault_name=config.obsidian_vault_name)
```

- [ ] **Step 4: Update existing context_builder tests that assert on system message**

If any test in `tests/test_context_builder.py` asserts the exact contents of the system message, update them to expect the `_(Obsidian vault name: ...)_` prefix.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_context_builder.py tests/test_orchestrator.py -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add skills/rules.md src/agent/context.py src/agent/orchestrator.py tests/test_context_builder.py
git commit -m "feat(rules,context): inject vault name into system prompt and require deep_link in notifier calls"
```

---

## Task 15: Source-Files Pre-Read Pass

**Files:**
- Modify: `src/agent/orchestrator.py`
- Test: `tests/test_orchestrator.py`

The spec calls for `source_files` to be pre-read so the LLM has them in context without using a tool call round.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_orchestrator.py`:

```python
@pytest.mark.asyncio
async def test_orchestrator_preloads_source_files_into_context(
    orchestrator_factory, tmp_path, capture_llm_messages
):
    """When task.source_files is set, the user message includes their contents."""
    src_a = tmp_path / "a.txt"
    src_a.write_text("HELLO_A_CONTENT", encoding="utf-8")
    path = _seed_task(
        tmp_path, "doing", task_id="700",
        source_files=[str(src_a.resolve())],
    )

    orch = orchestrator_factory(messages_capture=capture_llm_messages)
    await orch.run_cycle(path)

    user_msg = capture_llm_messages[-1][1].content
    assert "HELLO_A_CONTENT" in user_msg
```

`capture_llm_messages` is a placeholder for the existing test fixture / fake LLM that records the messages it was called with. If your test file uses a different name, adapt accordingly. If no such helper exists, the simpler test is to assert against the `Task` passed to a stub `ContextBuilder`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator.py -v -k preloads_source_files`
Expected: FAIL — source files are not yet read.

- [ ] **Step 3: Write minimal implementation**

In `src/agent/orchestrator.py`, modify `_run_llm_loop` to pre-read source files and inject them as an additional user message before calling the LLM:

```python
    async def _run_llm_loop(
        self, task: Task, dry_run: bool = False
    ) -> tuple[str, CycleState]:
        rules = self.rules.load()
        from src.config import config as _cfg
        messages = self.context_builder.build(
            rules, task, vault_name=_cfg.obsidian_vault_name
        )

        # Plan 5b: pre-read source_files and append as user message
        if task.source_files:
            preload = self._read_source_files(task.source_files)
            if preload:
                messages.append(Message(role="user", content=preload))

        tool_defs = self.bridge.tool_definitions()
        # ... rest unchanged
```

Add the helper method:

```python
    @staticmethod
    def _read_source_files(paths: list[str], max_bytes_each: int = 50_000) -> str:
        """Pre-read source files referenced by the task into a single text block.

        Each file is truncated to `max_bytes_each` to avoid blowing the context
        window on a forgotten 100 MB log file.
        """
        from pathlib import Path
        chunks: list[str] = ["## Pre-read source files"]
        for raw in paths:
            p = Path(raw)
            if not p.exists():
                chunks.append(f"### `{raw}` — (not found)")
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                chunks.append(f"### `{raw}` — (read error: {e})")
                continue
            if len(text) > max_bytes_each:
                text = text[:max_bytes_each] + f"\n\n[...truncated at {max_bytes_each} bytes]"
            chunks.append(f"### `{raw}`\n```\n{text}\n```")
        return "\n\n".join(chunks)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_orchestrator.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): pre-read task.source_files into LLM context"
```

---

## Task 16: End-to-End Manual Smoke Test

**Files:**
- None (this is a test, not code)

This task is a manual smoke test. It does not produce a commit. It verifies the seven layers cooperate end-to-end on a real Obsidian Sync round trip.

- [ ] **Step 1: Initialize the vault on desktop**

```bash
cd <your-user>/projects/cc-assitant
# Open Obsidian, "Open folder as vault", point at the tasks/ directory
# Confirm Obsidian created tasks/.obsidian/
ls tasks/.obsidian
```

Expected: `app.json`, `core-plugins.json`, `workspace.json`.

- [ ] **Step 2: Configure Obsidian Sync**

In Obsidian: Settings → Sync → set up the vault as a Sync remote. Wait for first sync to complete on desktop.

On phone: install Obsidian, sign into the same account, pull the `cc-assistant` vault.

- [ ] **Step 3: Verify deep link works**

On desktop, write a fake notifier output:
```
obsidian://open?vault=cc-assistant&file=todo/sample.md
```
Open this URL on the phone (paste into a chat / browser). Expected: Obsidian opens the file (or shows "file not found" if no such file).

- [ ] **Step 4: Run the daemon**

```bash
cc-assistant run
```

Expected: no errors. If `tasks/.obsidian/` is missing (it should not be after Step 1), expect a `[warn] Vault not initialized` line.

- [ ] **Step 5: Phone -> daemon roundtrip via intent**

(a) On desktop, manually create `tasks/blocked/test-001.md` from the template, set `intent: null`, save.
(b) Wait for sync to phone (~3s).
(c) On phone, open the file, change `intent: null` to `intent: resume`, save.
(d) Wait for sync back to desktop (~3s).
(e) Confirm: file moved from `tasks/blocked/` to `tasks/doing/`, and `intent` is back to `null` in the moved file.

If the move does not happen, check `logs/agent.jsonl` for `intent_applied` or `intent_invalid` entries. A common failure is that the desktop Obsidian app is not running, in which case Sync queues the change but never lands it — restart Obsidian and the move should happen.

- [ ] **Step 6: Document results**

Write a short note (no commit needed) of which Obsidian / Bases version was used and any UI quirks for future reference.

---

## Self-Review Checklist

After completing all tasks, run from repo root:

- [ ] `pytest -q` — all tests green
- [ ] `git log --oneline | head -20` — sane commit history
- [ ] `grep -rn "GitSync\|NoopSync\|repo_dir=\|git_pull" src/ tests/` — should be empty
- [ ] Manually open `tasks/views.base` in Obsidian — at least 看板 view renders
- [ ] Phone → desktop intent roundtrip works (Task 16 Step 5)

If any of those fail, fix in place and recommit.
