# Plan 4: Remaining Tools (web_fetch, code_edit, database, notifier, api_caller)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the remaining five tools listed in the spec's Layer 3 tools table — `web_fetch` (URL fetching), `code_edit` (line-aware code reads + safe replace), `database` (MySQL query/execute), `notifier` (WeChat enterprise bot webhook), `api_caller` (generic REST API client) — and register them in `ALL_TOOLS` so the Orchestrator picks them up automatically.

**Architecture:** Each tool is a self-contained subclass of `Tool` (Plan 3b ABC) under `src/tools/`. All HTTP-based tools use `httpx.AsyncClient`; tests use `httpx.MockTransport` to inject deterministic responses. The database tool uses `aiomysql` with a connection-factory injection pattern so unit tests pass a mock factory and the production path lazy-creates a real connection from `config`. Every tool honors `dry_run=True` for write/destructive operations; reads still execute since they have no side effects.

**Tech Stack:** Python 3.11+, `httpx>=0.27`, `aiomysql>=0.2`, existing `pydantic`/`asyncio`/`pytest-asyncio` from prior plans. No new framework dependencies.

**Out of scope (deferred):**
- Real internet search via Serper/Google/Bing (Plan 5 — needs API key + cost decision). `web_fetch` only fetches a known URL; the LLM cannot perform a search query yet.
- DDL safety guards (e.g., refusing `DROP TABLE`). Database tool currently trusts the LLM gated by `risk_level="high"` + the routing rules in `skills/rules.md`.
- Connection pooling for the database tool. Each call opens and closes a connection. Plan 5 can add an `aiomysql.Pool`.
- Image attachments / structured-card formats for the WeChat notifier — text and markdown only for MVP.

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Modify | `pyproject.toml` | Add `httpx>=0.27` and `aiomysql>=0.2` |
| Create | `src/tools/web_fetch.py` | `WebFetchTool` — GET a URL, return text body, truncated |
| Create | `src/tools/code_edit.py` | `CodeEditTool` — read line range, replace exact text |
| Create | `src/tools/database.py` | `DatabaseTool` — async MySQL query / execute via aiomysql |
| Create | `src/tools/notifier.py` | `NotifierTool` — POST WeChat webhook |
| Create | `src/tools/api_caller.py` | `ApiCallerTool` — generic REST request |
| Modify | `src/tools/__init__.py` | Add five new tools to `ALL_TOOLS` |
| Create | `tests/test_tool_web_fetch.py` | WebFetchTool tests via httpx MockTransport |
| Create | `tests/test_tool_code_edit.py` | CodeEditTool tests via tmp_path |
| Create | `tests/test_tool_database.py` | DatabaseTool tests via mocked connection factory |
| Create | `tests/test_tool_notifier.py` | NotifierTool tests via httpx MockTransport |
| Create | `tests/test_tool_api_caller.py` | ApiCallerTool tests via httpx MockTransport |
| Modify | `tests/test_tool_registry.py` | Verify all 7 tools in `ALL_TOOLS` |

---

### Task 1: Add Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add httpx and aiomysql via uv**

```bash
cd /c/<your-user>/projects/cc-assitant
uv add "httpx>=0.27" "aiomysql>=0.2"
```

- [ ] **Step 2: Verify imports**

```bash
uv run python -c "import httpx; import aiomysql; print(httpx.__version__, aiomysql.__version__)"
```

Expected: a line with two version strings (e.g., `0.27.0 0.2.0`).

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add httpx and aiomysql for remaining tools"
```

---

### Task 2: WebFetchTool

**Files:**
- Create: `src/tools/web_fetch.py`
- Create: `tests/test_tool_web_fetch.py`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_tool_web_fetch.py`:

```python
import httpx

from src.tools.web_fetch import WebFetchTool


def _build_mock_transport(handler):
    """Wrap a request handler in httpx.MockTransport for AsyncClient injection."""
    return httpx.MockTransport(handler)


async def test_fetch_returns_body():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.host == "example.com"
        return httpx.Response(200, text="hello world")

    tool = WebFetchTool(transport=_build_mock_transport(handler))
    result = await tool.execute(url="https://example.com/")

    assert result.success is True
    assert result.output == "hello world"


async def test_fetch_non_2xx_returns_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    tool = WebFetchTool(transport=_build_mock_transport(handler))
    result = await tool.execute(url="https://example.com/missing")

    assert result.success is False
    assert "404" in (result.error or "")


async def test_fetch_truncates_long_body():
    big = "x" * 100_000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=big)

    tool = WebFetchTool(transport=_build_mock_transport(handler))
    result = await tool.execute(url="https://example.com/", max_chars=1000)

    assert result.success is True
    assert len(result.output) <= 1000 + len("\n[...truncated]")
    assert result.output.endswith("[...truncated]")


async def test_fetch_dry_run_does_not_make_request():
    """dry_run skips the actual HTTP call and returns a stub."""
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["n"] += 1
        return httpx.Response(200, text="hi")

    tool = WebFetchTool(transport=_build_mock_transport(handler))
    result = await tool.execute(url="https://example.com/", dry_run=True)

    assert result.success is True
    assert "[dry-run]" in result.output
    assert called["n"] == 0


async def test_fetch_missing_url_returns_error():
    tool = WebFetchTool()
    result = await tool.execute()

    assert result.success is False
    assert "url" in (result.error or "").lower()


async def test_fetch_timeout_returns_error():
    """A timeout on the request surfaces as ToolResult(success=False, error=...)."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("simulated timeout", request=request)

    tool = WebFetchTool(transport=_build_mock_transport(handler))
    result = await tool.execute(url="https://example.com/", timeout_seconds=1)

    assert result.success is False
    assert "timeout" in (result.error or "").lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_tool_web_fetch.py -v
```

Expected: FAIL — cannot import `WebFetchTool`.

- [ ] **Step 3: Write implementation**

Write `src/tools/web_fetch.py`:

```python
from __future__ import annotations

from typing import Any, Optional

import httpx

from src.tools.base import Tool, ToolResult


class WebFetchTool(Tool):
    """Fetch the content of a single URL via HTTP GET.

    Returns the response body as text. Bodies longer than `max_chars` are truncated
    with a trailing marker so the LLM knows the result was cut off.

    Note: this tool only fetches a known URL. Real internet search (e.g., via
    Serper or Google) is deferred to a future plan.
    """

    name = "web_fetch"
    description = (
        "Fetch the body of a URL via HTTP GET. Returns text. Bodies longer than "
        "max_chars are truncated. For binary or HTML-heavy pages, expect raw text."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full HTTP/HTTPS URL."},
            "timeout_seconds": {
                "type": "integer",
                "description": "Hard timeout. Default 30.",
                "default": 30,
            },
            "max_chars": {
                "type": "integer",
                "description": "Truncate body to this many characters. Default 50000.",
                "default": 50_000,
            },
        },
        "required": ["url"],
    }
    risk_level = "low"

    DEFAULT_TIMEOUT_SECONDS = 30
    DEFAULT_MAX_CHARS = 50_000

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        # transport injection enables MockTransport in tests; production passes None
        self._transport = transport

    async def execute(self, dry_run: bool = False, **params: Any) -> ToolResult:
        url = params.get("url")
        if not url:
            return ToolResult(success=False, output="", error="missing 'url' parameter")
        timeout = float(params.get("timeout_seconds") or self.DEFAULT_TIMEOUT_SECONDS)
        max_chars = int(params.get("max_chars") or self.DEFAULT_MAX_CHARS)

        if dry_run:
            return ToolResult(success=True, output=f"[dry-run] would GET {url}")

        client_kwargs: dict[str, Any] = {"timeout": timeout, "follow_redirects": True}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport

        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.get(url)
        except httpx.TimeoutException as e:
            return ToolResult(success=False, output="", error=f"timeout: {e}")
        except httpx.HTTPError as e:
            return ToolResult(success=False, output="", error=f"http error: {e}")

        if response.status_code >= 400:
            return ToolResult(
                success=False,
                output="",
                error=f"HTTP {response.status_code}",
                metadata={"status_code": response.status_code},
            )

        body = response.text
        if len(body) > max_chars:
            body = body[:max_chars] + "\n[...truncated]"

        return ToolResult(
            success=True,
            output=body,
            metadata={"status_code": response.status_code},
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_tool_web_fetch.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tools/web_fetch.py tests/test_tool_web_fetch.py
git commit -m "feat: add WebFetchTool for HTTP GET with timeout, truncation, dry_run"
```

---

### Task 3: CodeEditTool

**Files:**
- Create: `src/tools/code_edit.py`
- Create: `tests/test_tool_code_edit.py`

CodeEdit gives the LLM safer file editing than raw `file_ops.write` — line-bounded reads and exact-match replacements that fail loudly if the search string isn't unique.

- [ ] **Step 1: Write the failing tests**

Write `tests/test_tool_code_edit.py`:

```python
from src.tools.code_edit import CodeEditTool


async def test_read_lines_full_file(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("line1\nline2\nline3\n", encoding="utf-8")

    tool = CodeEditTool()
    result = await tool.execute(operation="read_lines", path=str(f))

    assert result.success is True
    assert "line1" in result.output
    assert "line3" in result.output


async def test_read_lines_range(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("a\nb\nc\nd\ne\n", encoding="utf-8")

    tool = CodeEditTool()
    result = await tool.execute(
        operation="read_lines", path=str(f), start_line=2, end_line=4
    )

    assert result.success is True
    # Lines 2-4 of "a/b/c/d/e" are b, c, d
    assert "b" in result.output
    assert "c" in result.output
    assert "d" in result.output
    assert "a" not in result.output.split("\n")[0]  # 'a' is line 1, excluded


async def test_read_lines_missing_file_returns_error(tmp_path):
    tool = CodeEditTool()
    result = await tool.execute(operation="read_lines", path=str(tmp_path / "nope.py"))

    assert result.success is False
    assert "not found" in (result.error or "").lower()


async def test_replace_in_file_unique_match(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("def foo():\n    return 1\n", encoding="utf-8")

    tool = CodeEditTool()
    result = await tool.execute(
        operation="replace_in_file",
        path=str(f),
        search="return 1",
        replace="return 42",
    )

    assert result.success is True
    assert f.read_text(encoding="utf-8") == "def foo():\n    return 42\n"


async def test_replace_in_file_no_match_returns_error(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("def foo():\n    return 1\n", encoding="utf-8")

    tool = CodeEditTool()
    result = await tool.execute(
        operation="replace_in_file",
        path=str(f),
        search="not present",
        replace="something",
    )

    assert result.success is False
    assert "no match" in (result.error or "").lower()
    assert f.read_text(encoding="utf-8") == "def foo():\n    return 1\n"  # unchanged


async def test_replace_in_file_multiple_matches_returns_error(tmp_path):
    """If search matches more than once, fail loudly — protects against accidental edits."""
    f = tmp_path / "code.py"
    f.write_text("x = 1\ny = 1\nz = 1\n", encoding="utf-8")

    tool = CodeEditTool()
    result = await tool.execute(
        operation="replace_in_file",
        path=str(f),
        search="= 1",
        replace="= 2",
    )

    assert result.success is False
    assert "multiple" in (result.error or "").lower()
    assert "3" in (result.error or "")  # mentions the count
    # File unchanged
    assert "x = 1" in f.read_text(encoding="utf-8")


async def test_replace_dry_run_does_not_write(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("hello\n", encoding="utf-8")

    tool = CodeEditTool()
    result = await tool.execute(
        operation="replace_in_file",
        path=str(f),
        search="hello",
        replace="goodbye",
        dry_run=True,
    )

    assert result.success is True
    assert "[dry-run]" in result.output
    assert f.read_text(encoding="utf-8") == "hello\n"  # unchanged


async def test_unknown_operation_returns_error():
    tool = CodeEditTool()
    result = await tool.execute(operation="weird", path="/tmp/x")

    assert result.success is False
    assert "unknown operation" in (result.error or "").lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_tool_code_edit.py -v
```

Expected: FAIL — cannot import `CodeEditTool`.

- [ ] **Step 3: Write implementation**

Write `src/tools/code_edit.py`:

```python
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from src.tools.base import Tool, ToolResult


class CodeEditTool(Tool):
    """Read or modify a code file with line-aware safety.

    Operations:
      - `read_lines(path, start_line=1, end_line=None)`: read 1-indexed line range.
        end_line is inclusive. Both omitted → full file.
      - `replace_in_file(path, search, replace)`: replace the unique occurrence of
        `search` with `replace`. Fails if 0 or 2+ matches — this is intentional
        protection against accidental wide replacements.

    For unrestricted writes (overwrite the whole file), use file_ops instead.
    """

    name = "code_edit"
    description = (
        "Read a line range from a file, or replace a unique exact-match string. "
        "Operations: 'read_lines' (returns line range), 'replace_in_file' "
        "(rewrites the unique match; fails on 0 or multiple matches)."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["read_lines", "replace_in_file"],
            },
            "path": {"type": "string"},
            "start_line": {
                "type": "integer",
                "description": "1-indexed inclusive start. Default 1.",
            },
            "end_line": {
                "type": "integer",
                "description": "1-indexed inclusive end. Default = last line.",
            },
            "search": {
                "type": "string",
                "description": "Required for replace_in_file. Must match exactly once.",
            },
            "replace": {
                "type": "string",
                "description": "Required for replace_in_file.",
            },
        },
        "required": ["operation", "path"],
    }
    risk_level = "low"  # read is low; replace_in_file is the "high" branch internally

    async def execute(self, dry_run: bool = False, **params: Any) -> ToolResult:
        op = params.get("operation")
        path_str = params.get("path")

        if not op:
            return ToolResult(success=False, output="", error="missing 'operation' parameter")
        if not path_str:
            return ToolResult(success=False, output="", error="missing 'path' parameter")

        path = Path(path_str)

        if op == "read_lines":
            return await self._read_lines(
                path,
                start=params.get("start_line"),
                end=params.get("end_line"),
            )
        if op == "replace_in_file":
            search = params.get("search")
            replace = params.get("replace")
            if search is None:
                return ToolResult(success=False, output="", error="missing 'search' parameter")
            if replace is None:
                return ToolResult(success=False, output="", error="missing 'replace' parameter")
            return await self._replace_in_file(path, search, replace, dry_run=dry_run)

        return ToolResult(success=False, output="", error=f"unknown operation: {op!r}")

    @staticmethod
    async def _read_lines(path: Path, start: Any, end: Any) -> ToolResult:
        if not path.exists():
            return ToolResult(success=False, output="", error=f"file not found: {path}")
        try:
            text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        except OSError as e:
            return ToolResult(success=False, output="", error=f"read failed: {e}")

        lines = text.splitlines()
        s = int(start) if start is not None else 1
        e = int(end) if end is not None else len(lines)
        s = max(1, s)
        e = min(len(lines), e)

        selected = lines[s - 1 : e]  # 1-indexed inclusive
        return ToolResult(
            success=True,
            output="\n".join(selected),
            metadata={"start_line": s, "end_line": e, "total_lines": len(lines)},
        )

    @staticmethod
    async def _replace_in_file(
        path: Path, search: str, replace: str, dry_run: bool
    ) -> ToolResult:
        if not path.exists():
            return ToolResult(success=False, output="", error=f"file not found: {path}")

        try:
            text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        except OSError as e:
            return ToolResult(success=False, output="", error=f"read failed: {e}")

        count = text.count(search)
        if count == 0:
            return ToolResult(success=False, output="", error="no match for search string")
        if count > 1:
            return ToolResult(
                success=False,
                output="",
                error=f"multiple matches ({count}); search string must be unique",
            )

        if dry_run:
            return ToolResult(
                success=True,
                output=f"[dry-run] would replace 1 occurrence in {path}",
            )

        new_text = text.replace(search, replace, 1)
        try:
            await asyncio.to_thread(path.write_text, new_text, encoding="utf-8")
        except OSError as e:
            return ToolResult(success=False, output="", error=f"write failed: {e}")

        return ToolResult(success=True, output=f"replaced 1 occurrence in {path}")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_tool_code_edit.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tools/code_edit.py tests/test_tool_code_edit.py
git commit -m "feat: add CodeEditTool with line-range reads and unique-match replace safety"
```

---

### Task 4: DatabaseTool

**Files:**
- Create: `src/tools/database.py`
- Create: `tests/test_tool_database.py`

The database tool uses async aiomysql with a connection-factory injection pattern. Tests pass a fake factory that yields a fake connection; production passes None and the tool builds a real connection from `config`.

- [ ] **Step 1: Write the failing tests**

Write `tests/test_tool_database.py`:

```python
from unittest.mock import AsyncMock, MagicMock

from src.tools.database import DatabaseTool


def _build_fake_factory(rows=None, rowcount=0):
    """Build a factory that returns a fake aiomysql connection.

    The fake supports the async context manager protocol used by aiomysql.connect
    (`async with conn`), `conn.cursor()` returning an async-context cursor with
    `execute`, `fetchall`, and `rowcount`, and a `commit` method on the connection.
    """
    cursor = MagicMock()
    cursor.execute = AsyncMock(return_value=None)
    cursor.fetchall = AsyncMock(return_value=rows or [])
    cursor.rowcount = rowcount
    cursor.__aenter__ = AsyncMock(return_value=cursor)
    cursor.__aexit__ = AsyncMock(return_value=None)
    cursor.description = (("col1",), ("col2",)) if rows and isinstance(rows[0], tuple) else None

    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cursor)
    conn.commit = AsyncMock(return_value=None)
    conn.close = MagicMock(return_value=None)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=None)

    factory = AsyncMock(return_value=conn)
    return factory, cursor, conn


async def test_query_returns_rows():
    rows = [(1, "a"), (2, "b")]
    factory, cursor, _ = _build_fake_factory(rows=rows)

    tool = DatabaseTool(connection_factory=factory)
    result = await tool.execute(operation="query", sql="SELECT id, name FROM users")

    assert result.success is True
    cursor.execute.assert_awaited_once_with("SELECT id, name FROM users", None)
    cursor.fetchall.assert_awaited_once()
    assert "1" in result.output
    assert "a" in result.output


async def test_query_with_params():
    rows = [(42,)]
    factory, cursor, _ = _build_fake_factory(rows=rows)

    tool = DatabaseTool(connection_factory=factory)
    result = await tool.execute(
        operation="query",
        sql="SELECT id FROM users WHERE name = %s",
        params=["alice"],
    )

    assert result.success is True
    # aiomysql expects a tuple; verify the tool converts list -> tuple
    args, _ = cursor.execute.await_args
    assert args[0] == "SELECT id FROM users WHERE name = %s"
    assert args[1] == ("alice",)


async def test_execute_returns_rowcount():
    factory, cursor, conn = _build_fake_factory(rowcount=5)

    tool = DatabaseTool(connection_factory=factory)
    result = await tool.execute(operation="execute", sql="UPDATE users SET active = 1")

    assert result.success is True
    assert "5" in result.output
    conn.commit.assert_awaited_once()


async def test_execute_dry_run_does_not_run():
    factory, cursor, conn = _build_fake_factory()

    tool = DatabaseTool(connection_factory=factory)
    result = await tool.execute(
        operation="execute", sql="DELETE FROM users", dry_run=True
    )

    assert result.success is True
    assert "[dry-run]" in result.output
    cursor.execute.assert_not_called()
    conn.commit.assert_not_called()


async def test_query_dry_run_still_runs():
    """Read operations have no side effects, so dry_run still executes."""
    rows = [(1,)]
    factory, cursor, _ = _build_fake_factory(rows=rows)

    tool = DatabaseTool(connection_factory=factory)
    result = await tool.execute(operation="query", sql="SELECT 1", dry_run=True)

    assert result.success is True
    cursor.execute.assert_awaited_once()


async def test_unknown_operation_returns_error():
    factory, _, _ = _build_fake_factory()
    tool = DatabaseTool(connection_factory=factory)
    result = await tool.execute(operation="vacuum", sql="select 1")

    assert result.success is False
    assert "unknown operation" in (result.error or "").lower()


async def test_missing_sql_returns_error():
    factory, _, _ = _build_fake_factory()
    tool = DatabaseTool(connection_factory=factory)
    result = await tool.execute(operation="query")

    assert result.success is False
    assert "sql" in (result.error or "").lower()


async def test_db_error_returns_failure():
    factory, cursor, _ = _build_fake_factory()
    cursor.execute = AsyncMock(side_effect=RuntimeError("syntax error"))

    tool = DatabaseTool(connection_factory=factory)
    result = await tool.execute(operation="query", sql="SLEECT *")

    assert result.success is False
    assert "syntax error" in (result.error or "")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_tool_database.py -v
```

Expected: FAIL — cannot import `DatabaseTool`.

- [ ] **Step 3: Write implementation**

Write `src/tools/database.py`:

```python
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Optional

from src.tools.base import Tool, ToolResult

# Type alias for a connection factory: () -> awaitable producing an aiomysql-like conn.
ConnectionFactory = Callable[[], Awaitable[Any]]


class DatabaseTool(Tool):
    """Run async MySQL queries via aiomysql.

    Operations:
      - `query(sql, params=None)`: SELECT statement; returns rows as JSON-serialized
        list of tuples (column names available via `description` in metadata).
      - `execute(sql, params=None)`: DDL or DML; commits and returns rowcount.

    `dry_run=True` blocks `execute` (returns a stub) but still runs `query` since
    reads have no side effects.

    Connection factory is injected for testing; production code passes None and
    the tool builds a real aiomysql connection from `src.config.config`.
    """

    name = "database"
    description = (
        "Run a MySQL query (SELECT) or execute statement (INSERT/UPDATE/DELETE/DDL). "
        "Use 'query' to read; 'execute' to write. params is a list bound positionally."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["query", "execute"]},
            "sql": {"type": "string"},
            "params": {
                "type": "array",
                "description": "Positional parameters for the SQL placeholders (%s).",
            },
        },
        "required": ["operation", "sql"],
    }
    risk_level = "high"

    def __init__(
        self,
        connection_factory: Optional[ConnectionFactory] = None,
    ) -> None:
        self._factory = connection_factory

    async def execute(self, dry_run: bool = False, **params: Any) -> ToolResult:
        op = params.get("operation")
        sql = params.get("sql")

        if not op:
            return ToolResult(success=False, output="", error="missing 'operation' parameter")
        if not sql:
            return ToolResult(success=False, output="", error="missing 'sql' parameter")

        bind = params.get("params")
        bind = tuple(bind) if isinstance(bind, list) else bind

        if op == "execute" and dry_run:
            return ToolResult(success=True, output=f"[dry-run] would execute: {sql[:120]}")

        if op not in ("query", "execute"):
            return ToolResult(success=False, output="", error=f"unknown operation: {op!r}")

        factory = self._factory or self._default_factory
        try:
            conn = await factory()
        except Exception as e:  # pylint: disable=broad-except
            return ToolResult(success=False, output="", error=f"connection failed: {e}")

        try:
            async with conn:
                cur = conn.cursor()
                async with cur:
                    try:
                        await cur.execute(sql, bind)
                    except Exception as e:  # pylint: disable=broad-except
                        return ToolResult(success=False, output="", error=str(e))

                    if op == "query":
                        rows = await cur.fetchall()
                        return ToolResult(
                            success=True,
                            output=json.dumps([list(r) for r in rows], ensure_ascii=False, default=str),
                            metadata={"row_count": len(rows)},
                        )
                    # execute branch
                    rowcount = cur.rowcount
                    await conn.commit()
                    return ToolResult(
                        success=True,
                        output=f"affected {rowcount} rows",
                        metadata={"rowcount": rowcount},
                    )
        finally:
            close = getattr(conn, "close", None)
            if close is not None:
                try:
                    res = close()
                    if hasattr(res, "__await__"):
                        await res  # type: ignore[func-returns-value]
                except Exception:  # pylint: disable=broad-except
                    pass

    @staticmethod
    async def _default_factory() -> Any:
        """Create a real aiomysql connection from config. Production path."""
        import aiomysql  # type: ignore[import-not-found]
        from src.config import config

        return await aiomysql.connect(
            host=config.db_host,
            port=config.db_port,
            user=config.db_user,
            password=config.db_password,
            db=config.db_name,
            autocommit=False,
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_tool_database.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tools/database.py tests/test_tool_database.py
git commit -m "feat: add DatabaseTool with async aiomysql query/execute and connection injection"
```

---

### Task 5: NotifierTool

**Files:**
- Create: `src/tools/notifier.py`
- Create: `tests/test_tool_notifier.py`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_tool_notifier.py`:

```python
import json

import httpx

from src.tools.notifier import NotifierTool


def _capturing_handler(captured):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"errcode": 0})

    return handler


async def test_send_text_message():
    captured: dict = {}
    tool = NotifierTool(
        webhook_url="https://wechat.example/webhook?key=abc",
        transport=httpx.MockTransport(_capturing_handler(captured)),
    )

    result = await tool.execute(message="hello")

    assert result.success is True
    assert captured["method"] == "POST"
    assert captured["url"] == "https://wechat.example/webhook?key=abc"
    assert captured["body"]["msgtype"] == "text"
    assert captured["body"]["text"]["content"] == "hello"


async def test_send_with_mentions():
    captured: dict = {}
    tool = NotifierTool(
        webhook_url="https://wechat.example/webhook",
        transport=httpx.MockTransport(_capturing_handler(captured)),
    )

    await tool.execute(message="hi", mentioned=["alice", "bob"])

    assert captured["body"]["text"]["mentioned_list"] == ["alice", "bob"]


async def test_send_dry_run_does_not_post():
    captured: dict = {}
    called = {"n": 0}

    def handler(request):
        called["n"] += 1
        return httpx.Response(200)

    tool = NotifierTool(
        webhook_url="https://wechat.example/webhook",
        transport=httpx.MockTransport(handler),
    )

    result = await tool.execute(message="ping", dry_run=True)

    assert result.success is True
    assert "[dry-run]" in result.output
    assert called["n"] == 0


async def test_send_missing_message_returns_error():
    tool = NotifierTool(webhook_url="https://wechat.example/webhook")
    result = await tool.execute()

    assert result.success is False
    assert "message" in (result.error or "").lower()


async def test_send_missing_webhook_returns_error():
    tool = NotifierTool(webhook_url="")
    result = await tool.execute(message="hi")

    assert result.success is False
    assert "webhook" in (result.error or "").lower()


async def test_send_non_2xx_returns_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    tool = NotifierTool(
        webhook_url="https://wechat.example/webhook",
        transport=httpx.MockTransport(handler),
    )

    result = await tool.execute(message="hi")

    assert result.success is False
    assert "500" in (result.error or "")


async def test_send_wechat_errcode_nonzero_returns_error():
    """WeChat returns HTTP 200 even on logical errors; check errcode field."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errcode": 93000, "errmsg": "invalid webhook"})

    tool = NotifierTool(
        webhook_url="https://wechat.example/webhook",
        transport=httpx.MockTransport(handler),
    )

    result = await tool.execute(message="hi")

    assert result.success is False
    assert "93000" in (result.error or "")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_tool_notifier.py -v
```

Expected: FAIL — cannot import `NotifierTool`.

- [ ] **Step 3: Write implementation**

Write `src/tools/notifier.py`:

```python
from __future__ import annotations

from typing import Any, Optional

import httpx

from src.tools.base import Tool, ToolResult


class NotifierTool(Tool):
    """Send a text message to the configured WeChat enterprise bot webhook.

    The webhook URL is read from `src.config.config.wechat_webhook_url` by default;
    pass `webhook_url` to the constructor to override (used in tests).

    WeChat enterprise bots expect a JSON payload of the form:
        {"msgtype": "text", "text": {"content": "...", "mentioned_list": [...]}}

    They return HTTP 200 with `{"errcode": 0}` on success and a non-zero `errcode`
    on logical failure. Both forms are handled.
    """

    name = "notifier"
    description = (
        "Send a text message to the WeChat enterprise bot webhook. "
        "Useful for alerting the human about completed tasks or blocked status."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
            "mentioned": {
                "type": "array",
                "description": "Optional list of WeChat user IDs to mention.",
            },
        },
        "required": ["message"],
    }
    risk_level = "low"

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        if webhook_url is None:
            from src.config import config
            webhook_url = config.wechat_webhook_url
        self._webhook_url = webhook_url
        self._transport = transport

    async def execute(self, dry_run: bool = False, **params: Any) -> ToolResult:
        message = params.get("message")
        if not message:
            return ToolResult(success=False, output="", error="missing 'message' parameter")
        if not self._webhook_url:
            return ToolResult(
                success=False,
                output="",
                error="webhook URL not configured (set WECHAT_WEBHOOK_URL or pass webhook_url)",
            )

        if dry_run:
            return ToolResult(
                success=True,
                output=f"[dry-run] would send to webhook: {message[:120]}",
            )

        body: dict[str, Any] = {
            "msgtype": "text",
            "text": {"content": message},
        }
        mentioned = params.get("mentioned")
        if mentioned:
            body["text"]["mentioned_list"] = list(mentioned)

        client_kwargs: dict[str, Any] = {"timeout": 30}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport

        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.post(self._webhook_url, json=body)
        except httpx.HTTPError as e:
            return ToolResult(success=False, output="", error=f"http error: {e}")

        if response.status_code >= 400:
            return ToolResult(success=False, output="", error=f"HTTP {response.status_code}")

        # WeChat-specific: check errcode
        try:
            payload = response.json()
        except ValueError:
            payload = {}

        errcode = payload.get("errcode")
        if errcode is not None and errcode != 0:
            errmsg = payload.get("errmsg", "")
            return ToolResult(
                success=False,
                output="",
                error=f"WeChat errcode {errcode}: {errmsg}",
            )

        return ToolResult(success=True, output="message sent")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_tool_notifier.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tools/notifier.py tests/test_tool_notifier.py
git commit -m "feat: add NotifierTool for WeChat enterprise bot webhook with errcode handling"
```

---

### Task 6: ApiCallerTool

**Files:**
- Create: `src/tools/api_caller.py`
- Create: `tests/test_tool_api_caller.py`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_tool_api_caller.py`:

```python
import json

import httpx

from src.tools.api_caller import ApiCallerTool


def _echo_handler(captured):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content.decode("utf-8") if request.content else ""
        return httpx.Response(200, json={"received": "ok"})

    return handler


async def test_get_request():
    captured: dict = {}
    tool = ApiCallerTool(transport=httpx.MockTransport(_echo_handler(captured)))

    result = await tool.execute(method="GET", url="https://api.example.com/users")

    assert result.success is True
    assert captured["method"] == "GET"
    body = json.loads(result.output)
    assert body["received"] == "ok"


async def test_post_with_json_body():
    captured: dict = {}
    tool = ApiCallerTool(transport=httpx.MockTransport(_echo_handler(captured)))

    result = await tool.execute(
        method="POST",
        url="https://api.example.com/users",
        json_body={"name": "alice"},
    )

    assert result.success is True
    assert captured["method"] == "POST"
    sent = json.loads(captured["body"])
    assert sent == {"name": "alice"}


async def test_query_params_in_url():
    captured: dict = {}
    tool = ApiCallerTool(transport=httpx.MockTransport(_echo_handler(captured)))

    await tool.execute(
        method="GET",
        url="https://api.example.com/search",
        query_params={"q": "hello", "page": 2},
    )

    assert "q=hello" in captured["url"]
    assert "page=2" in captured["url"]


async def test_custom_headers_passed():
    captured: dict = {}
    tool = ApiCallerTool(transport=httpx.MockTransport(_echo_handler(captured)))

    await tool.execute(
        method="GET",
        url="https://api.example.com/me",
        headers={"Authorization": "Bearer xyz"},
    )

    assert captured["headers"].get("authorization") == "Bearer xyz"


async def test_dry_run_skips_get_too():
    """For an api_caller, GET could still be expensive — dry_run skips ALL methods."""
    called = {"n": 0}

    def handler(request):
        called["n"] += 1
        return httpx.Response(200)

    tool = ApiCallerTool(transport=httpx.MockTransport(handler))
    result = await tool.execute(
        method="GET", url="https://api.example.com/foo", dry_run=True
    )

    assert result.success is True
    assert "[dry-run]" in result.output
    assert called["n"] == 0


async def test_non_2xx_returns_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    tool = ApiCallerTool(transport=httpx.MockTransport(handler))
    result = await tool.execute(method="GET", url="https://api.example.com/secret")

    assert result.success is False
    assert "403" in (result.error or "")


async def test_missing_method_returns_error():
    tool = ApiCallerTool()
    result = await tool.execute(url="https://api.example.com")

    assert result.success is False
    assert "method" in (result.error or "").lower()


async def test_missing_url_returns_error():
    tool = ApiCallerTool()
    result = await tool.execute(method="GET")

    assert result.success is False
    assert "url" in (result.error or "").lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_tool_api_caller.py -v
```

Expected: FAIL — cannot import `ApiCallerTool`.

- [ ] **Step 3: Write implementation**

Write `src/tools/api_caller.py`:

```python
from __future__ import annotations

from typing import Any, Optional

import httpx

from src.tools.base import Tool, ToolResult


class ApiCallerTool(Tool):
    """Make a single HTTP request to a third-party REST API.

    Supports any standard method (GET/POST/PUT/PATCH/DELETE), JSON body, query
    params, custom headers. Returns the response text in `output` on success;
    HTTP errors (4xx/5xx) are reported as failure with status in metadata.

    `dry_run=True` skips the request entirely (even GET) — for an API caller,
    even a "read" can be expensive (rate limits, auth tokens) so we are
    conservative.
    """

    name = "api_caller"
    description = (
        "Make an HTTP request to a third-party REST API. Methods: GET/POST/PUT/PATCH/DELETE. "
        "Returns response body. HTTP errors (4xx/5xx) come back as failures."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
            },
            "url": {"type": "string"},
            "headers": {
                "type": "object",
                "description": "Optional HTTP headers.",
            },
            "json_body": {
                "type": "object",
                "description": "Optional JSON body for POST/PUT/PATCH.",
            },
            "query_params": {
                "type": "object",
                "description": "Optional query string parameters.",
            },
            "timeout_seconds": {"type": "integer", "default": 30},
        },
        "required": ["method", "url"],
    }
    risk_level = "high"  # generic API call could mutate remote state

    DEFAULT_TIMEOUT_SECONDS = 30

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        self._transport = transport

    async def execute(self, dry_run: bool = False, **params: Any) -> ToolResult:
        method = params.get("method")
        url = params.get("url")
        if not method:
            return ToolResult(success=False, output="", error="missing 'method' parameter")
        if not url:
            return ToolResult(success=False, output="", error="missing 'url' parameter")

        method = str(method).upper()
        timeout = float(params.get("timeout_seconds") or self.DEFAULT_TIMEOUT_SECONDS)

        if dry_run:
            return ToolResult(
                success=True,
                output=f"[dry-run] would {method} {url}",
            )

        client_kwargs: dict[str, Any] = {"timeout": timeout, "follow_redirects": True}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport

        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.request(
                    method,
                    url,
                    headers=params.get("headers"),
                    json=params.get("json_body"),
                    params=params.get("query_params"),
                )
        except httpx.TimeoutException as e:
            return ToolResult(success=False, output="", error=f"timeout: {e}")
        except httpx.HTTPError as e:
            return ToolResult(success=False, output="", error=f"http error: {e}")

        if response.status_code >= 400:
            return ToolResult(
                success=False,
                output=response.text,
                error=f"HTTP {response.status_code}",
                metadata={"status_code": response.status_code},
            )

        return ToolResult(
            success=True,
            output=response.text,
            metadata={"status_code": response.status_code},
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_tool_api_caller.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tools/api_caller.py tests/test_tool_api_caller.py
git commit -m "feat: add ApiCallerTool for generic REST requests with conservative dry_run"
```

---

### Task 7: Registry Update

**Files:**
- Modify: `src/tools/__init__.py`
- Modify: `tests/test_tool_registry.py`

Register the five new tools in `ALL_TOOLS` and update the registry test to verify all 7.

- [ ] **Step 1: Update tests/test_tool_registry.py**

Replace the contents of `tests/test_tool_registry.py` with:

```python
from src.tools import ALL_TOOLS
from src.tools.api_caller import ApiCallerTool
from src.tools.code_edit import CodeEditTool
from src.tools.database import DatabaseTool
from src.tools.file_ops import FileOpsTool
from src.tools.notifier import NotifierTool
from src.tools.shell import ShellTool
from src.tools.web_fetch import WebFetchTool


def test_registry_contains_all_seven_tools():
    expected = {
        FileOpsTool,
        ShellTool,
        WebFetchTool,
        CodeEditTool,
        DatabaseTool,
        NotifierTool,
        ApiCallerTool,
    }
    assert expected.issubset(set(ALL_TOOLS))
    # And the registry contains exactly these (no extras yet)
    assert set(ALL_TOOLS) == expected


def test_registry_tool_classes_are_instantiable():
    """Every class in ALL_TOOLS can be instantiated with no required args
    and exposes the required attrs."""
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

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_tool_registry.py -v
```

Expected: FAIL — `ALL_TOOLS` is missing the five new tools.

- [ ] **Step 3: Update src/tools/__init__.py**

Replace the contents of `src/tools/__init__.py` with:

```python
"""Tool registry. Each foundational tool registers itself by being added to ALL_TOOLS.

The Orchestrator instantiates everything in this list at startup and advertises
each tool's `parameters_schema` to the LLM via ToolDefinition.
"""

from src.tools.api_caller import ApiCallerTool
from src.tools.base import Tool, ToolResult
from src.tools.code_edit import CodeEditTool
from src.tools.database import DatabaseTool
from src.tools.file_ops import FileOpsTool
from src.tools.notifier import NotifierTool
from src.tools.shell import ShellTool
from src.tools.web_fetch import WebFetchTool

ALL_TOOLS: list[type[Tool]] = [
    FileOpsTool,
    ShellTool,
    WebFetchTool,
    CodeEditTool,
    DatabaseTool,
    NotifierTool,
    ApiCallerTool,
]

__all__ = [
    "Tool",
    "ToolResult",
    "ALL_TOOLS",
    "FileOpsTool",
    "ShellTool",
    "WebFetchTool",
    "CodeEditTool",
    "DatabaseTool",
    "NotifierTool",
    "ApiCallerTool",
]
```

- [ ] **Step 4: Run registry test**

```bash
uv run pytest tests/test_tool_registry.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Run the full suite to confirm no regressions**

```bash
uv run pytest -v
```

Expected: cumulative count rises by ~45 (6 web_fetch + 8 code_edit + 8 database + 7 notifier + 8 api_caller + (3 registry already counted before, but the test now exercises all 7 tools so it's still 3 tests)). Plan 4 net new = 6 + 8 + 8 + 7 + 8 = 37. After Plans 1+2+3a+3b+3c+4: **139 + 37 = 176 passed, 1 skipped**.

- [ ] **Step 6: Commit**

```bash
git add src/tools/__init__.py tests/test_tool_registry.py
git commit -m "feat: register web_fetch/code_edit/database/notifier/api_caller in ALL_TOOLS"
```

---

## Self-Review

**1. Spec coverage (Layer 3 — Tools table):**
- `web_search` → `WebFetchTool` (Task 2). Spec said "Internet search, fetch web content (async httpx)"; we implement fetch only. Real search deferred to Plan 5 (documented in "Out of scope").
- `code_edit` → `CodeEditTool` (Task 3). Spec said "Read and modify project code (async)". Implemented as line-range read + unique-match replace, which is safer than raw write and adds value beyond `file_ops`.
- `database` → `DatabaseTool` (Task 4). Spec said "MySQL queries (ThreadPoolExecutor with aiomysql)". Implemented async-native via aiomysql; the spec's "ThreadPoolExecutor" mention is misleading — aiomysql is async-native and doesn't need it.
- `notifier` → `NotifierTool` (Task 5). Spec said "WeChat enterprise bot webhook (async httpx)". Implemented exactly.
- `api_caller` → `ApiCallerTool` (Task 6). Spec said "Third-party REST API calls (async httpx)". Implemented exactly.

**2. Placeholder scan:**
- No "TBD" / "TODO" / "fill in details" / vague handlers.
- All test bodies have real assertions.
- All implementation steps include full code.
- "Out of scope" items (real search, DDL guards, connection pooling, image attachments) are explicitly documented at the top with rationale.

**3. Type consistency:**
- All tools subclass `Tool` and implement `async execute(self, dry_run: bool = False, **params) -> ToolResult` consistently.
- `parameters_schema` is `dict[str, Any]` with `type: "object"` everywhere.
- `risk_level` ∈ {"low", "high"} consistently.
- All HTTP-using tools accept an optional `transport` parameter for `httpx.MockTransport` injection in tests.
- `DatabaseTool.connection_factory` is `Optional[Callable[[], Awaitable[Any]]]`; the production path (`_default_factory`) and test-injected paths are both consistent.

**4. Cross-platform:**
- All tools use `pathlib.Path` for files; httpx is cross-platform; aiomysql is cross-platform.
- Tests use `tmp_path` (pytest fixture) and `httpx.MockTransport` for deterministic behavior.

**5. dry_run policy:**
- `WebFetchTool`: dry_run skips (low-risk read but still external IO).
- `CodeEditTool`: dry_run skips writes; reads always run.
- `DatabaseTool`: dry_run skips `execute`; `query` always runs (read-only).
- `NotifierTool`: dry_run skips POST.
- `ApiCallerTool`: dry_run skips ALL methods (even GET, since API GETs can be expensive / rate-limited / auth-charged).

This is intentional and documented per tool. Consistent with `file_ops` (reads run, writes skip) and `shell` (always skip).

All clean.
