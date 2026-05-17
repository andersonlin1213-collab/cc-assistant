# Plan 3a: LLM Client Layer (Claude MVP)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pluggable async LLM client abstraction with one concrete implementation: `ClaudeClient` over the Anthropic SDK. Includes typed message/content/tool/response models, prompt caching for the system prompt and tool definitions, and a factory that switches providers via `config.llm_provider`.

**Architecture:** `LLMClient` ABC defines the async `chat()` contract. `ClaudeClient` implements it over `anthropic.AsyncAnthropic`, translating between our typed Pydantic models and the Anthropic API's dict shapes. The system message is extracted from the message list and emitted as the API's top-level `system` parameter with `cache_control: ephemeral`. Tool definitions get cache_control on the last entry. Tests use a mocked `AsyncAnthropic` to verify request shape and response parsing without hitting the real API. An optional integration test (skipped without `ANTHROPIC_API_KEY`) does one real round-trip.

**Tech Stack:** Python 3.11+, `anthropic` SDK (>=0.40), pydantic v2 (already installed), `pytest-asyncio` (already installed). Default model: `claude-sonnet-4-6`.

**Out of scope (deferred):** OpenAI client, Ollama client, streaming, vision/files, batch API. These come in a future plan once the Orchestrator (Plan 3c) is shipped and the abstraction is exercised.

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Modify | `pyproject.toml` | Add `anthropic>=0.40` |
| Create | `src/agent/__init__.py` | Agent package marker |
| Create | `src/agent/llm/__init__.py` | LLM package marker |
| Create | `src/agent/llm/types.py` | Pydantic models: `TextBlock`, `ToolUseBlock`, `ToolResultBlock`, `Message`, `ToolDefinition`, `Usage`, `LLMResponse` |
| Create | `src/agent/llm/base.py` | `LLMClient` ABC with single `chat()` method |
| Create | `src/agent/llm/claude.py` | `ClaudeClient` — anthropic SDK adapter with prompt caching |
| Create | `src/agent/llm/factory.py` | `get_llm_client()` factory keyed off `config.llm_provider` |
| Create | `tests/test_llm_types.py` | Type model tests (discriminated union round-trip) |
| Create | `tests/test_llm_claude.py` | ClaudeClient unit tests with mocked `AsyncAnthropic` |
| Create | `tests/test_llm_factory.py` | Factory provider switching test |
| Create | `tests/test_llm_claude_real.py` | Optional real-API smoke test, skipped without env var |

---

### Task 1: Dependencies and Package Init

**Files:**
- Modify: `pyproject.toml` (via `uv add`)
- Create: `src/agent/__init__.py`
- Create: `src/agent/llm/__init__.py`

- [ ] **Step 1: Add anthropic dependency**

```bash
cd /c/<your-user>/projects/cc-assitant
uv add "anthropic>=0.40"
```

- [ ] **Step 2: Create package directories**

```bash
mkdir -p src/agent/llm
touch src/agent/__init__.py
touch src/agent/llm/__init__.py
```

- [ ] **Step 3: Verify**

```bash
uv run python -c "import anthropic; print(anthropic.__version__)"
```

Expected: a version string (e.g., `0.40.0` or higher).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock src/agent/__init__.py src/agent/llm/__init__.py
git commit -m "chore: add anthropic SDK and create agent.llm package"
```

---

### Task 2: LLM Type Models

**Files:**
- Create: `src/agent/llm/types.py`
- Create: `tests/test_llm_types.py`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_llm_types.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_llm_types.py -v
```

Expected: FAIL — cannot import from `src.agent.llm.types`.

- [ ] **Step 3: Write implementation**

Write `src/agent/llm/types.py`:

```python
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ToolUseBlock(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict


class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False


ContentBlock = Annotated[
    Union[TextBlock, ToolUseBlock, ToolResultBlock],
    Field(discriminator="type"),
]


class Message(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: Union[str, list[ContentBlock]]


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


class LLMResponse(BaseModel):
    content: list[ContentBlock]
    stop_reason: str  # "end_turn" | "tool_use" | "max_tokens" | "stop_sequence"
    usage: Usage
    model: str
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_llm_types.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/agent/llm/types.py tests/test_llm_types.py
git commit -m "feat: add typed pydantic models for LLM messages, tool calls, and responses"
```

---

### Task 3: LLMClient ABC

**Files:**
- Create: `src/agent/llm/base.py`

This is a small file with no behavior to test in isolation — it's an abstract base class. Tests will exercise it via the concrete `ClaudeClient` in Task 4.

- [ ] **Step 1: Write implementation**

Write `src/agent/llm/base.py`:

```python
from __future__ import annotations

from abc import ABC, abstractmethod

from src.agent.llm.types import LLMResponse, Message, ToolDefinition


class LLMClient(ABC):
    """Abstract async LLM client.

    Implementations adapt our typed Message/ToolDefinition/LLMResponse models
    to a specific provider's API. The single `chat()` method covers both
    plain conversation and tool-use; pass `tools=None` for plain chat.
    """

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Send messages and optional tool definitions; receive a typed response.

        Implementations should:
          - Extract any `role="system"` message and pass it to the provider's
            system-prompt mechanism (Anthropic's top-level `system=` parameter).
          - Apply prompt caching to stable inputs (system prompt, tool definitions)
            to reduce token costs across the Orchestrator's repeated cycles.
          - Translate provider response shapes back to typed `LLMResponse`.
        """
```

- [ ] **Step 2: Verify import works**

```bash
uv run python -c "from src.agent.llm.base import LLMClient; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/agent/llm/base.py
git commit -m "feat: add LLMClient ABC defining the async chat contract"
```

---

### Task 4: ClaudeClient

**Files:**
- Create: `src/agent/llm/claude.py`
- Create: `tests/test_llm_claude.py`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_llm_claude.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_llm_claude.py -v
```

Expected: FAIL — cannot import `ClaudeClient`.

- [ ] **Step 3: Write implementation**

Write `src/agent/llm/claude.py`:

```python
from __future__ import annotations

from typing import Any

import anthropic

from src.agent.llm.base import LLMClient
from src.agent.llm.types import (
    LLMResponse,
    Message,
    TextBlock,
    ToolDefinition,
    ToolUseBlock,
    Usage,
)


class ClaudeClient(LLMClient):
    """Anthropic SDK adapter implementing the LLMClient contract.

    Applies prompt caching to:
      - the system prompt (one cache block)
      - the last tool definition (caches the entire tools array up to that point)

    These two stable inputs (rules.md + tool list) are reconstructed identically
    every cycle by the Orchestrator's Completion Promise Pattern, so caching them
    produces a high cache-hit rate across cycles.
    """

    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        client: anthropic.AsyncAnthropic | Any = None,
    ) -> None:
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        self._client = client or anthropic.AsyncAnthropic(api_key=api_key)

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        system_text, api_messages = self._partition_system(messages)

        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": api_messages,
        }

        if system_text is not None:
            # System prompt as a list of text blocks, with cache_control on the last.
            # Even with one block, this is the canonical caching shape.
            request["system"] = [
                {
                    "type": "text",
                    "text": system_text,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        if tools:
            api_tools = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in tools
            ]
            # Caching: cache_control on the last tool caches the tools array prefix
            api_tools[-1]["cache_control"] = {"type": "ephemeral"}
            request["tools"] = api_tools

        response = await self._client.messages.create(**request)
        return self._parse_response(response)

    @staticmethod
    def _partition_system(
        messages: list[Message],
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Pull out role=system messages; return (system_text, api_messages)."""
        system_text: str | None = None
        api_messages: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                # Concatenate multiple system messages with double newlines.
                text = m.content if isinstance(m.content, str) else _blocks_text(m.content)
                system_text = text if system_text is None else f"{system_text}\n\n{text}"
            else:
                if isinstance(m.content, str):
                    api_messages.append({"role": m.role, "content": m.content})
                else:
                    api_messages.append(
                        {
                            "role": m.role,
                            "content": [b.model_dump() for b in m.content],
                        }
                    )
        return system_text, api_messages

    @staticmethod
    def _parse_response(response: Any) -> LLMResponse:
        content_blocks: list[TextBlock | ToolUseBlock] = []
        for block in response.content:
            if block.type == "text":
                content_blocks.append(TextBlock(text=block.text))
            elif block.type == "tool_use":
                content_blocks.append(
                    ToolUseBlock(id=block.id, name=block.name, input=block.input)
                )
            # Ignore unknown block types (e.g., thinking blocks if extended thinking
            # is enabled; not supported in this MVP).

        usage = Usage(
            input_tokens=getattr(response.usage, "input_tokens", 0),
            output_tokens=getattr(response.usage, "output_tokens", 0),
            cache_creation_input_tokens=getattr(
                response.usage, "cache_creation_input_tokens", 0
            ),
            cache_read_input_tokens=getattr(
                response.usage, "cache_read_input_tokens", 0
            ),
        )

        return LLMResponse(
            content=content_blocks,
            stop_reason=response.stop_reason,
            usage=usage,
            model=response.model,
        )


def _blocks_text(blocks: list) -> str:
    """Concatenate text blocks; ignore non-text content. Used for system prompt extraction."""
    parts = []
    for b in blocks:
        if isinstance(b, TextBlock):
            parts.append(b.text)
    return "\n".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_llm_claude.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/agent/llm/claude.py tests/test_llm_claude.py
git commit -m "feat: add ClaudeClient with prompt caching for system prompt and tools"
```

---

### Task 5: Provider Factory

**Files:**
- Create: `src/agent/llm/factory.py`
- Create: `tests/test_llm_factory.py`

The factory reads `config.llm_provider` and returns a configured client. For now, only `"claude"` is supported; OpenAI and Ollama raise `NotImplementedError` so adding them later is a single-file change.

- [ ] **Step 1: Write the failing tests**

Write `tests/test_llm_factory.py`:

```python
import os

import pytest

from src.agent.llm.claude import ClaudeClient
from src.agent.llm.factory import get_llm_client


def test_factory_returns_claude_for_provider_claude(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    import importlib
    import src.config

    importlib.reload(src.config)

    client = get_llm_client()
    assert isinstance(client, ClaudeClient)
    assert client.api_key == "test-key"


def test_factory_raises_on_missing_anthropic_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Also clear via setenv to empty string (some loaders pick up empty defaults)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    import importlib
    import src.config

    importlib.reload(src.config)

    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        get_llm_client()


def test_factory_raises_not_implemented_for_openai(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")

    import importlib
    import src.config

    importlib.reload(src.config)

    with pytest.raises(NotImplementedError, match="openai"):
        get_llm_client()


def test_factory_raises_not_implemented_for_ollama(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")

    import importlib
    import src.config

    importlib.reload(src.config)

    with pytest.raises(NotImplementedError, match="ollama"):
        get_llm_client()


def test_factory_raises_on_unknown_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "nonexistent")

    import importlib
    import src.config

    importlib.reload(src.config)

    with pytest.raises(ValueError, match="unknown"):
        get_llm_client()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_llm_factory.py -v
```

Expected: FAIL — cannot import `get_llm_client`.

- [ ] **Step 3: Write implementation**

Write `src/agent/llm/factory.py`:

```python
from __future__ import annotations

from src.agent.llm.base import LLMClient
from src.agent.llm.claude import ClaudeClient
from src.config import config


def get_llm_client() -> LLMClient:
    """Construct an LLMClient based on `config.llm_provider`.

    Reads from the global `config` (pydantic-settings, populated from .env).
    Raises ValueError on missing required credentials or unknown provider.
    Raises NotImplementedError for providers known to the spec but not yet built.
    """
    provider = config.llm_provider.lower()

    if provider == "claude":
        if not config.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=claude")
        return ClaudeClient(api_key=config.anthropic_api_key)

    if provider == "openai":
        raise NotImplementedError(
            "openai provider is not implemented yet (see Plan 5 — Multi-LLM)"
        )

    if provider == "ollama":
        raise NotImplementedError(
            "ollama provider is not implemented yet (see Plan 5 — Multi-LLM)"
        )

    raise ValueError(f"unknown LLM_PROVIDER: {provider!r}")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_llm_factory.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/agent/llm/factory.py tests/test_llm_factory.py
git commit -m "feat: add LLM client factory keyed off config.llm_provider"
```

---

### Task 6: Optional Real-API Smoke Test

**Files:**
- Create: `tests/test_llm_claude_real.py`

This test is skipped automatically when `ANTHROPIC_API_KEY` is not set. It does ONE small round-trip (≤ 100 input tokens, max_tokens=64) so cost is negligible. It verifies the SDK integration works end-to-end against the real API.

- [ ] **Step 1: Write the test**

Write `tests/test_llm_claude_real.py`:

```python
"""Real Anthropic API smoke test.

Skipped automatically when ANTHROPIC_API_KEY is not set. To run locally:
  ANTHROPIC_API_KEY=sk-... uv run pytest tests/test_llm_claude_real.py -v

Cost: a single short round-trip (≤ 100 input tokens, ≤ 64 output tokens).
"""

import os

import pytest

from src.agent.llm.claude import ClaudeClient
from src.agent.llm.types import Message, TextBlock


pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)


async def test_real_api_round_trip():
    client = ClaudeClient(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = await client.chat(
        messages=[
            Message(role="system", content="Reply with exactly one word."),
            Message(role="user", content="Say 'pong'."),
        ],
        max_tokens=64,
    )
    assert resp.stop_reason in ("end_turn", "stop_sequence")
    assert len(resp.content) >= 1
    text = " ".join(b.text for b in resp.content if isinstance(b, TextBlock))
    assert "pong" in text.lower()
    # Caching should produce non-zero values on the second call, but for a single
    # round-trip we just verify the field exists and is non-negative.
    assert resp.usage.input_tokens > 0
    assert resp.usage.output_tokens > 0
```

- [ ] **Step 2: Run the test (will skip without API key)**

```bash
uv run pytest tests/test_llm_claude_real.py -v
```

Expected without `ANTHROPIC_API_KEY`: 1 skipped.
Expected with `ANTHROPIC_API_KEY` set: 1 passed.

- [ ] **Step 3: Run the full suite to confirm no regressions**

```bash
uv run pytest -v
```

Expected: all previous tests still pass + the new ones from Plan 3a. Total: 63 (Plan 1+2) + 8 (types) + 7 (claude) + 5 (factory) + 1 skipped = **84 collected, 83 passed, 1 skipped** (or 84 passed if API key is set).

- [ ] **Step 4: Commit**

```bash
git add tests/test_llm_claude_real.py
git commit -m "test: add optional real Anthropic API smoke test (skipped without API key)"
```

---

## Self-Review

**1. Spec coverage (Layer 3 — LLM Client portion):**
- `LLMClient` ABC with `chat()` and `chat_with_tools()` methods: Implemented as a single `chat(messages, tools=None, max_tokens=...)`. The combined signature is functionally equivalent — `tools=None` is plain chat, `tools=[...]` is tool-use. Cleaner than splitting into two methods. The spec's separate `chat_with_tools` was illustrative; merging is a minor design improvement.
- Pluggable via `LLM_PROVIDER`: Task 5 factory.
- ClaudeClient (Anthropic API): Task 4.
- OpenAIClient, OllamaClient: explicitly deferred to Plan 5; factory raises `NotImplementedError` so the dispatch path is clear.
- Prompt caching: applied to system prompt and tool definitions in `ClaudeClient` (Task 4).

**2. Placeholder scan:**
- No "TBD" / "TODO" / "fill in details".
- All test bodies have real assertions.
- All implementation steps include full code.

**3. Type consistency:**
- `Message.role` is `Literal["user", "assistant", "system"]` consistently in types, claude.py, and tests.
- `TextBlock`, `ToolUseBlock`, `ToolResultBlock` discriminated by `type` field; round-trips via `model_dump`/`model_validate`.
- `Usage` field names match Anthropic SDK's response usage fields exactly: `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`.
- `LLMResponse.stop_reason` is `str` (not enum) since Anthropic adds new reasons periodically; using a string keeps us forward-compatible.

**4. Async test mode:**
- `pyproject.toml` already sets `asyncio_mode = "auto"`, so `async def test_*` is auto-detected. No `@pytest.mark.asyncio` needed.

All clean. Ready for Plan 3c (Orchestrator) once Plan 3b ships.
