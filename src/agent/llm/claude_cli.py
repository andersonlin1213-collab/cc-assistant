"""Subprocess-based LLM client that drives the local `claude` CLI.

Use this provider (`LLM_PROVIDER=claude_cli` in .env) to consume your
Claude.ai subscription quota (Pro / Max) instead of paying per-token via
the Anthropic API.

Trade-offs vs `ClaudeClient` (Anthropic SDK):
  - tool_use blocks are NOT exposed: the CLI runs its own native tools
    (Read / Write / Bash / Edit / etc.) internally and returns only the
    final text. cc-assistant's custom ToolDefinition list is ignored.
  - prompt caching is the CLI's concern, not ours.
  - usage / cost reporting is best-effort, parsed from the CLI's
    `--output-format json` schema.

The CLI must be on PATH (`claude` resolves) and the user must already be
authenticated (`claude login`).
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
from typing import Any
from urllib.parse import urlparse

from src.agent.llm.base import LLMClient
from src.agent.llm.types import (
    LLMResponse,
    Message,
    TextBlock,
    ToolDefinition,
    Usage,
)


# Env vars that, when present, make `claude` CLI use an "external API key"
# instead of the user's logged-in subscription session. cc-assistant's
# .env may set ANTHROPIC_API_KEY for the SDK-based ClaudeClient; that value
# must NOT leak into the CLI subprocess, or the CLI will try to use it for
# auth and fail with HTTP 401 if the key is a placeholder.
_EXTERNAL_API_KEY_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_API_KEY",
)


# Substrings in the CLI's `result` field that mean "couldn't reach the API"
# rather than "API said no". When we see these we route through
# ProviderUnavailable instead of cycle_error so the user sees a `[系统]`
# notice plus a placeholder (and not a giant error JSON dumped as an AI
# reply). Observed live on 5/6 23:22 when v2rayN was down for 12 hours
# and the daemon racked up `[Error] ConnectionRefused` walls.
_CONNECTION_ERROR_MARKERS = (
    "ConnectionRefused",
    "Unable to connect",
    "Connection error",
    "ECONNREFUSED",
    "ETIMEDOUT",
    "ENETUNREACH",
)


def _proxy_alive(env: dict[str, str], timeout: float = 1.0) -> tuple[bool, str | None]:
    """TCP-probe the configured HTTP/HTTPS proxy, if any.

    Returns ``(alive, addr)`` where ``addr`` is ``host:port`` of the proxy
    we tried (None if no proxy is configured). When no proxy is set we
    return ``(True, None)`` so non-proxy users skip this check entirely.

    The probe is a single TCP connect with a short timeout — it doesn't
    actually do HTTP. The point is to fail fast (~ms) instead of letting
    the claude CLI subprocess burn its full timeout window discovering
    the same outage; observed mode on 5/6 was a 3-minute hang per cycle.
    """
    proxy_url = env.get("HTTPS_PROXY") or env.get("HTTP_PROXY")
    if not proxy_url:
        return True, None
    try:
        u = urlparse(proxy_url)
        host = u.hostname or ""
        port = u.port or (443 if u.scheme == "https" else 80)
    except Exception:  # pylint: disable=broad-except
        # Malformed proxy URL — don't block on it; let the CLI surface
        # whatever real failure follows.
        return True, None
    if not host:
        return True, None
    addr = f"{host}:{port}"
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True, addr
    except (OSError, socket.timeout):
        return False, addr


def _format_cli_failure(returncode: int, stdout: str, stderr: str) -> tuple[str, bool]:
    """Turn the CLI's noisy JSON envelope into a one-line human message.

    Returns ``(message, is_connection_error)``. When stdout is parseable
    JSON, we extract the human-readable `result` field plus the HTTP
    status if any; the rest of the envelope (input_tokens, session_id,
    iterations, etc.) is dropped — it bloats the conversation with
    nothing actionable. When stdout isn't JSON we fall back to the old
    truncated stdout/stderr dump.

    The boolean tells the caller whether the failure is a network-reach
    issue (ConnectionRefused etc.) so it can route through the
    `[系统]` provider_unavailable channel instead of polluting the
    conversation with an `[Error]` AI reply.
    """
    is_conn_err = False
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        truncated_out = stdout[:300] if stdout else ""
        truncated_err = stderr[:300] if stderr else ""
        msg = (
            f"claude CLI exited {returncode}: "
            f"stdout={truncated_out!r} stderr={truncated_err!r}"
        )
        return msg, is_conn_err

    result_msg = str(data.get("result") or "").strip()
    api_status = data.get("api_error_status")
    duration = data.get("duration_ms", 0)

    is_conn_err = any(m in result_msg for m in _CONNECTION_ERROR_MARKERS)

    parts = [f"claude CLI failed: {result_msg or '(no result message)'}"]
    if api_status is not None:
        parts.append(f"HTTP {api_status}")
    if duration:
        parts.append(f"after {duration}ms")
    msg = " — ".join(parts)
    return msg, is_conn_err


class ClaudeCLIClient(LLMClient):
    DEFAULT_BIN = "claude"

    def __init__(
        self,
        bin_path: str | None = None,
        model: str | None = None,
    ) -> None:
        self.bin_path = bin_path or shutil.which(self.DEFAULT_BIN) or self.DEFAULT_BIN
        # `model` is informational only; the CLI uses its own configured model
        # (settable via `claude /model` or --model). We surface it on
        # LLMResponse.model when the JSON output doesn't include one.
        self.model = model or "claude-cli"

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        if not messages:
            raise ValueError("ClaudeCLIClient.chat requires at least one message")

        # `tools` and `max_tokens` are part of the interface but ignored: the
        # CLI manages its own tool ecosystem and output length. cc-assistant's
        # custom tools (DatabaseTool / NotifierTool / ApiCallerTool /
        # WebFetchTool) are unreachable from this provider — that's why
        # `LLMRouter` (src/agent/llm/router.py) exists: tasks tagged with
        # any of `Config.escalate_tags` get routed to `ClaudeClient` (API)
        # so their tools work. If you're seeing a task that needs mysql or
        # dingtalk silently no-op here, the fix is to tag it (or set
        # `provider: claude` in frontmatter), not to add tool support here.
        del tools, max_tokens

        prompt = self._render_messages(messages)
        # On Windows the CLI is typically a `.CMD` npm shim; passing a long
        # multi-line prompt as a positional arg gets mangled by cmd.exe quote
        # parsing (the CLI then enters interactive mode and hangs / returns
        # the wrong response). Piping via stdin sidesteps both the shim and
        # the platform's command-line length / quoting limits.
        env = {
            k: v for k, v in os.environ.items()
            if k not in _EXTERNAL_API_KEY_VARS
        }

        # Pre-flight: if the user routes through a local proxy (mainland
        # China / GFW workflow with v2rayN/clash/etc.), TCP-probe it before
        # spawning the subprocess. Avoids the 3-minute timeout hang we hit
        # on 5/6 when v2rayN was down — see _proxy_alive's docstring.
        # Imported lazily to avoid a circular import at module load
        # (router imports LLMClient which is imported here).
        proxy_ok, proxy_addr = _proxy_alive(env)
        if not proxy_ok:
            from src.agent.llm.router import ProviderUnavailable
            raise ProviderUnavailable(
                f"代理不可达 ({proxy_addr}) — 检查 v2rayN/clash 是否在跑"
            )

        proc = await asyncio.create_subprocess_exec(
            self.bin_path,
            "-p", "",
            "--output-format", "json",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout_b, stderr_b = await proc.communicate(input=prompt.encode("utf-8"))
        if proc.returncode != 0:
            stdout = stdout_b.decode("utf-8", errors="replace")
            stderr = stderr_b.decode("utf-8", errors="replace")
            msg, is_conn_err = _format_cli_failure(
                proc.returncode, stdout, stderr
            )
            if is_conn_err:
                # Route network-reach failures through the same channel as
                # missing-credential failures: [系统] notice in the file +
                # placeholder, no giant JSON dumped as an AI reply.
                from src.agent.llm.router import ProviderUnavailable
                raise ProviderUnavailable(msg)
            raise RuntimeError(msg)
        return self._parse_response(stdout_b.decode("utf-8", errors="replace"))

    @staticmethod
    def _render_messages(messages: list[Message]) -> str:
        """Flatten the typed Message list into one prompt string.

        The CLI's `-p` mode takes a single prompt; we render the conversation
        as labeled segments so the model can recover turn structure. System
        messages are concatenated and emitted first.
        """
        parts: list[str] = []
        label = {"system": "[SYSTEM]", "user": "[USER]", "assistant": "[ASSISTANT]"}
        for m in messages:
            text = m.content if isinstance(m.content, str) else _blocks_text(m.content)
            parts.append(f"{label[m.role]}\n{text}")
        return "\n\n".join(parts)

    def _parse_response(self, raw: str) -> LLMResponse:
        try:
            data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            # Fallback: treat whatever we got as the assistant's text.
            return LLMResponse(
                content=[TextBlock(text=raw)],
                stop_reason="end_turn",
                usage=Usage(),
                model=self.model,
            )

        text = str(data.get("result") or data.get("response") or raw)
        stop_reason = str(data.get("stop_reason") or "end_turn")

        usage_d = data.get("usage") or {}
        usage = Usage(
            input_tokens=int(usage_d.get("input_tokens", 0)),
            output_tokens=int(usage_d.get("output_tokens", 0)),
            cache_creation_input_tokens=int(
                usage_d.get("cache_creation_input_tokens", 0)
            ),
            cache_read_input_tokens=int(usage_d.get("cache_read_input_tokens", 0)),
        )

        # `modelUsage` keys are the actual model strings the CLI used. Pick
        # the first one for the response's `model` field; fall back to the
        # configured default.
        model_usage = data.get("modelUsage") or {}
        if isinstance(model_usage, dict) and model_usage:
            model = str(next(iter(model_usage.keys())))
        else:
            model = self.model

        return LLMResponse(
            content=[TextBlock(text=text)],
            stop_reason=stop_reason,
            usage=usage,
            model=model,
        )


def _blocks_text(blocks: list) -> str:
    parts: list[str] = []
    for b in blocks:
        if isinstance(b, TextBlock):
            parts.append(b.text)
    return "\n".join(parts)
