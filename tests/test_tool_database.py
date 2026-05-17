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
