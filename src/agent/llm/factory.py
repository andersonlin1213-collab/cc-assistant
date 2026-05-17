from __future__ import annotations

import shutil

import src.config as _config_module

from src.agent.llm.base import LLMClient
from src.agent.llm.claude import ClaudeClient
from src.agent.llm.claude_cli import ClaudeCLIClient
from src.agent.llm.router import LLMRouter


def get_llm_router() -> LLMRouter:
    """Build an LLMRouter populated with whichever providers have reachable
    credentials/binaries. The Orchestrator dispatches per-task via the
    router's `select()` so claude_cli and claude (API) can coexist.

    Bring-up rules:
      - `ClaudeClient` is added when ANTHROPIC_API_KEY is set.
      - `ClaudeCLIClient` is added when the `claude` binary is on PATH.
      - At least one must be available, else fail fast with a config error.
    """
    config = _config_module.config

    api_client: LLMClient | None = None
    if config.anthropic_api_key:
        api_client = ClaudeClient(api_key=config.anthropic_api_key)

    cli_client: LLMClient | None = None
    if shutil.which(ClaudeCLIClient.DEFAULT_BIN) is not None:
        cli_client = ClaudeCLIClient()

    if api_client is None and cli_client is None:
        raise ValueError(
            "no LLM provider configured: set ANTHROPIC_API_KEY for "
            "claude, or install the `claude` CLI on PATH for claude_cli"
        )

    return LLMRouter(
        api_client=api_client,
        cli_client=cli_client,
        default_provider=config.llm_provider,
        escalate_tags=config.escalate_tags_set,
    )


def get_llm_client() -> LLMClient:
    """Construct an LLMClient based on `config.llm_provider`.

    Reads from the global `config` (pydantic-settings, populated from .env).
    Raises ValueError on missing required credentials or unknown provider.
    Raises NotImplementedError for providers known to the spec but not yet built.
    """
    config = _config_module.config
    provider = config.llm_provider.lower()

    if provider == "claude":
        if not config.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=claude")
        return ClaudeClient(api_key=config.anthropic_api_key)

    if provider in ("claude_cli", "claude-cli"):
        # Subprocess adapter: drives the local `claude` CLI so the daemon
        # consumes your Claude.ai subscription quota instead of the API.
        # No API key required; the CLI handles auth via its own login.
        return ClaudeCLIClient()

    if provider == "openai":
        raise NotImplementedError(
            "openai provider is not implemented yet (see Plan 5 — Multi-LLM)"
        )

    if provider == "ollama":
        raise NotImplementedError(
            "ollama provider is not implemented yet (see Plan 5 — Multi-LLM)"
        )

    raise ValueError(f"unknown LLM_PROVIDER: {provider!r}")
