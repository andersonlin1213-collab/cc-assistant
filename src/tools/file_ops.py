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
