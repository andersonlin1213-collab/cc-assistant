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

        if not api_messages:
            raise ValueError(
                "ClaudeClient.chat requires at least one non-system message"
            )

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
