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
