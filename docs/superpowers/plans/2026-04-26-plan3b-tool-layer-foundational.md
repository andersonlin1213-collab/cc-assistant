# Plan 3b: Tool Layer (Foundational Tools)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Tool abstraction and ship the two foundational tools (`file_ops`, `shell`). Each tool exposes a JSON-Schema parameter spec consumable by the LLM client (Plan 3a) and supports a `dry_run` mode that returns "would-do" descriptions without side effects.

**Architecture:** A `Tool` ABC defines `name`, `description`, `parameters_schema`, `risk_level`, and an async `execute(dry_run, **params)` method returning a `ToolResult`. Tools are independent of the LLM layer — they expose a JSON Schema dict and a uniform result type, and the Orchestrator (Plan 3c) bridges them. A small `ALL_TOOLS` registry list in `src/tools/__init__.py` is the single source of truth for which tools the agent can use; Plan 4 extends it.

**Tech Stack:** Python 3.11+ asyncio, `subprocess` (for shell), `pytest-asyncio` (auto mode already enabled). No new third-party dependencies.

**Out of scope (deferred):** `web_search`, `code_edit`, `database`, `notifier`, `api_caller` — Plan 4. Permission gates beyond `dry_run` (e.g., risk-level enforcement) — Plan 3c when the Orchestrator wires routing rules.

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `src/tools/__init__.py` | Package marker + `ALL_TOOLS` registry list |
| Create | `src/tools/base.py` | `Tool` ABC, `ToolResult` dataclass |
| Create | `src/tools/file_ops.py` | `FileOpsTool` — read/write/delete |
| Create | `src/tools/shell.py` | `ShellTool` — subprocess execution with timeout |
| Create | `tests/test_tool_base.py` | ABC enforcement + ToolResult shape |
| Create | `tests/test_tool_file_ops.py` | FileOpsTool unit tests including dry_run |
| Create | `tests/test_tool_shell.py` | ShellTool unit tests including dry_run + timeout |
| Create | `tests/test_tool_registry.py` | `ALL_TOOLS` includes the foundational tools |

---

### Task 1: Tool ABC and Registry Skeleton

**Files:**
- Create: `src/tools/__init__.py`
- Create: `src/tools/base.py`
- Create: `tests/test_tool_base.py`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_tool_base.py`:

```python
import pytest

from src.tools.base import Tool, ToolResult


def test_tool_result_minimal():
    r = ToolResult(success=True, output="hello")
    assert r.success is True
    assert r.output == "hello"
    assert r.error is None
    assert r.metadata is None


def test_tool_result_with_error_and_metadata():
    r = ToolResult(
        success=False,
        output="",
        error="boom",
        metadata={"returncode": 2},
    )
    assert r.success is False
    assert r.error == "boom"
    assert r.metadata == {"returncode": 2}


def test_tool_is_abstract():
    """Cannot instantiate Tool directly — execute() is abstract."""
    with pytest.raises(TypeError):
        Tool()  # type: ignore[abstract]


def test_tool_subclass_must_implement_execute():
    """A subclass without execute() can be defined but not instantiated."""

    class Incomplete(Tool):
        name = "incomplete"
        description = "missing execute"
        parameters_schema = {"type": "object"}

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


async def test_tool_subclass_with_execute_works():
    class Echo(Tool):
        name = "echo"
        description = "Echo the input"
        parameters_schema = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }
        risk_level = "low"

        async def execute(self, dry_run: bool = False, **params) -> ToolResult:
            return ToolResult(success=True, output=params["text"])

    tool = Echo()
    assert tool.name == "echo"
    assert tool.risk_level == "low"
    result = await tool.execute(text="hi")
    assert result.success
    assert result.output == "hi"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_tool_base.py -v
```

Expected: FAIL — cannot import from `src.tools.base`.

- [ ] **Step 3: Write implementation**

Write `src/tools/base.py`:

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Optional


@dataclass
class ToolResult:
    """Uniform return type for all Tool.execute() calls."""

    success: bool
    output: str
    error: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class Tool(ABC):
    """Abstract base class for all agent tools.

    Subclasses must define class-level `name`, `description`, `parameters_schema`,
    optionally `risk_level`, and implement `execute()`.

    `parameters_schema` is a JSON Schema dict. The Orchestrator (Plan 3c) translates
    this into the LLM client's ToolDefinition shape — Tools deliberately do NOT
    import from src.agent.llm to keep the layers decoupled.

    `dry_run=True` instructs the tool to skip side-effecting operations (writes,
    deletes, shell execution, network calls) and return a description of what
    *would* happen. Read operations may proceed in dry_run mode since they
    have no side effects.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    parameters_schema: ClassVar[dict[str, Any]]
    risk_level: ClassVar[str] = "low"  # "low" | "high"

    @abstractmethod
    async def execute(self, dry_run: bool = False, **params: Any) -> ToolResult:
        """Run the tool with the given parameters.

        Implementations should:
          - Validate required params and return ToolResult(success=False, error=...) on missing.
          - Honor dry_run for any side-effecting operation.
          - Catch expected operational errors (file not found, command timeout, etc.)
            and return them as `ToolResult(success=False, error=...)` rather than raising.
          - Let unexpected programmer errors (TypeError, KeyError on internal logic)
            propagate so they surface as bugs.
        """
```

- [ ] **Step 4: Write `src/tools/__init__.py` (placeholder for now; tools added in later tasks)**

Write `src/tools/__init__.py`:

```python
"""Tool registry. Each foundational tool registers itself by being added to ALL_TOOLS.

When Plan 4 ships additional tools (web_search, code_edit, database, notifier,
api_caller), append them to ALL_TOOLS. The Orchestrator instantiates everything
in this list at startup.
"""

from src.tools.base import Tool, ToolResult

# Populated as tools are added in subsequent tasks.
ALL_TOOLS: list[type[Tool]] = []

__all__ = ["Tool", "ToolResult", "ALL_TOOLS"]
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/test_tool_base.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add src/tools/__init__.py src/tools/base.py tests/test_tool_base.py
git commit -m "feat: add Tool ABC and ToolResult dataclass with empty registry"
```

---

### Task 2: FileOpsTool

**Files:**
- Create: `src/tools/file_ops.py`
- Create: `tests/test_tool_file_ops.py`
- Modify: `src/tools/__init__.py` (register tool)

- [ ] **Step 1: Write the failing tests**

Write `tests/test_tool_file_ops.py`:

```python
from pathlib import Path

from src.tools.file_ops import FileOpsTool


async def test_read_existing_file(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("hello world", encoding="utf-8")

    tool = FileOpsTool()
    result = await tool.execute(operation="read", path=str(f))

    assert result.success is True
    assert result.output == "hello world"


async def test_read_missing_file_returns_error(tmp_path):
    tool = FileOpsTool()
    result = await tool.execute(operation="read", path=str(tmp_path / "nope.txt"))

    assert result.success is False
    assert result.error is not None
    assert "not found" in result.error.lower()


async def test_write_new_file(tmp_path):
    target = tmp_path / "out.txt"
    tool = FileOpsTool()
    result = await tool.execute(
        operation="write",
        path=str(target),
        content="new content",
    )

    assert result.success is True
    assert target.read_text(encoding="utf-8") == "new content"


async def test_write_overwrites_existing(tmp_path):
    target = tmp_path / "existing.txt"
    target.write_text("old", encoding="utf-8")

    tool = FileOpsTool()
    await tool.execute(operation="write", path=str(target), content="new")

    assert target.read_text(encoding="utf-8") == "new"


async def test_write_dry_run_does_not_create_file(tmp_path):
    target = tmp_path / "ghost.txt"
    tool = FileOpsTool()
    result = await tool.execute(
        operation="write",
        path=str(target),
        content="should not exist",
        dry_run=True,
    )

    assert result.success is True
    assert "[dry-run]" in result.output
    assert not target.exists()


async def test_delete_existing_file(tmp_path):
    target = tmp_path / "doomed.txt"
    target.write_text("x", encoding="utf-8")

    tool = FileOpsTool()
    result = await tool.execute(operation="delete", path=str(target))

    assert result.success is True
    assert not target.exists()


async def test_delete_dry_run_does_not_delete(tmp_path):
    target = tmp_path / "saved.txt"
    target.write_text("survives", encoding="utf-8")

    tool = FileOpsTool()
    result = await tool.execute(operation="delete", path=str(target), dry_run=True)

    assert result.success is True
    assert "[dry-run]" in result.output
    assert target.exists()


async def test_unknown_operation_returns_error():
    tool = FileOpsTool()
    result = await tool.execute(operation="lol", path="/tmp/whatever")

    assert result.success is False
    assert "unknown operation" in (result.error or "").lower()


async def test_missing_required_params_returns_error():
    tool = FileOpsTool()
    result = await tool.execute(operation="read")  # no path

    assert result.success is False
    assert "path" in (result.error or "").lower()


async def test_unicode_content_round_trip(tmp_path):
    """Chinese (and other UTF-8) content must round-trip via write+read."""
    target = tmp_path / "chinese.md"
    tool = FileOpsTool()

    text = "你好，世界。\n部署到生产环境。"
    write_result = await tool.execute(operation="write", path=str(target), content=text)
    read_result = await tool.execute(operation="read", path=str(target))

    assert write_result.success
    assert read_result.success
    assert read_result.output == text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_tool_file_ops.py -v
```

Expected: FAIL — cannot import `FileOpsTool`.

- [ ] **Step 3: Write implementation**

Write `src/tools/file_ops.py`:

```python
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from src.tools.base import Tool, ToolResult


class FileOpsTool(Tool):
    """Read, write, or delete a local file.

    All file I/O is dispatched to a thread (asyncio.to_thread) so the event loop
    is not blocked by disk operations on slow storage.

    `dry_run=True` skips writes and deletes; reads still run since they have no
    side effects.
    """

    name = "file_ops"
    description = (
        "Read, write, or delete a local file. "
        "Operations: 'read' (returns content), 'write' (creates/overwrites), 'delete' (removes)."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["read", "write", "delete"],
                "description": "Which operation to perform.",
            },
            "path": {
                "type": "string",
                "description": "Absolute or relative file path.",
            },
            "content": {
                "type": "string",
                "description": "Required for 'write'. UTF-8 encoded.",
            },
        },
        "required": ["operation", "path"],
    }
    risk_level = "low"

    async def execute(self, dry_run: bool = False, **params: Any) -> ToolResult:
        op = params.get("operation")
        path_str = params.get("path")

        if not op:
            return ToolResult(success=False, output="", error="missing 'operation' parameter")
        if not path_str:
            return ToolResult(success=False, output="", error="missing 'path' parameter")

        path = Path(path_str)

        if op == "read":
            return await self._read(path)
        if op == "write":
            content = params.get("content", "")
            return await self._write(path, content, dry_run=dry_run)
        if op == "delete":
            return await self._delete(path, dry_run=dry_run)

        return ToolResult(success=False, output="", error=f"unknown operation: {op!r}")

    @staticmethod
    async def _read(path: Path) -> ToolResult:
        if not path.exists():
            return ToolResult(success=False, output="", error=f"file not found: {path}")
        try:
            content = await asyncio.to_thread(path.read_text, encoding="utf-8")
        except OSError as e:
            return ToolResult(success=False, output="", error=f"read failed: {e}")
        return ToolResult(success=True, output=content)

    @staticmethod
    async def _write(path: Path, content: str, dry_run: bool) -> ToolResult:
        if dry_run:
            return ToolResult(
                success=True,
                output=f"[dry-run] would write {len(content)} chars to {path}",
            )
        try:
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(path.write_text, content, encoding="utf-8")
        except OSError as e:
            return ToolResult(success=False, output="", error=f"write failed: {e}")
        return ToolResult(success=True, output=f"wrote {len(content)} chars to {path}")

    @staticmethod
    async def _delete(path: Path, dry_run: bool) -> ToolResult:
        if dry_run:
            return ToolResult(success=True, output=f"[dry-run] would delete {path}")
        if not path.exists():
            return ToolResult(success=False, output="", error=f"file not found: {path}")
        try:
            await asyncio.to_thread(path.unlink)
        except OSError as e:
            return ToolResult(success=False, output="", error=f"delete failed: {e}")
        return ToolResult(success=True, output=f"deleted {path}")
```

- [ ] **Step 4: Register tool in `src/tools/__init__.py`**

Edit `src/tools/__init__.py`:

```python
"""Tool registry. Each foundational tool registers itself by being added to ALL_TOOLS.

When Plan 4 ships additional tools (web_search, code_edit, database, notifier,
api_caller), append them to ALL_TOOLS. The Orchestrator instantiates everything
in this list at startup.
"""

from src.tools.base import Tool, ToolResult
from src.tools.file_ops import FileOpsTool

# Populated as tools are added in subsequent tasks.
ALL_TOOLS: list[type[Tool]] = [
    FileOpsTool,
]

__all__ = ["Tool", "ToolResult", "ALL_TOOLS", "FileOpsTool"]
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/test_tool_file_ops.py -v
```

Expected: 10 passed.

- [ ] **Step 6: Commit**

```bash
git add src/tools/file_ops.py src/tools/__init__.py tests/test_tool_file_ops.py
git commit -m "feat: add FileOpsTool with read/write/delete and dry_run support"
```

---

### Task 3: ShellTool

**Files:**
- Create: `src/tools/shell.py`
- Create: `tests/test_tool_shell.py`
- Modify: `src/tools/__init__.py` (register tool)

- [ ] **Step 1: Write the failing tests**

Write `tests/test_tool_shell.py`:

```python
import sys

import pytest

from src.tools.shell import ShellTool


async def test_shell_runs_simple_command():
    tool = ShellTool()
    # `python -c` works on all platforms; avoid `echo` which differs across shells.
    result = await tool.execute(
        command=f'{sys.executable} -c "print(1 + 2)"'
    )

    assert result.success is True
    assert result.output.strip() == "3"
    assert result.metadata is not None
    assert result.metadata["returncode"] == 0


async def test_shell_captures_stderr_on_failure():
    tool = ShellTool()
    result = await tool.execute(
        command=f'{sys.executable} -c "import sys; sys.stderr.write(\\"oops\\"); sys.exit(2)"'
    )

    assert result.success is False
    assert result.error is not None
    assert "oops" in result.error
    assert result.metadata["returncode"] == 2


async def test_shell_dry_run_does_not_execute():
    """A dry_run shell call must not actually run anything."""
    tool = ShellTool()
    # Use a command that would have an observable side effect if it ran:
    # writing a file. But since we're in dry_run mode, no file is created.
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        marker = Path(td) / "marker.txt"
        cmd = f'{sys.executable} -c "open(r\\"{marker}\\", \\"w\\").write(\\"ran\\")"'

        result = await tool.execute(command=cmd, dry_run=True)

        assert result.success is True
        assert "[dry-run]" in result.output
        assert not marker.exists()


async def test_shell_timeout():
    tool = ShellTool()
    # Sleep longer than the timeout
    result = await tool.execute(
        command=f'{sys.executable} -c "import time; time.sleep(2)"',
        timeout_seconds=1,
    )

    assert result.success is False
    assert "timed out" in (result.error or "").lower()


async def test_shell_missing_command_returns_error():
    tool = ShellTool()
    result = await tool.execute()  # no command

    assert result.success is False
    assert "command" in (result.error or "").lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_tool_shell.py -v
```

Expected: FAIL — cannot import `ShellTool`.

- [ ] **Step 3: Write implementation**

Write `src/tools/shell.py`:

```python
from __future__ import annotations

import asyncio
import subprocess
from typing import Any

from src.tools.base import Tool, ToolResult


class ShellTool(Tool):
    """Execute a shell command.

    `shell=True` is used so the LLM can issue commands with pipes and redirection
    natively. This means the caller is fully trusted (the LLM's output, gated by
    routing rules in skills/rules.md). The tool is marked `risk_level="high"` so
    Plan 3c's Orchestrator can require human approval before invoking it.

    Output and errors are captured separately. `metadata.returncode` is always
    populated when the command actually ran.
    """

    name = "shell"
    description = (
        "Execute a shell command. Returns stdout (output), stderr (error on failure), "
        "and exit code (metadata.returncode)."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run."},
            "timeout_seconds": {
                "type": "integer",
                "description": "Hard timeout. Default 30.",
                "default": 30,
            },
        },
        "required": ["command"],
    }
    risk_level = "high"

    DEFAULT_TIMEOUT_SECONDS = 30

    async def execute(self, dry_run: bool = False, **params: Any) -> ToolResult:
        command = params.get("command")
        if not command:
            return ToolResult(success=False, output="", error="missing 'command' parameter")
        timeout = int(params.get("timeout_seconds") or self.DEFAULT_TIMEOUT_SECONDS)

        if dry_run:
            return ToolResult(success=True, output=f"[dry-run] would run: {command}")

        try:
            result = await asyncio.to_thread(
                subprocess.run,
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error=f"command timed out after {timeout}s",
            )

        success = result.returncode == 0
        return ToolResult(
            success=success,
            output=result.stdout,
            error=result.stderr if not success else None,
            metadata={"returncode": result.returncode},
        )
```

- [ ] **Step 4: Register tool in `src/tools/__init__.py`**

Edit `src/tools/__init__.py`:

```python
"""Tool registry. Each foundational tool registers itself by being added to ALL_TOOLS.

When Plan 4 ships additional tools (web_search, code_edit, database, notifier,
api_caller), append them to ALL_TOOLS. The Orchestrator instantiates everything
in this list at startup.
"""

from src.tools.base import Tool, ToolResult
from src.tools.file_ops import FileOpsTool
from src.tools.shell import ShellTool

ALL_TOOLS: list[type[Tool]] = [
    FileOpsTool,
    ShellTool,
]

__all__ = ["Tool", "ToolResult", "ALL_TOOLS", "FileOpsTool", "ShellTool"]
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/test_tool_shell.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add src/tools/shell.py src/tools/__init__.py tests/test_tool_shell.py
git commit -m "feat: add ShellTool with subprocess execution, timeout, and dry_run"
```

---

### Task 4: Registry Test

**Files:**
- Create: `tests/test_tool_registry.py`

A small test ensures that `ALL_TOOLS` exposes the expected foundational tools and that each is instantiable. This catches forgotten registrations when new tools are added.

- [ ] **Step 1: Write the test**

Write `tests/test_tool_registry.py`:

```python
from src.tools import ALL_TOOLS
from src.tools.file_ops import FileOpsTool
from src.tools.shell import ShellTool


def test_registry_contains_foundational_tools():
    assert FileOpsTool in ALL_TOOLS
    assert ShellTool in ALL_TOOLS


def test_registry_tool_classes_are_instantiable():
    """Every class in ALL_TOOLS can be instantiated and exposes the required attrs."""
    for cls in ALL_TOOLS:
        instance = cls()
        assert isinstance(instance.name, str) and instance.name
        assert isinstance(instance.description, str) and instance.description
        assert isinstance(instance.parameters_schema, dict)
        assert instance.parameters_schema.get("type") == "object"
        assert instance.risk_level in {"low", "high"}


def test_registry_tool_names_are_unique():
    names = [cls().name for cls in ALL_TOOLS]
    assert len(names) == len(set(names)), f"duplicate tool names: {names}"
```

- [ ] **Step 2: Run the test**

```bash
uv run pytest tests/test_tool_registry.py -v
```

Expected: 3 passed.

- [ ] **Step 3: Run the full suite to confirm no regressions**

```bash
uv run pytest -v
```

Expected: all previous tests still pass + new ones from this plan. Cumulative across Plans 1+2+3b: 63 + 5 (base) + 10 (file_ops) + 5 (shell) + 3 (registry) = **86 passed**.

- [ ] **Step 4: Commit**

```bash
git add tests/test_tool_registry.py
git commit -m "test: verify ALL_TOOLS registry exposes foundational tools with valid contracts"
```

---

## Self-Review

**1. Spec coverage (Layer 3 — Tool portion):**
- `Tool` ABC with `name`, `description`, `parameters` (named `parameters_schema` here for clarity), `risk_level`, and async `execute()`: Task 1.
- `dry_run` mode (mentioned in spec's CLI section "`cc-assistant run --dry-run`"): every Tool's `execute(dry_run=True, ...)` skips writes.
- Auto-discovery: simplified to an explicit `ALL_TOOLS` list in `__init__.py`. Plan 4 extends the list. This is a deliberate simplification over runtime discovery — explicit beats clever, and the registry is small.
- `file_ops` tool (read/write/delete): Task 2.
- `shell` tool (subprocess via ThreadPoolExecutor — `asyncio.to_thread`): Task 3.
- The other 5 tools (`web_search`, `code_edit`, `database`, `notifier`, `api_caller`) are deferred to Plan 4 — explicitly listed in this plan's "Out of scope" section.

**2. Placeholder scan:**
- No "TBD" / "TODO" / "fill in details".
- All test bodies have real assertions.
- All implementation steps include full code.
- The registry note for "Plan 4 will extend" is a roadmap pointer, not a placeholder.

**3. Type consistency:**
- `Tool.execute(dry_run: bool = False, **params: Any) -> ToolResult` — same signature in base.py, file_ops.py, shell.py, and all tests.
- `ToolResult(success, output, error, metadata)` — fields used uniformly across all tool implementations and assertions.
- `parameters_schema` is `dict[str, Any]` consistently. Each tool's schema is a JSON-Schema object with `type: "object"` and `required` keys.
- `risk_level` is `"low"` for `file_ops`, `"high"` for `shell`. Plan 3c's Orchestrator will use this to gate execution.

**4. Cross-plan boundary:**
- Tool layer does NOT import from `src.agent.llm`. Plan 3c will write the bridge. This keeps each plan's diff small and independently reviewable.

**5. Async test mode:**
- `asyncio_mode = "auto"` in pyproject.toml means `async def test_*` is auto-detected. No decorators needed.

**6. Cross-platform notes:**
- Tests use `sys.executable` for the subprocess command rather than `echo` so they pass on Windows. The shell command itself uses `shell=True` which is safe with the `python -c` pattern.

All clean. Ready for Plan 3c (Orchestrator) once both 3a and 3b ship.
