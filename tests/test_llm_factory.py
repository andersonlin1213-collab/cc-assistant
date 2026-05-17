import os

import pytest

from src.agent.llm.claude import ClaudeClient
from src.agent.llm.claude_cli import ClaudeCLIClient
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


def test_factory_returns_claude_cli_for_provider_claude_cli(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude_cli")
    # No API key needed for this provider.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    import importlib
    import src.config

    importlib.reload(src.config)

    client = get_llm_client()
    assert isinstance(client, ClaudeCLIClient)


def test_factory_accepts_hyphen_form_of_claude_cli(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude-cli")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    import importlib
    import src.config

    importlib.reload(src.config)

    client = get_llm_client()
    assert isinstance(client, ClaudeCLIClient)


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
