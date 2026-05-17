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
