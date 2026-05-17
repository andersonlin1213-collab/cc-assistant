# Plan 1: Foundation & Board Layer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Set up the project skeleton and implement the task board layer — parsing, writing, and managing six-column Markdown task files (backlog/todo/doing/blocked/review/done) with YAML frontmatter (including `project`, `parent`, `instructions`, subtask `blocking_reason`), conversation threads, JSONL logging, and a rules loader for `skills/rules.md`.

**Architecture:** Python package with Pydantic models defining the data structures, a parser that reads Markdown task files into typed objects, a writer that updates them, a manager that moves files between six status directories, a rules loader that reads the human-editable `skills/rules.md`, and a JSONL logger for traceability. Everything is async-ready.

**Tech Stack:** Python 3.11+, uv, pydantic, pydantic-settings, python-frontmatter, python-dotenv, pytest, pytest-asyncio

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `pyproject.toml` | Project config, dependencies |
| Create | `.env.example` | Environment variable template |
| Create | `.gitignore` | Git ignore rules |
| Create | `src/__init__.py` | Package root |
| Create | `src/config.py` | Load .env, expose typed settings |
| Create | `src/models.py` | Pydantic models: Task, Subtask, ConversationEntry, LogEntry, enums (6-column TaskStatus, SubtaskStatus with BLOCKED) |
| Create | `src/board/__init__.py` | Board package |
| Create | `src/board/parser.py` | Parse .md task file → Task model (handles project/parent/instructions/blocking_reason) |
| Create | `src/board/writer.py` | Write Task model → .md file, append conversation |
| Create | `src/board/manager.py` | Move files across 6 status dirs, archive done tasks by month |
| Create | `src/rules/__init__.py` | Rules package |
| Create | `src/rules/loader.py` | Load `skills/rules.md` content for Agent context |
| Create | `src/logging/__init__.py` | Logging package |
| Create | `src/logging/structured.py` | JSONL structured logger |
| Create | `skills/rules.md` | Human-editable Agent behavior rules (template) |
| Create | `tasks/templates/default.md` | Default task template with new frontmatter fields |
| Create | `tests/__init__.py` | Test package |
| Create | `tests/test_config.py` | Config tests |
| Create | `tests/test_models.py` | Model validation tests |
| Create | `tests/test_parser.py` | Parser tests |
| Create | `tests/test_writer.py` | Writer tests |
| Create | `tests/test_manager.py` | Manager tests (6 columns) |
| Create | `tests/test_rules_loader.py` | Rules loader tests |
| Create | `tests/test_logger.py` | Logger tests |
| Create | `tests/test_integration.py` | Full roundtrip integration test |

---

### Task 1: Project Setup

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `src/__init__.py`
- Create: `src/board/__init__.py`
- Create: `src/rules/__init__.py`
- Create: `src/logging/__init__.py`
- Create: `tests/__init__.py`
- Create: `tasks/{backlog,todo,doing,blocked,review,done,templates}/.gitkeep`
- Create: `tasks/templates/default.md`
- Create: `skills/rules.md`
- Create: `logs/.gitkeep`

- [ ] **Step 1: Initialize uv project**

```bash
cd /c/<your-user>/projects/cc-assitant
uv init --name cc-assistant --python ">=3.11"
```

- [ ] **Step 2: Replace pyproject.toml**

Overwrite the generated `pyproject.toml`:

```toml
[project]
name = "cc-assistant"
version = "0.1.0"
description = "Local AI Task Automation Agent"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "python-frontmatter>=1.1",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 3: Install dependencies**

```bash
uv sync --all-extras
```

- [ ] **Step 4: Create .env.example**

Write `.env.example`:

```
# LLM Provider: claude | openai | ollama
LLM_PROVIDER=claude

# Anthropic
ANTHROPIC_API_KEY=

# OpenAI
OPENAI_API_KEY=

# Ollama
OLLAMA_BASE_URL=http://localhost:11434

# Database
DB_HOST=your-db-host.example.com
DB_PORT=3306
DB_USER=root
DB_PASSWORD=
DB_NAME=

# WeChat Notification
WECHAT_WEBHOOK_URL=

# Paths
TASKS_DIR=tasks
LOGS_DIR=logs
SKILLS_DIR=skills
```

- [ ] **Step 5: Create .gitignore**

Write `.gitignore`:

```
__pycache__/
*.pyc
.venv/
.env
logs/*.jsonl
logs/*.log
logs/*.pid
*.egg-info/
dist/
.pytest_cache/
```

- [ ] **Step 6: Create directory structure and placeholder files**

```bash
mkdir -p src/board src/rules src/logging \
         tasks/backlog tasks/todo tasks/doing tasks/blocked tasks/review tasks/done tasks/templates \
         skills logs tests
touch src/__init__.py src/board/__init__.py src/rules/__init__.py src/logging/__init__.py tests/__init__.py
touch tasks/backlog/.gitkeep tasks/todo/.gitkeep tasks/doing/.gitkeep \
      tasks/blocked/.gitkeep tasks/review/.gitkeep tasks/done/.gitkeep \
      logs/.gitkeep
```

- [ ] **Step 7: Create default task template**

Write `tasks/templates/default.md`:

```markdown
---
id: ""
title: ""
project: ""
parent: null
priority: P1
tags: []
created: ""
updated: ""
auto_approve: true
depends_on: []
instructions: ""
subtasks: []
---

## 任务描述


## 对话

```

- [ ] **Step 8: Create skills/rules.md**

Write `skills/rules.md`:

```markdown
# Agent 行为规则

> 这份文件由人类维护。Agent 每轮会重新加载此文件作为系统 prompt 的一部分。
> 修改后无需重启 Agent，下一轮循环自动生效。

## 1. 任务复杂度分类

- **简单**（直接执行）：单一工具调用、纯查询、纯文件读写
- **中等**（先发计划再执行）：多步骤、跨工具
- **复杂**（必须先拆解 + 等用户确认）：跨系统、不可逆操作、需要人类决策

## 2. 路由表（任务类型 → 执行者）

| 任务类型 | 执行者 |
|---------|-------|
| 代码改动、本地文件 | Agent 自动 |
| 部署到生产 | Agent 起草，人工确认（→ review） |
| 设计风格 / 文案选型 | 必须人工拍板（出方案 → blocked） |
| 联网搜索 / 第三方 API | Agent 自动 |
| 数据库 schema 变更 | Agent 起草，人工确认（→ review） |

## 3. 失败处理表

| 失败类型 | 处理 |
|---------|-----|
| 工具调用超时 | 重试 1 次，仍失败则 blocked |
| 网络错误 | 等 30s 重试 1 次 |
| 权限/凭据缺失 | 立即 blocked，写明缺什么 |
| 任务前提不满足 | blocked + 说明依赖项 |

## 4. 注意力分配规则

- P0 立即处理，可中断 P1/P2
- P2 仅在无 P0/P1 时执行
- P2 任务执行总时长 ≤ 30 分钟，超时挂起
- 阻塞中（blocked-on-human）的任务总数 ≤ 3，超过则不再生成新阻塞，改为先完成已有

## 5. 个人情境（用户 = Siyao）

- 用户有 ADHD / 启动困难
- 分配给人的任务必须满足三条：
  1. 具体（一句话能说清要做什么）
  2. 单次可完成（≤ 15 分钟）
  3. 说清"为什么需要你"（不是"看一下"，而是"你需要从 A/B/C 选一个，因为 X"）
- 一次最多挂起 3 个 blocked-on-human 任务，避免人侧积压
```

- [ ] **Step 9: Verify setup**

```bash
uv run python -c "import pydantic; import frontmatter; from pydantic_settings import BaseSettings; print('OK')"
```

Expected output: `OK`

- [ ] **Step 10: Commit**

```bash
git init
git add pyproject.toml .env.example .gitignore src/ tests/ tasks/ skills/ logs/.gitkeep uv.lock
git commit -m "chore: initialize project structure with uv, dependencies, and skill rules template"
```

---

### Task 2: Configuration Module

**Files:**
- Create: `src/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_config.py`:

```python
import os
from pathlib import Path


def test_config_loads_defaults():
    """Config should have sensible defaults when no .env exists."""
    for key in ["LLM_PROVIDER", "TASKS_DIR", "LOGS_DIR", "SKILLS_DIR"]:
        os.environ.pop(key, None)

    import importlib
    import src.config
    importlib.reload(src.config)
    from src.config import config

    assert config.llm_provider == "claude"
    assert config.tasks_dir == Path("tasks")
    assert config.logs_dir == Path("logs")
    assert config.skills_dir == Path("skills")


def test_config_reads_env(monkeypatch):
    """Config should read values from environment variables."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("TASKS_DIR", "/tmp/my_tasks")
    monkeypatch.setenv("LOGS_DIR", "/tmp/my_logs")
    monkeypatch.setenv("SKILLS_DIR", "/tmp/my_skills")

    import importlib
    import src.config
    importlib.reload(src.config)
    from src.config import config

    assert config.llm_provider == "openai"
    assert config.tasks_dir == Path("/tmp/my_tasks")
    assert config.logs_dir == Path("/tmp/my_logs")
    assert config.skills_dir == Path("/tmp/my_skills")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_config.py -v
```

Expected: FAIL — `src.config` has no `config` attribute.

- [ ] **Step 3: Write implementation**

Write `src/config.py`:

```python
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    llm_provider: str = "claude"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"

    # Database
    db_host: str = ""
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""
    db_name: str = ""

    # WeChat
    wechat_webhook_url: str = ""

    # Paths
    tasks_dir: Path = Path("tasks")
    logs_dir: Path = Path("logs")
    skills_dir: Path = Path("skills")

    # Dispatcher
    poll_interval_minutes: int = 30
    git_pull_interval_minutes: int = 5
    debounce_seconds: float = 2.0


config = Config()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_config.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_config.py pyproject.toml uv.lock
git commit -m "feat: add configuration module with env loading and skills_dir"
```

---

### Task 3: Pydantic Data Models

**Files:**
- Create: `src/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_models.py`:

```python
from datetime import datetime
from src.models import (
    Priority,
    TaskStatus,
    SubtaskStatus,
    Subtask,
    ConversationEntry,
    ConversationRole,
    Task,
    LogEntry,
)


def test_priority_ordering():
    """P0 < P1 < P2 (P0 is highest priority, sorts first)."""
    assert Priority.P0.sort_key < Priority.P1.sort_key
    assert Priority.P1.sort_key < Priority.P2.sort_key


def test_task_status_six_columns():
    """TaskStatus enum values match the six directory names."""
    assert TaskStatus.BACKLOG.value == "backlog"
    assert TaskStatus.TODO.value == "todo"
    assert TaskStatus.DOING.value == "doing"
    assert TaskStatus.BLOCKED.value == "blocked"
    assert TaskStatus.REVIEW.value == "review"
    assert TaskStatus.DONE.value == "done"


def test_subtask_status_includes_blocked():
    """SubtaskStatus must support BLOCKED for mid-task subtask blocks."""
    assert SubtaskStatus.TODO.value == "todo"
    assert SubtaskStatus.DOING.value == "doing"
    assert SubtaskStatus.BLOCKED.value == "blocked"
    assert SubtaskStatus.DONE.value == "done"


def test_subtask_with_blocking_reason():
    sub = Subtask(
        id="025-1",
        title="设计风格选型",
        status=SubtaskStatus.BLOCKED,
        blocking_reason="需要用户从方案 A/B/C 中选择",
    )
    assert sub.status == SubtaskStatus.BLOCKED
    assert sub.blocking_reason == "需要用户从方案 A/B/C 中选择"


def test_subtask_blocking_reason_optional():
    sub = Subtask(id="025-2", title="实现首页", status=SubtaskStatus.TODO)
    assert sub.blocking_reason is None


def test_conversation_entry():
    entry = ConversationEntry(
        role=ConversationRole.HUMAN,
        timestamp=datetime(2026, 4, 26, 14, 0),
        content="Do this task.",
    )
    assert entry.role == ConversationRole.HUMAN
    assert "Do this task" in entry.content


def test_task_with_new_fields():
    task = Task(
        id="025",
        title="个人 portfolio 网站",
        project="portfolio-website",
        parent=None,
        priority=Priority.P1,
        tags=["frontend", "design"],
        created=datetime(2026, 4, 26, 14, 0),
        updated=datetime(2026, 4, 26, 14, 0),
        auto_approve=True,
        depends_on=[],
        instructions="请优先使用 Tailwind CSS。",
        subtasks=[],
        description="做一个个人作品集网站。",
        conversation=[],
    )
    assert task.id == "025"
    assert task.project == "portfolio-website"
    assert task.parent is None
    assert task.instructions == "请优先使用 Tailwind CSS。"


def test_task_minimal_defaults():
    """project, parent, instructions all default to safe values."""
    task = Task(
        id="001",
        title="Simple",
        priority=Priority.P1,
        created=datetime(2026, 4, 26),
        updated=datetime(2026, 4, 26),
    )
    assert task.project == ""
    assert task.parent is None
    assert task.instructions == ""
    assert task.auto_approve is True
    assert task.tags == []
    assert task.subtasks == []


def test_log_entry():
    entry = LogEntry(
        task_id="025",
        action="tool_exec",
        detail="ran shell command",
        duration_ms=500,
        status="success",
    )
    assert entry.task_id == "025"
    assert entry.ts is not None  # auto-set
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_models.py -v
```

Expected: FAIL — cannot import from `src.models`.

- [ ] **Step 3: Write implementation**

Write `src/models.py`:

```python
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Priority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"

    @property
    def sort_key(self) -> int:
        return {"P0": 0, "P1": 1, "P2": 2}[self.value]


class TaskStatus(str, Enum):
    BACKLOG = "backlog"
    TODO = "todo"
    DOING = "doing"
    BLOCKED = "blocked"
    REVIEW = "review"
    DONE = "done"


class SubtaskStatus(str, Enum):
    TODO = "todo"
    DOING = "doing"
    BLOCKED = "blocked"
    DONE = "done"


class Subtask(BaseModel):
    id: str
    title: str
    status: SubtaskStatus = SubtaskStatus.TODO
    blocking_reason: Optional[str] = None


class ConversationRole(str, Enum):
    HUMAN = "Human"
    AI = "AI"


class ConversationEntry(BaseModel):
    role: ConversationRole
    timestamp: datetime
    content: str


class Task(BaseModel):
    id: str
    title: str
    project: str = ""
    parent: Optional[str] = None
    priority: Priority = Priority.P1
    tags: list[str] = Field(default_factory=list)
    created: datetime
    updated: datetime
    auto_approve: bool = True
    depends_on: list[str] = Field(default_factory=list)
    instructions: str = ""
    subtasks: list[Subtask] = Field(default_factory=list)
    description: str = ""
    conversation: list[ConversationEntry] = Field(default_factory=list)
    source_path: Optional[str] = None  # tracks which file this was parsed from


class LogEntry(BaseModel):
    ts: datetime = Field(default_factory=datetime.now)
    task_id: str
    action: str
    detail: str
    duration_ms: int = 0
    status: str = "success"
    tool: Optional[str] = None
    reason: Optional[str] = None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_models.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/models.py tests/test_models.py
git commit -m "feat: add pydantic models with 6-column status, project/parent/instructions, blocking_reason"
```

---

### Task 4: Board Parser

**Files:**
- Create: `src/board/parser.py`
- Create: `tests/test_parser.py`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_parser.py`:

```python
from datetime import datetime
from pathlib import Path
from src.board.parser import parse_task_file, parse_task_string
from src.models import Priority, ConversationRole, SubtaskStatus


SAMPLE_TASK = """\
---
id: "025"
title: 个人 portfolio 网站
project: portfolio-website
parent: null
priority: P1
tags: [frontend, design]
created: 2026-04-26 14:00
updated: 2026-04-26 15:31
auto_approve: true
depends_on: []
instructions: |
  请优先使用 Tailwind CSS。
  设计语言保持极简。
subtasks:
  - id: "025-1"
    title: 设计风格选型
    status: blocked
    blocking_reason: 需要用户从方案 A/B/C 中选择
  - id: "025-2"
    title: 实现首页布局
    status: doing
---

## 任务描述
做一个个人作品集网站，三端布局同步完成。

## 对话

### [Human] 2026-04-26 14:00
帮我做一个 portfolio 网站。

### [AI] 2026-04-26 14:02
准备了三种方案：A. 极简黑白；B. 渐变彩色；C. 复古印刷风。请选一个。

### [Human] 2026-04-26 15:30
选 A。
"""


def test_parse_frontmatter_basic():
    task = parse_task_string(SAMPLE_TASK)
    assert task.id == "025"
    assert task.title == "个人 portfolio 网站"
    assert task.priority == Priority.P1
    assert task.tags == ["frontend", "design"]
    assert task.auto_approve is True


def test_parse_new_fields():
    """project, parent, instructions all parsed."""
    task = parse_task_string(SAMPLE_TASK)
    assert task.project == "portfolio-website"
    assert task.parent is None
    assert "Tailwind CSS" in task.instructions
    assert "设计语言保持极简" in task.instructions


def test_parse_subtasks_with_blocking_reason():
    task = parse_task_string(SAMPLE_TASK)
    assert len(task.subtasks) == 2
    assert task.subtasks[0].id == "025-1"
    assert task.subtasks[0].status == SubtaskStatus.BLOCKED
    assert task.subtasks[0].blocking_reason == "需要用户从方案 A/B/C 中选择"
    assert task.subtasks[1].status == SubtaskStatus.DOING
    assert task.subtasks[1].blocking_reason is None


def test_parse_description():
    task = parse_task_string(SAMPLE_TASK)
    assert "三端布局同步完成" in task.description


def test_parse_conversation():
    task = parse_task_string(SAMPLE_TASK)
    assert len(task.conversation) == 3
    assert task.conversation[0].role == ConversationRole.HUMAN
    assert "portfolio 网站" in task.conversation[0].content
    assert task.conversation[1].role == ConversationRole.AI
    assert "三种方案" in task.conversation[1].content


def test_parse_conversation_timestamps():
    task = parse_task_string(SAMPLE_TASK)
    assert task.conversation[0].timestamp == datetime(2026, 4, 26, 14, 0)
    assert task.conversation[1].timestamp == datetime(2026, 4, 26, 14, 2)
    assert task.conversation[2].timestamp == datetime(2026, 4, 26, 15, 30)


def test_parse_file(tmp_path):
    f = tmp_path / "025-portfolio.md"
    f.write_text(SAMPLE_TASK, encoding="utf-8")
    task = parse_task_file(f)
    assert task.id == "025"
    assert task.source_path == str(f)


def test_parse_minimal_task():
    """Task with no project, no parent, no instructions, no subtasks should still parse."""
    md = """\
---
id: "002"
title: Simple task
priority: P2
tags: []
created: 2026-04-26 10:00
updated: 2026-04-26 10:00
auto_approve: true
depends_on: []
subtasks: []
---

## 任务描述
Do something.

## 对话
"""
    task = parse_task_string(md)
    assert task.id == "002"
    assert task.project == ""
    assert task.parent is None
    assert task.instructions == ""
    assert len(task.conversation) == 0


def test_parse_parent_id():
    """parent field can be a string id."""
    md = """\
---
id: "025-1-1"
title: Child task
project: portfolio-website
parent: "025-1"
priority: P1
tags: []
created: 2026-04-26 10:00
updated: 2026-04-26 10:00
auto_approve: true
depends_on: []
subtasks: []
---

## 任务描述
Subtask details.

## 对话
"""
    task = parse_task_string(md)
    assert task.parent == "025-1"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_parser.py -v
```

Expected: FAIL — cannot import `parse_task_file`.

- [ ] **Step 3: Write implementation**

Write `src/board/parser.py`:

```python
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import frontmatter

from src.models import (
    ConversationEntry,
    ConversationRole,
    Priority,
    Subtask,
    SubtaskStatus,
    Task,
)

# Matches: ### [Human] 2026-04-26 14:00  or  ### [AI] 2026-04-26 14:02
_CONVERSATION_HEADER = re.compile(
    r"^###\s+\[(?P<role>Human|AI)\]\s+(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*$"
)


def parse_task_string(text: str, source_path: str | None = None) -> Task:
    """Parse a Markdown task string into a Task model."""
    post = frontmatter.loads(text)
    meta = post.metadata
    body = post.content

    subtasks = [
        Subtask(
            id=str(s["id"]),
            title=s["title"],
            status=SubtaskStatus(s.get("status", "todo")),
            blocking_reason=s.get("blocking_reason"),
        )
        for s in meta.get("subtasks", []) or []
    ]

    description, conversation = _parse_body(body)

    parent_value = meta.get("parent")
    parent = str(parent_value) if parent_value not in (None, "", "null") else None

    return Task(
        id=str(meta["id"]),
        title=meta["title"],
        project=meta.get("project", "") or "",
        parent=parent,
        priority=Priority(meta.get("priority", "P1")),
        tags=meta.get("tags", []) or [],
        created=_parse_datetime(meta["created"]),
        updated=_parse_datetime(meta["updated"]),
        auto_approve=meta.get("auto_approve", True),
        depends_on=meta.get("depends_on", []) or [],
        instructions=meta.get("instructions", "") or "",
        subtasks=subtasks,
        description=description,
        conversation=conversation,
        source_path=source_path,
    )


def parse_task_file(path: Path) -> Task:
    """Parse a Markdown task file into a Task model."""
    text = path.read_text(encoding="utf-8")
    return parse_task_string(text, source_path=str(path))


def _parse_body(body: str) -> tuple[str, list[ConversationEntry]]:
    """Split the markdown body into description and conversation entries."""
    parts = re.split(r"^## 对话\s*$", body, maxsplit=1, flags=re.MULTILINE)

    desc_part = parts[0]
    desc_match = re.split(r"^## 任务描述\s*$", desc_part, maxsplit=1, flags=re.MULTILINE)
    description = desc_match[1].strip() if len(desc_match) > 1 else desc_part.strip()

    conversation: list[ConversationEntry] = []
    if len(parts) < 2:
        return description, conversation

    conv_text = parts[1]
    entries = re.split(r"(?=^### \[)", conv_text, flags=re.MULTILINE)

    for entry_text in entries:
        entry_text = entry_text.strip()
        if not entry_text:
            continue

        match = _CONVERSATION_HEADER.match(entry_text.split("\n")[0])
        if not match:
            continue

        role = ConversationRole(match.group("role"))
        ts = _parse_datetime(match.group("ts"))
        content_lines = entry_text.split("\n")[1:]
        content = "\n".join(content_lines).strip()

        conversation.append(
            ConversationEntry(role=role, timestamp=ts, content=content)
        )

    return description, conversation


def _parse_datetime(value: str | datetime) -> datetime:
    """Parse a datetime string or return as-is if already datetime."""
    if isinstance(value, datetime):
        return value
    value = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {value}")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_parser.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/board/parser.py tests/test_parser.py
git commit -m "feat: add markdown task parser with project/parent/instructions/blocking_reason"
```

---

### Task 5: Board Writer

**Files:**
- Create: `src/board/writer.py`
- Create: `tests/test_writer.py`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_writer.py`:

```python
from datetime import datetime
from src.board.writer import write_task_file, append_conversation
from src.board.parser import parse_task_string
from src.models import (
    Task,
    Priority,
    Subtask,
    SubtaskStatus,
    ConversationEntry,
    ConversationRole,
)


def _make_task(**overrides) -> Task:
    defaults = dict(
        id="001",
        title="Test task",
        project="",
        parent=None,
        priority=Priority.P1,
        tags=["test"],
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


def test_write_and_roundtrip(tmp_path):
    """Write a task to file, parse it back, fields match."""
    task = _make_task(
        project="test-project",
        instructions="Use TDD.",
        subtasks=[
            Subtask(id="001-1", title="Step one", status=SubtaskStatus.DONE),
            Subtask(
                id="001-2",
                title="Step two",
                status=SubtaskStatus.BLOCKED,
                blocking_reason="Awaiting user input",
            ),
        ],
        conversation=[
            ConversationEntry(
                role=ConversationRole.HUMAN,
                timestamp=datetime(2026, 4, 26, 14, 0),
                content="Do this.",
            ),
        ],
    )
    path = tmp_path / "001-test.md"
    write_task_file(task, path)

    parsed = parse_task_string(path.read_text(encoding="utf-8"))
    assert parsed.id == "001"
    assert parsed.project == "test-project"
    assert parsed.instructions == "Use TDD."
    assert len(parsed.subtasks) == 2
    assert parsed.subtasks[0].status == SubtaskStatus.DONE
    assert parsed.subtasks[1].status == SubtaskStatus.BLOCKED
    assert parsed.subtasks[1].blocking_reason == "Awaiting user input"
    assert parsed.description == "A test task."
    assert len(parsed.conversation) == 1
    assert parsed.conversation[0].content == "Do this."


def test_write_with_parent(tmp_path):
    """parent field round-trips correctly."""
    task = _make_task(id="025-1-1", parent="025-1")
    path = tmp_path / "025-1-1.md"
    write_task_file(task, path)

    parsed = parse_task_string(path.read_text(encoding="utf-8"))
    assert parsed.parent == "025-1"


def test_append_conversation(tmp_path):
    """Append a conversation entry to an existing task file."""
    task = _make_task()
    path = tmp_path / "001-test.md"
    write_task_file(task, path)

    entry = ConversationEntry(
        role=ConversationRole.AI,
        timestamp=datetime(2026, 4, 26, 14, 5),
        content="I will do this now.",
    )
    append_conversation(path, entry)

    parsed = parse_task_string(path.read_text(encoding="utf-8"))
    assert len(parsed.conversation) == 1
    assert parsed.conversation[0].role == ConversationRole.AI
    assert parsed.conversation[0].content == "I will do this now."


def test_write_preserves_chinese(tmp_path):
    """Chinese characters preserved in roundtrip."""
    task = _make_task(title="部署后端", description="把代码部署上去。")
    path = tmp_path / "001-deploy.md"
    write_task_file(task, path)

    content = path.read_text(encoding="utf-8")
    assert "部署后端" in content
    assert "把代码部署上去" in content
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_writer.py -v
```

Expected: FAIL — cannot import `write_task_file`.

- [ ] **Step 3: Write implementation**

Write `src/board/writer.py`:

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.models import ConversationEntry, Task


def write_task_file(task: Task, path: Path) -> None:
    """Write a Task model to a Markdown file."""
    lines: list[str] = []

    # YAML frontmatter
    lines.append("---")
    lines.append(f'id: "{task.id}"')
    lines.append(f"title: {task.title}")
    lines.append(f"project: {task.project}")
    lines.append(f"parent: {task.parent if task.parent is not None else 'null'}")
    lines.append(f"priority: {task.priority.value}")
    lines.append(f"tags: [{', '.join(task.tags)}]")
    lines.append(f"created: {_format_dt(task.created)}")
    lines.append(f"updated: {_format_dt(task.updated)}")
    lines.append(f"auto_approve: {'true' if task.auto_approve else 'false'}")
    lines.append(f"depends_on: [{', '.join(task.depends_on)}]")

    # instructions: emit as block scalar if multi-line, otherwise inline
    if task.instructions:
        if "\n" in task.instructions:
            lines.append("instructions: |")
            for line in task.instructions.split("\n"):
                lines.append(f"  {line}")
        else:
            lines.append(f"instructions: {task.instructions}")
    else:
        lines.append('instructions: ""')

    # Subtasks
    if task.subtasks:
        lines.append("subtasks:")
        for sub in task.subtasks:
            lines.append(f'  - id: "{sub.id}"')
            lines.append(f"    title: {sub.title}")
            lines.append(f"    status: {sub.status.value}")
            if sub.blocking_reason:
                lines.append(f"    blocking_reason: {sub.blocking_reason}")
    else:
        lines.append("subtasks: []")

    lines.append("---")
    lines.append("")

    # Description
    lines.append("## 任务描述")
    lines.append(task.description)
    lines.append("")

    # Conversation
    lines.append("## 对话")
    lines.append("")
    for entry in task.conversation:
        lines.append(_format_conversation_entry(entry))

    path.write_text("\n".join(lines), encoding="utf-8")


def append_conversation(path: Path, entry: ConversationEntry) -> None:
    """Append a conversation entry to an existing task file."""
    text = path.read_text(encoding="utf-8")
    formatted = _format_conversation_entry(entry)
    text = text.rstrip() + "\n" + formatted
    path.write_text(text, encoding="utf-8")


def _format_conversation_entry(entry: ConversationEntry) -> str:
    """Format a single conversation entry as Markdown."""
    header = f"### [{entry.role.value}] {_format_dt(entry.timestamp)}"
    return f"{header}\n{entry.content}\n"


def _format_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_writer.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/board/writer.py tests/test_writer.py
git commit -m "feat: add board writer supporting project/parent/instructions/blocking_reason"
```

---

### Task 6: Board Manager (Six Columns)

**Files:**
- Create: `src/board/manager.py`
- Create: `tests/test_manager.py`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_manager.py`:

```python
from datetime import datetime
from pathlib import Path
from src.board.manager import BoardManager
from src.models import TaskStatus


ALL_STATUSES = ["backlog", "todo", "doing", "blocked", "review", "done"]


def _setup_dirs(base: Path) -> dict[str, Path]:
    dirs = {}
    for status in ALL_STATUSES:
        d = base / "tasks" / status
        d.mkdir(parents=True, exist_ok=True)
        dirs[status] = d
    return dirs


def _create_task_file(directory: Path, filename: str, task_id: str = "001") -> Path:
    path = directory / filename
    path.write_text(
        f'---\nid: "{task_id}"\ntitle: Test\nproject: ""\nparent: null\n'
        f"priority: P1\ntags: []\n"
        f"created: 2026-04-26 14:00\nupdated: 2026-04-26 14:00\n"
        f'auto_approve: true\ndepends_on: []\ninstructions: ""\nsubtasks: []\n---\n\n'
        f"## 任务描述\nTest.\n\n## 对话\n",
        encoding="utf-8",
    )
    return path


def test_move_task_todo_to_doing(tmp_path):
    dirs = _setup_dirs(tmp_path)
    src = _create_task_file(dirs["todo"], "001-test.md")
    manager = BoardManager(tmp_path / "tasks")

    new_path = manager.move_task(src, TaskStatus.DOING)

    assert not src.exists()
    assert new_path.exists()
    assert new_path.parent.name == "doing"


def test_move_to_review(tmp_path):
    dirs = _setup_dirs(tmp_path)
    src = _create_task_file(dirs["doing"], "001-test.md")
    manager = BoardManager(tmp_path / "tasks")

    new_path = manager.move_task(src, TaskStatus.REVIEW)
    assert new_path.parent.name == "review"
    assert new_path.exists()


def test_move_to_backlog(tmp_path):
    dirs = _setup_dirs(tmp_path)
    src = _create_task_file(dirs["todo"], "001-test.md")
    manager = BoardManager(tmp_path / "tasks")

    new_path = manager.move_task(src, TaskStatus.BACKLOG)
    assert new_path.parent.name == "backlog"
    assert new_path.exists()


def test_move_to_done_archives_by_month(tmp_path):
    dirs = _setup_dirs(tmp_path)
    src = _create_task_file(dirs["review"], "001-test.md")
    manager = BoardManager(tmp_path / "tasks")

    new_path = manager.move_task(src, TaskStatus.DONE)

    today = datetime.now()
    expected_dir = dirs["done"] / today.strftime("%Y-%m")
    assert new_path.parent == expected_dir
    assert new_path.exists()


def test_list_tasks_in_status(tmp_path):
    dirs = _setup_dirs(tmp_path)
    _create_task_file(dirs["todo"], "001-task-a.md", "001")
    _create_task_file(dirs["todo"], "002-task-b.md", "002")
    _create_task_file(dirs["review"], "003-task-c.md", "003")

    manager = BoardManager(tmp_path / "tasks")

    todo_files = manager.list_tasks(TaskStatus.TODO)
    assert len(todo_files) == 2

    review_files = manager.list_tasks(TaskStatus.REVIEW)
    assert len(review_files) == 1


def test_list_active_tasks_excludes_backlog_and_done(tmp_path):
    """Active = todo + doing + blocked + review (not backlog, not done)."""
    dirs = _setup_dirs(tmp_path)
    _create_task_file(dirs["backlog"], "001-a.md", "001")
    _create_task_file(dirs["todo"], "002-b.md", "002")
    _create_task_file(dirs["doing"], "003-c.md", "003")
    _create_task_file(dirs["blocked"], "004-d.md", "004")
    _create_task_file(dirs["review"], "005-e.md", "005")
    _create_task_file(dirs["done"], "006-f.md", "006")

    manager = BoardManager(tmp_path / "tasks")
    active = manager.list_active_tasks()

    # backlog (not yet ready) and done (archived) excluded
    assert len(active) == 4
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_manager.py -v
```

Expected: FAIL — cannot import `BoardManager`.

- [ ] **Step 3: Write implementation**

Write `src/board/manager.py`:

```python
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from src.models import TaskStatus


class BoardManager:
    """Manages task files across the six status directories."""

    def __init__(self, tasks_dir: Path) -> None:
        self.tasks_dir = tasks_dir

    def _status_dir(self, status: TaskStatus) -> Path:
        return self.tasks_dir / status.value

    def move_task(self, source: Path, new_status: TaskStatus) -> Path:
        """Move a task file to a new status directory.

        Done tasks are archived into monthly subdirectories.
        """
        target_dir = self._status_dir(new_status)

        if new_status == TaskStatus.DONE:
            month_dir = target_dir / datetime.now().strftime("%Y-%m")
            month_dir.mkdir(parents=True, exist_ok=True)
            target_dir = month_dir

        target_dir.mkdir(parents=True, exist_ok=True)
        dest = target_dir / source.name
        shutil.move(str(source), str(dest))
        return dest

    def list_tasks(self, status: TaskStatus) -> list[Path]:
        """List .md task files in a status directory.

        Done is recursive (monthly subdirs); others are flat.
        """
        directory = self._status_dir(status)
        if not directory.exists():
            return []
        if status == TaskStatus.DONE:
            return sorted(directory.rglob("*.md"))
        return sorted(directory.glob("*.md"))

    def list_active_tasks(self) -> list[Path]:
        """List active task files (todo + doing + blocked + review).

        Excludes backlog (not yet ready) and done (archived).
        """
        active: list[Path] = []
        for status in (
            TaskStatus.TODO,
            TaskStatus.DOING,
            TaskStatus.BLOCKED,
            TaskStatus.REVIEW,
        ):
            active.extend(self.list_tasks(status))
        return active
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_manager.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/board/manager.py tests/test_manager.py
git commit -m "feat: add board manager for 6-column task movement and listing"
```

---

### Task 7: Rules Loader

**Files:**
- Create: `src/rules/loader.py`
- Create: `tests/test_rules_loader.py`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_rules_loader.py`:

```python
from pathlib import Path
from src.rules.loader import RulesLoader


def test_load_rules(tmp_path):
    """Loader reads skills/rules.md content."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    rules_file = skills_dir / "rules.md"
    rules_file.write_text("# Agent Rules\n\nBe helpful.\n", encoding="utf-8")

    loader = RulesLoader(skills_dir)
    content = loader.load()

    assert "Agent Rules" in content
    assert "Be helpful" in content


def test_load_picks_up_edits(tmp_path):
    """Each load() call re-reads the file from disk (no caching)."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    rules_file = skills_dir / "rules.md"
    rules_file.write_text("v1", encoding="utf-8")

    loader = RulesLoader(skills_dir)
    assert loader.load() == "v1"

    rules_file.write_text("v2", encoding="utf-8")
    assert loader.load() == "v2"


def test_load_missing_returns_empty(tmp_path):
    """If skills/rules.md does not exist, loader returns empty string (no crash)."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    loader = RulesLoader(skills_dir)
    assert loader.load() == ""
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_rules_loader.py -v
```

Expected: FAIL — cannot import `RulesLoader`.

- [ ] **Step 3: Write implementation**

Write `src/rules/loader.py`:

```python
from __future__ import annotations

from pathlib import Path


class RulesLoader:
    """Loads the human-editable skills/rules.md file fresh on every call.

    Per the Completion Promise Pattern, every Orchestrator cycle re-reads
    rules so user edits take effect on the next cycle without restart.
    """

    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = skills_dir

    def load(self) -> str:
        """Return the current rules.md content, or empty string if absent."""
        path = self.skills_dir / "rules.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_rules_loader.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rules/loader.py tests/test_rules_loader.py
git commit -m "feat: add skills/rules.md loader with no-cache reads for live edits"
```

---

### Task 8: Structured JSONL Logger

**Files:**
- Create: `src/logging/structured.py`
- Create: `tests/test_logger.py`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_logger.py`:

```python
import json
from src.logging.structured import StructuredLogger
from src.models import LogEntry


def test_log_creates_file(tmp_path):
    logger = StructuredLogger(tmp_path)
    entry = LogEntry(
        task_id="001",
        action="test_action",
        detail="testing",
        duration_ms=100,
        status="success",
    )
    logger.log(entry)

    log_file = tmp_path / "001.jsonl"
    assert log_file.exists()
    line = log_file.read_text(encoding="utf-8").strip()
    data = json.loads(line)
    assert data["task_id"] == "001"
    assert data["action"] == "test_action"


def test_log_appends_multiple(tmp_path):
    logger = StructuredLogger(tmp_path)
    for i in range(3):
        entry = LogEntry(
            task_id="001", action=f"step_{i}", detail=f"step {i}", status="success"
        )
        logger.log(entry)

    lines = (tmp_path / "001.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3


def test_log_system_event(tmp_path):
    logger = StructuredLogger(tmp_path)
    logger.log_system("startup", "Agent started")

    log_file = tmp_path / "agent.jsonl"
    assert log_file.exists()
    data = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert data["action"] == "startup"
    assert data["task_id"] == "_system"


def test_get_task_logs(tmp_path):
    logger = StructuredLogger(tmp_path)
    for i in range(3):
        logger.log(
            LogEntry(
                task_id="002", action=f"step_{i}", detail=f"d{i}", status="success"
            )
        )

    logs = logger.get_task_logs("002")
    assert len(logs) == 3
    assert logs[0]["action"] == "step_0"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_logger.py -v
```

Expected: FAIL — cannot import `StructuredLogger`.

- [ ] **Step 3: Write implementation**

Write `src/logging/structured.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from src.models import LogEntry


class StructuredLogger:
    """Writes structured JSONL log files — one per task, plus a global system log."""

    def __init__(self, logs_dir: Path) -> None:
        self.logs_dir = logs_dir
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def log(self, entry: LogEntry) -> None:
        """Append a log entry to the task-specific JSONL file."""
        path = self.logs_dir / f"{entry.task_id}.jsonl"
        self._append(path, entry)

    def log_system(self, action: str, detail: str, **kwargs: object) -> None:
        """Log a system-level event to agent.jsonl."""
        entry = LogEntry(task_id="_system", action=action, detail=detail, **kwargs)
        path = self.logs_dir / "agent.jsonl"
        self._append(path, entry)

    def get_task_logs(self, task_id: str) -> list[dict]:
        """Read all log entries for a given task."""
        path = self.logs_dir / f"{task_id}.jsonl"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        return [json.loads(line) for line in lines if line.strip()]

    def _append(self, path: Path, entry: LogEntry) -> None:
        data = entry.model_dump(mode="json")
        if hasattr(data["ts"], "isoformat"):
            data["ts"] = data["ts"].isoformat()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_logger.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/logging/structured.py tests/test_logger.py
git commit -m "feat: add structured JSONL logger with per-task and system log files"
```

---

### Task 9: Integration Test — Full Roundtrip

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write the integration test**

Write `tests/test_integration.py`:

```python
"""Integration test:
Human creates task in todo/ → Agent moves to doing/ → AI replies →
auto_approve=false → Agent moves to review/ → Human approves → done/
"""

from datetime import datetime

from src.board.manager import BoardManager
from src.board.parser import parse_task_file
from src.board.writer import write_task_file, append_conversation
from src.logging.structured import StructuredLogger
from src.rules.loader import RulesLoader
from src.models import (
    ConversationEntry,
    ConversationRole,
    LogEntry,
    Priority,
    Subtask,
    SubtaskStatus,
    Task,
    TaskStatus,
)


def test_full_roundtrip(tmp_path):
    # Setup directories
    tasks_dir = tmp_path / "tasks"
    logs_dir = tmp_path / "logs"
    skills_dir = tmp_path / "skills"
    for status in ["backlog", "todo", "doing", "blocked", "review", "done"]:
        (tasks_dir / status).mkdir(parents=True)
    skills_dir.mkdir()
    (skills_dir / "rules.md").write_text("# Rules\nBe careful.", encoding="utf-8")

    manager = BoardManager(tasks_dir)
    logger = StructuredLogger(logs_dir)
    rules = RulesLoader(skills_dir)

    # 1. Rules load
    assert "Be careful" in rules.load()

    # 2. Human creates a task in todo/ (auto_approve=false → will route to review/)
    task = Task(
        id="025",
        title="搭建测试环境",
        project="infra",
        parent=None,
        priority=Priority.P0,
        tags=["infra"],
        created=datetime(2026, 4, 26, 10, 0),
        updated=datetime(2026, 4, 26, 10, 0),
        auto_approve=False,
        instructions="使用 Docker compose。",
        description="搭建一个完整的测试环境。",
        conversation=[
            ConversationEntry(
                role=ConversationRole.HUMAN,
                timestamp=datetime(2026, 4, 26, 10, 0),
                content="优先搞定数据库部分。",
            )
        ],
    )
    todo_path = tasks_dir / "todo" / "025-setup-test-env.md"
    write_task_file(task, todo_path)
    assert todo_path.exists()

    # 3. Agent parses the task
    parsed = parse_task_file(todo_path)
    assert parsed.id == "025"
    assert parsed.priority == Priority.P0
    assert parsed.project == "infra"
    assert parsed.instructions == "使用 Docker compose。"
    assert parsed.auto_approve is False

    # 4. Agent moves task to doing/
    doing_path = manager.move_task(todo_path, TaskStatus.DOING)
    assert not todo_path.exists()
    assert doing_path.exists()
    assert doing_path.parent.name == "doing"

    # 5. Agent appends AI reply
    ai_reply = ConversationEntry(
        role=ConversationRole.AI,
        timestamp=datetime(2026, 4, 26, 10, 1),
        content="收到，先搭建数据库：\n1. 创建 MySQL 实例\n2. 初始化表结构",
    )
    append_conversation(doing_path, ai_reply)

    # 6. Log the action
    logger.log(
        LogEntry(
            task_id="025",
            action="task_started",
            detail="开始搭建测试环境",
            status="success",
        )
    )

    # 7. Re-parse and verify conversation
    reparsed = parse_task_file(doing_path)
    assert len(reparsed.conversation) == 2
    assert reparsed.conversation[1].role == ConversationRole.AI
    assert "MySQL 实例" in reparsed.conversation[1].content

    # 8. Agent finishes work; auto_approve=false → moves to review/
    review_path = manager.move_task(doing_path, TaskStatus.REVIEW)
    assert review_path.parent.name == "review"
    assert review_path.exists()

    # 9. Active tasks list now includes the review item
    active = manager.list_active_tasks()
    assert len(active) == 1
    assert active[0] == review_path

    # 10. Human approves → moves to done/YYYY-MM/
    done_path = manager.move_task(review_path, TaskStatus.DONE)
    assert done_path.exists()
    today = datetime.now()
    assert done_path.parent.name == today.strftime("%Y-%m")

    # 11. Verify logs
    logs = logger.get_task_logs("025")
    assert len(logs) == 1
    assert logs[0]["action"] == "task_started"

    # 12. Verify active tasks list is empty after archival
    active = manager.list_active_tasks()
    assert len(active) == 0
```

- [ ] **Step 2: Run the integration test**

```bash
uv run pytest tests/test_integration.py -v
```

Expected: 1 passed.

- [ ] **Step 3: Run all tests to verify nothing is broken**

```bash
uv run pytest -v
```

Expected: All tests passed (config: 2, models: 9, parser: 9, writer: 4, manager: 6, rules_loader: 3, logger: 4, integration: 1 = **38 total**).

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add full roundtrip integration test for board layer (todo→doing→review→done)"
```

---

## Self-Review

**Spec coverage:**
- Layer 1 Task Board (six-column directory structure, frontmatter format, `project`/`parent`/`instructions`/`subtasks[].blocking_reason`, conversation thread): Tasks 1, 3, 4, 5, 6.
- Layer 4 `skills/rules.md` template + loader: Tasks 1 (template content) and 7 (loader).
- Layer 5 Structured JSONL logging: Task 8.
- Config (env vars including `SKILLS_DIR`): Task 2.
- Layers 2 (dispatcher), 3 (orchestrator + LLM clients + Tools), business logic engine, CLI, Mobile Web UI: deferred to Plans 2-5 as per spec.

**Placeholder scan:** No "TBD" / "TODO" / "fill in details" / vague handlers / unreferenced types found. All test assertions reference fields and enum values defined in earlier tasks.

**Type consistency:**
- `TaskStatus` enum has the six values `backlog/todo/doing/blocked/review/done` consistently in models, manager tests, and integration test.
- `SubtaskStatus` includes `BLOCKED` (used in writer test) and is consistent with parser handling of `blocking_reason`.
- `Task` fields `project`, `parent`, `instructions` defined in models, written by writer, read by parser, asserted in integration test.
- `Subtask.blocking_reason` defined in models, written by writer, read by parser, asserted in writer test.
- `parse_task_string` / `parse_task_file` / `write_task_file` / `append_conversation` / `BoardManager` / `RulesLoader` / `StructuredLogger` names match across all tests and implementations.

All clean.
