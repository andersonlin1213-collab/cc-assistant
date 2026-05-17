"""ClaudeClient unit tests using a mocked AsyncAnthropic.

These tests verify request shaping (system extraction, caching, tool conversion)
and response parsing without hitting the real Anthropic API. The real-API
smoke test lives in tests/test_llm_claude_real.py and is skipped without an
ANTHROPIC_API_KEY environment variable.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.llm.claude import ClaudeClient
from src.agent.llm.types import (
    Message,
    TextBlock,
    ToolDefinition,
    ToolUseBlock,
)


def _fake_response(content_blocks, stop_reason="end_turn", model="claude-sonnet-4-6"):
    """Build a minimal fake Anthropic response object for the SDK mock."""
    return SimpleNamespace(
        content=content_blocks,
        stop_reason=stop_reason,
        model=model,
        usage=SimpleNamespace(
            input_tokens=12,
            output_tokens=8,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        ),
    )


def _fake_text_block(text):
    return SimpleNamespace(type="text", text=text)


def _fake_tool_use_block(id_, name, input_):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


def _build_mock_anthropic(response):
    """Build a mock AsyncAnthropic whose `messages.create` returns the given response."""
    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=response)
    return mock_client


async def test_chat_extracts_system_message_and_caches():
    """A role=system Message becomes the API's top-level system param with cache_control."""
    fake = _fake_response([_fake_text_block("ack")])
    mock = _build_mock_anthropic(fake)
    client = ClaudeClient(api_key="x", client=mock)

    messages = [
        Message(role="system", content="You are an agent."),
        Message(role="user", content="Hello"),
    ]
    await client.chat(messages)

    call = mock.messages.create.call_args
    kwargs = call.kwargs

    # System message extracted out of message list
    assert "system" in kwargs
    assert isinstance(kwargs["system"], list)
    assert kwargs["system"][0]["type"] == "text"
    assert kwargs["system"][0]["text"] == "You are an agent."
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}

    # Only the user message survives in `messages`
    assert len(kwargs["messages"]) == 1
    assert kwargs["messages"][0]["role"] == "user"


async def test_chat_passes_tools_with_cache_on_last():
    """ToolDefinitions are converted to API shape; cache_control is on the last tool."""
    fake = _fake_response([_fake_text_block("ack")])
    mock = _build_mock_anthropic(fake)
    client = ClaudeClient(api_key="x", client=mock)

    tools = [
        ToolDefinition(name="t1", description="first", input_schema={"type": "object"}),
        ToolDefinition(name="t2", description="second", input_schema={"type": "object"}),
    ]
    await client.chat(
        messages=[Message(role="user", content="Hi")],
        tools=tools,
    )

    kwargs = mock.messages.create.call_args.kwargs
    assert "tools" in kwargs
    assert len(kwargs["tools"]) == 2
    assert kwargs["tools"][0]["name"] == "t1"
    assert "cache_control" not in kwargs["tools"][0]
    assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral"}


async def test_chat_parses_text_response():
    """A plain text response is parsed into a TextBlock."""
    fake = _fake_response([_fake_text_block("Hello there")])
    mock = _build_mock_anthropic(fake)
    client = ClaudeClient(api_key="x", client=mock)

    resp = await client.chat([Message(role="user", content="Hi")])

    assert resp.stop_reason == "end_turn"
    assert resp.model == "claude-sonnet-4-6"
    assert resp.usage.input_tokens == 12
    assert len(resp.content) == 1
    assert isinstance(resp.content[0], TextBlock)
    assert resp.content[0].text == "Hello there"


async def test_chat_parses_tool_use_response():
    """A tool_use response is parsed into a ToolUseBlock."""
    fake = _fake_response(
        [
            _fake_text_block("I will run a command."),
            _fake_tool_use_block("call_1", "shell", {"command": "pwd"}),
        ],
        stop_reason="tool_use",
    )
    mock = _build_mock_anthropic(fake)
    client = ClaudeClient(api_key="x", client=mock)

    resp = await client.chat(
        messages=[Message(role="user", content="Where am I?")],
        tools=[
            ToolDefinition(name="shell", description="run", input_schema={"type": "object"})
        ],
    )

    assert resp.stop_reason == "tool_use"
    assert len(resp.content) == 2
    assert isinstance(resp.content[0], TextBlock)
    assert isinstance(resp.content[1], ToolUseBlock)
    assert resp.content[1].name == "shell"
    assert resp.content[1].input == {"command": "pwd"}


async def test_chat_uses_default_model_when_not_overridden():
    fake = _fake_response([_fake_text_block("ok")])
    mock = _build_mock_anthropic(fake)
    client = ClaudeClient(api_key="x", client=mock)

    await client.chat([Message(role="user", content="Hi")])

    kwargs = mock.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-4-6"


async def test_chat_uses_overridden_model():
    fake = _fake_response([_fake_text_block("ok")], model="claude-opus-4-7")
    mock = _build_mock_anthropic(fake)
    client = ClaudeClient(api_key="x", model="claude-opus-4-7", client=mock)

    await client.chat([Message(role="user", content="Hi")])

    kwargs = mock.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-opus-4-7"


async def test_chat_max_tokens_is_passed():
    fake = _fake_response([_fake_text_block("ok")])
    mock = _build_mock_anthropic(fake)
    client = ClaudeClient(api_key="x", client=mock)

    await client.chat([Message(role="user", content="Hi")], max_tokens=2048)

    kwargs = mock.messages.create.call_args.kwargs
    assert kwargs["max_tokens"] == 2048


async def test_chat_raises_when_only_system_messages():
    """Calling chat with only system messages raises a clear error."""
    from unittest.mock import MagicMock
    mock = MagicMock()
    client = ClaudeClient(api_key="x", client=mock)

    with pytest.raises(ValueError, match="at least one non-system message"):
        await client.chat([Message(role="system", content="rules")])

    # SDK should NOT have been called
    mock.messages.create.assert_not_called()


async def test_chat_concatenates_multiple_system_messages():
    """Multiple role=system messages are concatenated with double newlines."""
    fake = _fake_response([_fake_text_block("ack")])
    mock = _build_mock_anthropic(fake)
    client = ClaudeClient(api_key="x", client=mock)

    await client.chat(
        [
            Message(role="system", content="Rule 1: be helpful."),
            Message(role="system", content="Rule 2: be terse."),
            Message(role="user", content="hi"),
        ]
    )

    kwargs = mock.messages.create.call_args.kwargs
    assert "system" in kwargs
    sys_text = kwargs["system"][0]["text"]
    assert "Rule 1: be helpful." in sys_text
    assert "Rule 2: be terse." in sys_text
    assert "\n\n" in sys_text  # concatenated with double newline


async def test_chat_omits_tools_key_when_tools_list_empty():
    """tools=[] should produce the same request shape as tools=None (no `tools` key)."""
    fake = _fake_response([_fake_text_block("ok")])
    mock = _build_mock_anthropic(fake)
    client = ClaudeClient(api_key="x", client=mock)

    await client.chat([Message(role="user", content="hi")], tools=[])

    kwargs = mock.messages.create.call_args.kwargs
    assert "tools" not in kwargs
