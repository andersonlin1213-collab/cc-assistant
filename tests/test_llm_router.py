"""LLMRouter routing tests.

Covers the precedence ladder:
  explicit task.provider → tag-based escalation → config default,
plus ProviderUnavailable when the resolved target isn't configured.

ClaudeClient and ClaudeCLIClient are stubbed with sentinels — the router
shouldn't care what an LLMClient actually is, only which slot it's in.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from src.agent.llm.router import LLMRouter, ProviderUnavailable
from src.models import Priority, Task


def _task(*, provider: str | None = None, tags: list[str] | None = None) -> Task:
    return Task(
        id="100",
        title="t",
        priority=Priority.P1,
        tags=tags or [],
        created=datetime(2026, 5, 5),
        updated=datetime(2026, 5, 5),
        provider=provider,
    )


def test_router_requires_at_least_one_provider():
    with pytest.raises(ValueError, match="at least one"):
        LLMRouter(api_client=None, cli_client=None, default_provider="claude")


def test_explicit_claude_routes_to_api():
    api, cli = object(), object()
    router = LLMRouter(api, cli, default_provider="claude_cli")
    assert router.select(_task(provider="claude")) is api


def test_explicit_claude_cli_routes_to_cli():
    api, cli = object(), object()
    router = LLMRouter(api, cli, default_provider="claude")
    assert router.select(_task(provider="claude_cli")) is cli


def test_explicit_claude_dash_cli_alias_works():
    """Accept the hyphenated alias `claude-cli` as well as the underscored
    canonical form. Mobile users sometimes type either."""
    api, cli = object(), object()
    router = LLMRouter(api, cli, default_provider="claude")
    assert router.select(_task(provider="claude-cli")) is cli


def test_unknown_explicit_provider_raises():
    api, cli = object(), object()
    router = LLMRouter(api, cli, default_provider="claude")
    with pytest.raises(ProviderUnavailable, match="unknown task.provider"):
        router.select(_task(provider="gpt-4"))


def test_tag_based_escalation_routes_to_api():
    """A task tagged with one of the custom-tool signals (mysql/dingtalk/etc.)
    needs cc-assistant's tools, which only the API path exposes. Router must
    escalate to ClaudeClient even when the config default is claude_cli."""
    api, cli = object(), object()
    router = LLMRouter(api, cli, default_provider="claude_cli")
    for tag in ("db", "mysql", "wecom", "dingtalk", "api"):
        assert router.select(_task(tags=[tag])) is api, (
            f"tag {tag!r} should escalate to API but didn't"
        )


def test_explicit_claude_cli_overrides_tag_escalation():
    """When the user is explicit about the provider, that wins — even if a
    tag would normally escalate. Lets the user opt out of escalation for
    one-off cases (e.g. a tag was added for grouping, not tool need)."""
    api, cli = object(), object()
    router = LLMRouter(api, cli, default_provider="claude_cli")
    selected = router.select(_task(provider="claude_cli", tags=["mysql"]))
    assert selected is cli


def test_config_default_claude_cli():
    api, cli = object(), object()
    router = LLMRouter(api, cli, default_provider="claude_cli")
    assert router.select(_task()) is cli


def test_config_default_claude():
    api, cli = object(), object()
    router = LLMRouter(api, cli, default_provider="claude")
    assert router.select(_task()) is api


def test_unavailable_when_explicit_provider_not_configured():
    """User asks for `provider: claude` but ANTHROPIC_API_KEY is missing
    (api_client=None). Router must raise rather than silently route to the
    other provider — that would run a mysql task on claude_cli where the
    DatabaseTool can't reach."""
    cli = object()
    router = LLMRouter(api_client=None, cli_client=cli, default_provider="claude_cli")
    with pytest.raises(ProviderUnavailable, match="not configured"):
        router.select(_task(provider="claude"))


def test_unavailable_when_tag_escalation_target_missing():
    """Tag-escalated to API but API isn't configured. Same fail-fast logic:
    don't quietly fall back to a provider that can't actually run the task."""
    cli = object()
    router = LLMRouter(api_client=None, cli_client=cli, default_provider="claude_cli")
    with pytest.raises(ProviderUnavailable):
        router.select(_task(tags=["mysql"]))


def test_unavailable_when_default_target_missing():
    """Config default is claude but no API key configured."""
    cli = object()
    router = LLMRouter(api_client=None, cli_client=cli, default_provider="claude")
    with pytest.raises(ProviderUnavailable):
        router.select(_task())


def test_custom_escalate_tags_override_default():
    """User adds a new custom tool (say `grafana`) and wants tasks tagged
    `grafana` to escalate. With the tag set wired through config the user
    just appends to .env — no code change. Builtin tags are dropped from
    the override, mirroring the substitution semantics."""
    api, cli = object(), object()
    router = LLMRouter(
        api, cli, default_provider="claude_cli",
        escalate_tags={"grafana", "kafka"},
    )
    # New tag escalates
    assert router.select(_task(tags=["grafana"])) is api
    # Removed default no longer escalates
    assert router.select(_task(tags=["mysql"])) is cli


def test_default_escalate_tags_when_not_overridden():
    """Backward compat: omit `escalate_tags` and the router uses the
    builtin default set, so tests pre-dating the config field still pass."""
    api, cli = object(), object()
    router = LLMRouter(api, cli, default_provider="claude_cli")
    assert router.select(_task(tags=["mysql"])) is api
