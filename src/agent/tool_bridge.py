from __future__ import annotations

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
