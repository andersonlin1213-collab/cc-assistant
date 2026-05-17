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
