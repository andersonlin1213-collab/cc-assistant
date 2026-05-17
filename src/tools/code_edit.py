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
