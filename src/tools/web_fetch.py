from __future__ import annotations

from typing import Any, Optional

import httpx

from src.tools.base import Tool, ToolResult


class WebFetchTool(Tool):
    """Fetch the content of a single URL via HTTP GET.

    Returns the response body as text. Bodies longer than `max_chars` are truncated
    with a trailing marker so the LLM knows the result was cut off.

    Note: this tool only fetches a known URL. Real internet search (e.g., via
    Serper or Google) is deferred to a future plan.
    """

    name = "web_fetch"
    description = (
        "Fetch the body of a URL via HTTP GET. Returns text. Bodies longer than "
        "max_chars are truncated. For binary or HTML-heavy pages, expect raw text."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full HTTP/HTTPS URL."},
            "timeout_seconds": {
                "type": "integer",
                "description": "Hard timeout. Default 30.",
                "default": 30,
            },
            "max_chars": {
                "type": "integer",
                "description": "Truncate body to this many characters. Default 50000.",
                "default": 50_000,
            },
        },
        "required": ["url"],
    }
    risk_level = "low"

    DEFAULT_TIMEOUT_SECONDS = 30
    DEFAULT_MAX_CHARS = 50_000

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        # transport injection enables MockTransport in tests; production passes None
        self._transport = transport

    async def execute(self, dry_run: bool = False, **params: Any) -> ToolResult:
        url = params.get("url")
        if not url:
            return ToolResult(success=False, output="", error="missing 'url' parameter")
        timeout = float(params.get("timeout_seconds") or self.DEFAULT_TIMEOUT_SECONDS)
        max_chars = int(params.get("max_chars") or self.DEFAULT_MAX_CHARS)

        if dry_run:
            return ToolResult(success=True, output=f"[dry-run] would GET {url}")

        client_kwargs: dict[str, Any] = {"timeout": timeout, "follow_redirects": True}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport

        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.get(url)
        except httpx.TimeoutException as e:
            return ToolResult(success=False, output="", error=f"timeout: {e}")
        except httpx.HTTPError as e:
            return ToolResult(success=False, output="", error=f"http error: {e}")

        if response.status_code >= 400:
            return ToolResult(
                success=False,
                output="",
                error=f"HTTP {response.status_code}",
                metadata={"status_code": response.status_code},
            )

        body = response.text
        if len(body) > max_chars:
            body = body[:max_chars] + "\n[...truncated]"

        return ToolResult(
            success=True,
            output=body,
            metadata={"status_code": response.status_code},
        )
