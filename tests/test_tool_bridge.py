from src.agent.cycle_state import CycleState
from src.agent.llm.types import ToolUseBlock
from src.agent.tool_bridge import ToolBridge
from src.tools.base import Tool, ToolResult


class FakeTool(Tool):
    name = "fake"
    description = "A fake tool"
    parameters_schema = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
    }
    risk_level = "low"

    async def execute(self, dry_run: bool = False, **params) -> ToolResult:
        return ToolResult(success=True, output=f"echo:{params['x']}")


def test_tool_definitions_include_regular_and_control():
    """ToolBridge advertises regular tools + control tools to the LLM."""
    bridge = ToolBridge(tools=[FakeTool()])
    defs = bridge.tool_definitions()

    names = {d.name for d in defs}
    assert "fake" in names
    assert "mark_complete" in names
    assert "mark_blocked" in names
    assert len(defs) == 3


async def test_dispatch_regular_tool_returns_tool_result():
    bridge = ToolBridge(tools=[FakeTool()])
    state = CycleState()

    tu = ToolUseBlock(id="call_1", name="fake", input={"x": "hi"})
    result = await bridge.dispatch(tu, state)

    assert result.success is True
    assert result.output == "echo:hi"
    # State unchanged for regular tools
    assert state.marked_complete is False
    assert state.marked_blocked is False


async def test_dispatch_mark_complete_sets_state():
    bridge = ToolBridge(tools=[FakeTool()])
    state = CycleState()

    tu = ToolUseBlock(id="call_2", name="mark_complete", input={"reason": "all done"})
    result = await bridge.dispatch(tu, state)

    assert result.success is True
    assert state.marked_complete is True
    assert state.complete_reason == "all done"


async def test_dispatch_mark_blocked_sets_state():
    bridge = ToolBridge(tools=[FakeTool()])
    state = CycleState()

    tu = ToolUseBlock(id="call_3", name="mark_blocked", input={"reason": "need approval"})
    result = await bridge.dispatch(tu, state)

    assert result.success is True
    assert state.marked_blocked is True
    assert state.blocked_reason == "need approval"


async def test_dispatch_unknown_tool_returns_error():
    bridge = ToolBridge(tools=[FakeTool()])
    state = CycleState()

    tu = ToolUseBlock(id="call_4", name="nonexistent", input={})
    result = await bridge.dispatch(tu, state)

    assert result.success is False
    assert result.error is not None
    assert "unknown tool" in result.error.lower()


async def test_dispatch_passes_dry_run():
    """Regular tool dispatch forwards the dry_run flag."""
    captured = {}

    class CaptureTool(Tool):
        name = "capture"
        description = "capture dry_run"
        parameters_schema = {"type": "object"}
        risk_level = "low"

        async def execute(self, dry_run: bool = False, **params) -> ToolResult:
            captured["dry_run"] = dry_run
            return ToolResult(success=True, output="captured")

    bridge = ToolBridge(tools=[CaptureTool()])
    state = CycleState()

    tu = ToolUseBlock(id="c", name="capture", input={})
    await bridge.dispatch(tu, state, dry_run=True)

    assert captured["dry_run"] is True
