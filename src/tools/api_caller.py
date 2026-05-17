from __future__ import annotations

from typing import Any, Optional

import httpx

from src.tools.base import Tool, ToolResult


class ApiCallerTool(Tool):
    """Make a single HTTP request to a third-party REST API.

    Supports any standard method (GET/POST/PUT/PATCH/DELETE), JSON body, query
    params, custom headers. Returns the response text in `output` on success;
    HTTP errors (4xx/5xx) are reported as failure with status in metadata.

    `dry_run=True` skips the request entirely (even GET) — for an API caller,
    even a "read" can be expensive (rate limits, auth tokens) so we are
    conservative.
    """

    name = "api_caller"
    description = (
        "Make an HTTP request to a third-party REST API. Methods: GET/POST/PUT/PATCH/DELETE. "
        "Returns response body. HTTP errors (4xx/5xx) come back as failures."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
            },
            "url": {"type": "string"},
            "headers": {
                "type": "object",
                "description": "Optional HTTP headers.",
            },
            "json_body": {
                "type": "object",
                "description": "Optional JSON body for POST/PUT/PATCH.",
            },
            "query_params": {
                "type": "object",
                "description": "Optional query string parameters.",
            },
            "timeout_seconds": {"type": "integer", "default": 30},
        },
        "required": ["method", "url"],
    }
    risk_level = "high"  # generic API call could mutate remote state

    DEFAULT_TIMEOUT_SECONDS = 30

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        self._transport = transport

    async def execute(self, dry_run: bool = False, **params: Any) -> ToolResult:
        method = params.get("method")
        url = params.get("url")
        if not method:
            return ToolResult(success=False, output="", error="missing 'method' parameter")
        if not url:
            return ToolResult(success=False, output="", error="missing 'url' parameter")

        method = str(method).upper()
        timeout = float(params.get("timeout_seconds") or self.DEFAULT_TIMEOUT_SECONDS)

        if dry_run:
            return ToolResult(
                success=True,
                output=f"[dry-run] would {method} {url}",
            )

        client_kwargs: dict[str, Any] = {"timeout": timeout, "follow_redirects": True}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport

        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.request(
                    method,
                    url,
                    headers=params.get("headers"),
                    json=params.get("json_body"),
                    params=params.get("query_params"),
                )
        except httpx.TimeoutException as e:
            return ToolResult(success=False, output="", error=f"timeout: {e}")
        except httpx.HTTPError as e:
            return ToolResult(success=False, output="", error=f"http error: {e}")

        if response.status_code >= 400:
            return ToolResult(
                success=False,
                output=response.text,
                error=f"HTTP {response.status_code}",
                metadata={"status_code": response.status_code},
            )

        return ToolResult(
            success=True,
            output=response.text,
            metadata={"status_code": response.status_code},
        )
