from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
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
