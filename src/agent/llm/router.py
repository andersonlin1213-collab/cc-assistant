"""Per-task LLM provider routing.

Bridges the gap left by `claude_cli` provider: the CLI subprocess runs its
own native tools and ignores cc-assistant's `ToolDefinition` list, so any
task that needs DatabaseTool / NotifierTool / ApiCallerTool / WebFetchTool
must reach the Anthropic SDK path (`ClaudeClient`) instead.

Routing precedence (top to bottom):
  1. Explicit `task.provider == "claude"`     → ClaudeClient (API)
  2. Explicit `task.provider == "claude_cli"` → ClaudeCLIClient (subprocess)
  3. Tag-based escalation: any tag in ESCALATE_TAGS  → ClaudeClient
  4. Config default (`config.llm_provider`)

When a route resolves to a client that isn't configured (e.g. user asked
for `provider: claude` but no ANTHROPIC_API_KEY in .env), the router
raises ProviderUnavailable. The orchestrator catches it, logs a structured
entry, and skips the cycle — silent fallback to the wrong provider would
just produce wrong results (e.g. running a mysql task on claude_cli where
DatabaseTool is missing).
"""
from __future__ import annotations

from typing import Iterable, Optional

from src.agent.llm.base import LLMClient
from src.models import Task

# Default escalate tags. The router consults its instance-level
# `escalate_tags` (configurable via `Config.escalate_tags`); this constant
# is just the fallback when no override is supplied.
_DEFAULT_ESCALATE_TAGS = frozenset({"db", "mysql", "wecom", "dingtalk", "api"})


class ProviderUnavailable(Exception):
    """Raised when the routing target is not a configured provider.

    Carries a human-readable reason so the orchestrator's log entry tells
    the user *why* the route failed (missing API key, claude CLI not on
    PATH, both providers absent, etc.).
    """


class LLMRouter:
    """Selects an LLMClient per task. Holds zero, one, or both providers."""

    # Class-level default kept for inspection / back-compat with tests that
    # imported `LLMRouter.ESCALATE_TAGS`. Per-instance lookup uses
    # `self.escalate_tags`, which `get_llm_router()` populates from
    # `Config.escalate_tags_set`.
    ESCALATE_TAGS = _DEFAULT_ESCALATE_TAGS

    def __init__(
        self,
        api_client: Optional[LLMClient],
        cli_client: Optional[LLMClient],
        default_provider: str,
        escalate_tags: Optional[Iterable[str]] = None,
    ) -> None:
        if api_client is None and cli_client is None:
            raise ValueError(
                "LLMRouter requires at least one configured provider "
                "(set ANTHROPIC_API_KEY for claude, or install `claude` CLI "
                "on PATH for claude_cli)"
            )
        self.api = api_client
        self.cli = cli_client
        self.default = default_provider.lower()
        self.escalate_tags: frozenset[str] = (
            frozenset(escalate_tags)
            if escalate_tags is not None
            else _DEFAULT_ESCALATE_TAGS
        )

    def select(self, task: Task) -> LLMClient:
        explicit = (task.provider or "").lower()
        if explicit == "claude":
            return self._require(self.api, "claude (explicit task.provider)")
        if explicit in ("claude_cli", "claude-cli"):
            return self._require(self.cli, "claude_cli (explicit task.provider)")
        if explicit:
            raise ProviderUnavailable(
                f"unknown task.provider {task.provider!r}; "
                "expected 'claude' or 'claude_cli'"
            )

        matched = set(task.tags) & self.escalate_tags
        if matched:
            return self._require(
                self.api,
                f"claude (tag-escalated: {sorted(matched)})",
            )

        if self.default == "claude":
            return self._require(self.api, "claude (config default)")
        return self._require(self.cli, "claude_cli (config default)")

    @staticmethod
    def _require(client: Optional[LLMClient], label: str) -> LLMClient:
        if client is None:
            raise ProviderUnavailable(f"provider not configured: {label}")
        return client


class _SingleClientRouter:
    """Adapter that lets Orchestrator accept a plain LLMClient for tests
    and one-off paths. select() always returns the same client; routing
    decisions are no-ops in this mode."""

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def select(self, task: Task) -> LLMClient:  # noqa: ARG002
        return self._client
