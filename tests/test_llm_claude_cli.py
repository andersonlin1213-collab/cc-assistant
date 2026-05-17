"""Tests for ClaudeCLIClient — subprocess adapter to the local `claude` CLI."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.llm.claude_cli import ClaudeCLIClient
from src.agent.llm.types import LLMResponse, Message, TextBlock


# ---------------------------------------------------------------- #
# _render_messages                                                  #
# ---------------------------------------------------------------- #


def test_render_messages_labels_each_role():
    client = ClaudeCLIClient(bin_path="claude")
    out = client._render_messages([
        Message(role="system", content="be terse"),
        Message(role="user", content="hi"),
        Message(role="assistant", content="hello"),
        Message(role="user", content="bye"),
    ])
    assert "[SYSTEM]\nbe terse" in out
    assert "[USER]\nhi" in out
    assert "[ASSISTANT]\nhello" in out
    assert "[USER]\nbye" in out
    # System should appear once, before the conversation
    assert out.index("[SYSTEM]") < out.index("[USER]\nhi")


def test_render_messages_handles_block_content():
    """When a Message.content is a list of blocks, render their text."""
    client = ClaudeCLIClient(bin_path="claude")
    msg = Message(role="user", content=[TextBlock(text="block1"), TextBlock(text="block2")])
    out = client._render_messages([msg])
    assert "block1" in out and "block2" in out


# ---------------------------------------------------------------- #
# _parse_response                                                   #
# ---------------------------------------------------------------- #


def test_parse_response_extracts_result_and_usage():
    raw = json.dumps({
        "type": "result",
        "result": "pong",
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": 6,
            "output_tokens": 6,
            "cache_creation_input_tokens": 11906,
            "cache_read_input_tokens": 15218,
        },
        "modelUsage": {"claude-opus-4-7[1m]": {}},
    })
    client = ClaudeCLIClient(bin_path="claude")
    resp = client._parse_response(raw)

    assert isinstance(resp, LLMResponse)
    assert len(resp.content) == 1
    assert resp.content[0].type == "text"
    assert resp.content[0].text == "pong"
    assert resp.stop_reason == "end_turn"
    assert resp.usage.input_tokens == 6
    assert resp.usage.output_tokens == 6
    assert resp.usage.cache_creation_input_tokens == 11906
    assert resp.usage.cache_read_input_tokens == 15218
    assert "opus" in resp.model.lower() or resp.model  # not empty


def test_parse_response_falls_back_to_plain_text_when_not_json():
    """If the CLI prints non-JSON (older format, error spew), wrap as text."""
    client = ClaudeCLIClient(bin_path="claude")
    resp = client._parse_response("just a string\n")
    assert resp.content[0].text == "just a string\n"
    assert resp.stop_reason == "end_turn"


def test_parse_response_handles_missing_usage():
    raw = json.dumps({"result": "ok", "stop_reason": "end_turn"})
    client = ClaudeCLIClient(bin_path="claude")
    resp = client._parse_response(raw)
    assert resp.content[0].text == "ok"
    assert resp.usage.input_tokens == 0
    assert resp.usage.output_tokens == 0


# ---------------------------------------------------------------- #
# chat — subprocess invocation                                      #
# ---------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_chat_invokes_subprocess_with_prompt_via_stdin():
    client = ClaudeCLIClient(bin_path="claude")

    fake_proc = MagicMock()
    fake_proc.communicate = AsyncMock(
        return_value=(b'{"result":"pong","stop_reason":"end_turn"}', b"")
    )
    fake_proc.returncode = 0

    with patch(
        "src.agent.llm.claude_cli.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake_proc),
    ) as mock_exec:
        resp = await client.chat(messages=[Message(role="user", content="hi")])

    # Subprocess was called with the right command shape — empty -p so the
    # prompt comes via stdin (avoids Windows .CMD shim quoting issues).
    args, kwargs = mock_exec.call_args
    assert args[0] == "claude"
    p_idx = args.index("-p")
    assert args[p_idx + 1] == ""
    assert "--output-format" in args
    assert args[args.index("--output-format") + 1] == "json"
    assert kwargs.get("stdin") is not None

    # The rendered prompt was piped through communicate(input=...).
    fake_proc.communicate.assert_awaited_once()
    sent = fake_proc.communicate.await_args.kwargs.get("input")
    assert sent is not None
    assert b"[USER]\nhi" in sent

    assert resp.content[0].text == "pong"


@pytest.mark.asyncio
async def test_chat_raises_on_nonzero_exit():
    client = ClaudeCLIClient(bin_path="claude")

    fake_proc = MagicMock()
    fake_proc.communicate = AsyncMock(return_value=(b"", b"command not found"))
    fake_proc.returncode = 127

    with patch(
        "src.agent.llm.claude_cli.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake_proc),
    ):
        with pytest.raises(RuntimeError, match="claude CLI exited 127"):
            await client.chat(messages=[Message(role="user", content="hi")])


@pytest.mark.asyncio
async def test_chat_ignores_tools_param_silently():
    """tools= is accepted (interface compat) but the CLI runs its own tools."""
    from src.agent.llm.types import ToolDefinition

    client = ClaudeCLIClient(bin_path="claude")
    fake_proc = MagicMock()
    fake_proc.communicate = AsyncMock(
        return_value=(b'{"result":"ok","stop_reason":"end_turn"}', b"")
    )
    fake_proc.returncode = 0

    with patch(
        "src.agent.llm.claude_cli.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake_proc),
    ):
        # Should not raise — tools are accepted but ignored.
        resp = await client.chat(
            messages=[Message(role="user", content="hi")],
            tools=[ToolDefinition(name="dummy", description="x", input_schema={})],
        )
    assert resp.content[0].text == "ok"


@pytest.mark.asyncio
async def test_chat_requires_at_least_one_message():
    client = ClaudeCLIClient(bin_path="claude")
    with pytest.raises(ValueError, match="at least one"):
        await client.chat(messages=[])


@pytest.mark.asyncio
async def test_chat_strips_anthropic_api_key_from_subprocess_env(monkeypatch):
    """Regression: ANTHROPIC_API_KEY in cc-assistant's env (loaded from .env
    for the SDK-based ClaudeClient) must NOT leak into the claude CLI
    subprocess. The CLI would then treat it as an external API key and fail
    with 401 when the value is a placeholder, instead of using the user's
    `claude login` session.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-from-dotenv")
    monkeypatch.setenv("CLAUDE_API_KEY", "another-dummy")
    monkeypatch.setenv("UNRELATED_VAR", "keep-me")

    client = ClaudeCLIClient(bin_path="claude")
    fake_proc = MagicMock()
    fake_proc.communicate = AsyncMock(
        return_value=(b'{"result":"ok","stop_reason":"end_turn"}', b"")
    )
    fake_proc.returncode = 0

    with patch(
        "src.agent.llm.claude_cli.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake_proc),
    ) as mock_exec:
        await client.chat(messages=[Message(role="user", content="hi")])

    env = mock_exec.call_args.kwargs.get("env")
    assert env is not None, "subprocess must be invoked with explicit env="
    assert "ANTHROPIC_API_KEY" not in env
    assert "CLAUDE_API_KEY" not in env
    assert env.get("UNRELATED_VAR") == "keep-me"


# ------------------------------------------------------------------ #
# Pre-flight proxy probe + cleaned non-zero exit handling             #
# ------------------------------------------------------------------ #


def test_proxy_alive_returns_true_and_none_when_no_proxy_configured():
    """No HTTP_PROXY/HTTPS_PROXY in env → no probe → (True, None). Lets
    non-proxy users skip the check entirely with no overhead."""
    from src.agent.llm.claude_cli import _proxy_alive
    alive, addr = _proxy_alive({})
    assert alive is True
    assert addr is None


def test_proxy_alive_returns_false_when_proxy_unreachable():
    """A proxy URL pointing at a closed port returns (False, host:port).
    Use a high port unlikely to be in use on the test runner."""
    from src.agent.llm.claude_cli import _proxy_alive
    alive, addr = _proxy_alive(
        {"HTTP_PROXY": "http://127.0.0.1:1"},
        timeout=0.5,
    )
    assert alive is False
    assert addr == "127.0.0.1:1"


def test_proxy_alive_handles_malformed_url_gracefully():
    """Garbage in `HTTP_PROXY` shouldn't make the probe block startup —
    return (True, None) and let the CLI surface whatever real failure
    follows. Pre-flight is best-effort, not a strict gate."""
    from src.agent.llm.claude_cli import _proxy_alive
    alive, addr = _proxy_alive({"HTTP_PROXY": "garbage:::not-a-url"})
    assert alive is True
    assert addr is None


@pytest.mark.asyncio
async def test_chat_raises_provider_unavailable_when_proxy_down(monkeypatch):
    """Pre-flight catches a dead proxy → ProviderUnavailable raised before
    spawning the subprocess. Avoids the 3-min hang we hit on 5/6 when
    v2rayN was down for 12 hours."""
    from src.agent.llm.router import ProviderUnavailable
    # Clear any real HTTPS_PROXY that the dev machine has set; _proxy_alive
    # prefers HTTPS_PROXY over HTTP_PROXY, so a live one would shadow our
    # dead-port test value.
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")

    client = ClaudeCLIClient(bin_path="claude")
    fake_proc = MagicMock()
    fake_proc.communicate = AsyncMock(return_value=(b"", b""))
    fake_proc.returncode = 0
    mock_exec = AsyncMock(return_value=fake_proc)

    with patch(
        "src.agent.llm.claude_cli.asyncio.create_subprocess_exec",
        new=mock_exec,
    ):
        with pytest.raises(ProviderUnavailable, match="代理不可达"):
            await client.chat(messages=[Message(role="user", content="hi")])

    # Subprocess must NOT have been spawned — pre-flight short-circuits.
    mock_exec.assert_not_called()


@pytest.mark.asyncio
async def test_chat_extracts_clean_message_from_cli_json_error(monkeypatch):
    """Non-zero exit with parseable JSON envelope → extract `result` field
    and emit a one-line message. Replaces the old behavior of dumping the
    full envelope (~1KB of tokens / session_ids / iterations) into the
    conversation as an [Error] AI reply."""
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)

    cli_envelope = {
        "type": "result",
        "is_error": True,
        "api_error_status": 500,
        "duration_ms": 1234,
        "result": "API Error: internal server error",
        "session_id": "irrelevant-noise",
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }
    client = ClaudeCLIClient(bin_path="claude")
    fake_proc = MagicMock()
    fake_proc.communicate = AsyncMock(
        return_value=(json.dumps(cli_envelope).encode(), b"")
    )
    fake_proc.returncode = 1

    with patch(
        "src.agent.llm.claude_cli.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake_proc),
    ):
        with pytest.raises(RuntimeError) as exc:
            await client.chat(messages=[Message(role="user", content="hi")])

    msg = str(exc.value)
    # Extracted human-readable result, not the JSON dump.
    assert "API Error: internal server error" in msg
    assert "HTTP 500" in msg
    assert "1234ms" in msg
    # Noise fields are NOT in the message.
    assert "session_id" not in msg
    assert "input_tokens" not in msg


@pytest.mark.asyncio
async def test_chat_routes_connection_refused_to_provider_unavailable(monkeypatch):
    """If the CLI's `result` field mentions a connection-class error, the
    failure is treated as transient/network — route through
    ProviderUnavailable (→ [系统] notice in Obsidian) instead of an
    [Error] AI reply. Real-world: 5/6 23:22 v2rayN-down dump landed as a
    1KB JSON wall in the user's task file."""
    from src.agent.llm.router import ProviderUnavailable
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)

    cli_envelope = {
        "type": "result",
        "is_error": True,
        "api_error_status": None,
        "duration_ms": 180021,
        "result": "API Error: Unable to connect to API (ConnectionRefused)",
    }
    client = ClaudeCLIClient(bin_path="claude")
    fake_proc = MagicMock()
    fake_proc.communicate = AsyncMock(
        return_value=(json.dumps(cli_envelope).encode(), b"")
    )
    fake_proc.returncode = 1

    with patch(
        "src.agent.llm.claude_cli.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake_proc),
    ):
        with pytest.raises(ProviderUnavailable, match="ConnectionRefused"):
            await client.chat(messages=[Message(role="user", content="hi")])
