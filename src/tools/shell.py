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
        "Execute a shell command. Returns stdout in 'output'; stderr in 'error' only "
        "when exit code != 0 (stderr from successful commands is discarded). "
        "Exit code in metadata.returncode."
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
                metadata={"returncode": None, "timed_out": True},
            )

        success = result.returncode == 0
        return ToolResult(
            success=success,
            output=result.stdout,
            error=result.stderr if not success else None,
            metadata={"returncode": result.returncode},
        )
