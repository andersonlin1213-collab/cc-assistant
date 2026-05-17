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
