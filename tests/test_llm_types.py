import pytest

from src.agent.llm.types import (
    LLMResponse,
    Message,
    TextBlock,
    ToolDefinition,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)


def test_text_block_has_type_discriminator():
    block = TextBlock(text="hello")
    assert block.type == "text"
    assert block.model_dump() == {"type": "text", "text": "hello"}


def test_tool_use_block():
    block = ToolUseBlock(id="abc", name="shell", input={"command": "ls"})
    assert block.type == "tool_use"
    d = block.model_dump()
    assert d["type"] == "tool_use"
    assert d["id"] == "abc"
    assert d["name"] == "shell"
    assert d["input"] == {"command": "ls"}


def test_tool_result_block():
    block = ToolResultBlock(tool_use_id="abc", content="ok")
    assert block.type == "tool_result"
    assert block.is_error is False


def test_message_with_string_content():
    m = Message(role="user", content="hello")
    assert m.role == "user"
    assert m.content == "hello"


def test_message_with_block_content_round_trip():
    """A message with mixed content blocks round-trips through model_dump/model_validate."""
    m = Message(
        role="assistant",
        content=[
            TextBlock(text="I will use a tool."),
            ToolUseBlock(id="t1", name="shell", input={"command": "pwd"}),
        ],
    )
    d = m.model_dump()
    assert d["role"] == "assistant"
    assert len(d["content"]) == 2
    assert d["content"][0]["type"] == "text"
    assert d["content"][1]["type"] == "tool_use"

    restored = Message.model_validate(d)
    assert restored.content[0].text == "I will use a tool."
    assert restored.content[1].name == "shell"


def test_tool_definition():
    td = ToolDefinition(
        name="shell",
        description="Run a shell command",
        input_schema={"type": "object", "properties": {"command": {"type": "string"}}},
    )
    assert td.name == "shell"
    assert td.input_schema["type"] == "object"


def test_llm_response():
    resp = LLMResponse(
        content=[TextBlock(text="hi")],
        stop_reason="end_turn",
        usage=Usage(input_tokens=10, output_tokens=5),
        model="claude-sonnet-4-6",
    )
    assert resp.stop_reason == "end_turn"
    assert resp.usage.input_tokens == 10
    assert resp.usage.cache_read_input_tokens == 0  # default


def test_usage_includes_cache_fields():
    u = Usage(
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=200,
        cache_read_input_tokens=300,
    )
    assert u.cache_creation_input_tokens == 200
    assert u.cache_read_input_tokens == 300


def test_response_block_excludes_tool_result():
    """LLMResponse.content uses ResponseBlock which excludes ToolResultBlock."""
    from pydantic import ValidationError
    from src.agent.llm.types import ResponseBlock  # noqa: F401

    # A valid response with text + tool_use should validate
    resp = LLMResponse(
        content=[TextBlock(text="hi"), ToolUseBlock(id="t1", name="x", input={})],
        stop_reason="tool_use",
        usage=Usage(),
        model="claude-sonnet-4-6",
    )
    assert len(resp.content) == 2

    # A tool_result block should NOT validate as a response content block
    with pytest.raises(ValidationError):
        LLMResponse.model_validate(
            {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "x",
                        "content": "data",
                        "is_error": False,
                    }
                ],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 0, "output_tokens": 0,
                          "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
                "model": "claude-sonnet-4-6",
            }
        )
