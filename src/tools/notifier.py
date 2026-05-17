from __future__ import annotations

from typing import Any, Optional

import httpx

from src.tools.base import Tool, ToolResult


class NotifierTool(Tool):
    """Send a text message to the configured WeChat enterprise bot webhook.

    The webhook URL is read from `src.config.config.wechat_webhook_url` by default;
    pass `webhook_url` to the constructor to override (used in tests).

    WeChat enterprise bots expect a JSON payload of the form:
        {"msgtype": "text", "text": {"content": "...", "mentioned_list": [...]}}

    They return HTTP 200 with `{"errcode": 0}` on success and a non-zero `errcode`
    on logical failure. Both forms are handled.
    """

    name = "notifier"
    description = (
        "Send a text message to the WeChat enterprise bot webhook. "
        "Useful for alerting the human about completed tasks or blocked status."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
            "mentioned": {
                "type": "array",
                "description": "Optional list of WeChat user IDs to mention.",
            },
            "deep_link": {
                "type": "string",
                "description": (
                    "Optional URL — when set, the notification is sent as a "
                    "markdown message with the link inlined."
                ),
            },
        },
        "required": ["message"],
    }
    risk_level = "low"

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        if webhook_url is None:
            from src.config import config
            webhook_url = config.wechat_webhook_url
        self._webhook_url = webhook_url
        self._transport = transport

    async def execute(self, dry_run: bool = False, **params: Any) -> ToolResult:
        message = params.get("message")
        if not message:
            return ToolResult(success=False, output="", error="missing 'message' parameter")
        if not self._webhook_url:
            return ToolResult(
                success=False,
                output="",
                error="webhook URL not configured (set WECHAT_WEBHOOK_URL or pass webhook_url)",
            )

        if dry_run:
            return ToolResult(
                success=True,
                output=f"[dry-run] would send to webhook: {message[:120]}",
            )

        deep_link = params.get("deep_link")
        body: dict[str, Any]
        if deep_link:
            md_content = f"{message}\n\n[打开任务]({deep_link})"
            body = {
                "msgtype": "markdown",
                "markdown": {"content": md_content},
            }
        else:
            body = {
                "msgtype": "text",
                "text": {"content": message},
            }
            mentioned = params.get("mentioned")
            if mentioned:
                body["text"]["mentioned_list"] = list(mentioned)

        client_kwargs: dict[str, Any] = {"timeout": 30}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport

        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.post(self._webhook_url, json=body)
        except httpx.HTTPError as e:
            return ToolResult(success=False, output="", error=f"http error: {e}")

        if response.status_code >= 400:
            return ToolResult(success=False, output="", error=f"HTTP {response.status_code}")

        # WeChat-specific: check errcode
        try:
            payload = response.json()
        except ValueError:
            payload = {}

        errcode = payload.get("errcode")
        if errcode is not None and errcode != 0:
            errmsg = payload.get("errmsg", "")
            return ToolResult(
                success=False,
                output="",
                error=f"WeChat errcode {errcode}: {errmsg}",
            )

        return ToolResult(success=True, output="message sent")
