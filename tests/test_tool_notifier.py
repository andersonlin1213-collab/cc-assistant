import json

import httpx

from src.tools.notifier import NotifierTool


def _capturing_handler(captured):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"errcode": 0})

    return handler


async def test_send_text_message():
    captured: dict = {}
    tool = NotifierTool(
        webhook_url="https://wechat.example/webhook?key=abc",
        transport=httpx.MockTransport(_capturing_handler(captured)),
    )

    result = await tool.execute(message="hello")

    assert result.success is True
    assert captured["method"] == "POST"
    assert captured["url"] == "https://wechat.example/webhook?key=abc"
    assert captured["body"]["msgtype"] == "text"
    assert captured["body"]["text"]["content"] == "hello"


async def test_send_with_mentions():
    captured: dict = {}
    tool = NotifierTool(
        webhook_url="https://wechat.example/webhook",
        transport=httpx.MockTransport(_capturing_handler(captured)),
    )

    await tool.execute(message="hi", mentioned=["alice", "bob"])

    assert captured["body"]["text"]["mentioned_list"] == ["alice", "bob"]


async def test_send_dry_run_does_not_post():
    captured: dict = {}
    called = {"n": 0}

    def handler(request):
        called["n"] += 1
        return httpx.Response(200)

    tool = NotifierTool(
        webhook_url="https://wechat.example/webhook",
        transport=httpx.MockTransport(handler),
    )

    result = await tool.execute(message="ping", dry_run=True)

    assert result.success is True
    assert "[dry-run]" in result.output
    assert called["n"] == 0


async def test_send_missing_message_returns_error():
    tool = NotifierTool(webhook_url="https://wechat.example/webhook")
    result = await tool.execute()

    assert result.success is False
    assert "message" in (result.error or "").lower()


async def test_send_missing_webhook_returns_error():
    tool = NotifierTool(webhook_url="")
    result = await tool.execute(message="hi")

    assert result.success is False
    assert "webhook" in (result.error or "").lower()


async def test_send_non_2xx_returns_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    tool = NotifierTool(
        webhook_url="https://wechat.example/webhook",
        transport=httpx.MockTransport(handler),
    )

    result = await tool.execute(message="hi")

    assert result.success is False
    assert "500" in (result.error or "")


async def test_send_wechat_errcode_nonzero_returns_error():
    """WeChat returns HTTP 200 even on logical errors; check errcode field."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errcode": 93000, "errmsg": "invalid webhook"})

    tool = NotifierTool(
        webhook_url="https://wechat.example/webhook",
        transport=httpx.MockTransport(handler),
    )

    result = await tool.execute(message="hi")

    assert result.success is False
    assert "93000" in (result.error or "")


async def test_notifier_sends_markdown_msgtype_when_deep_link_provided():
    captured: dict = {}
    tool = NotifierTool(
        webhook_url="https://wechat.example/webhook?key=abc",
        transport=httpx.MockTransport(_capturing_handler(captured)),
    )
    result = await tool.execute(
        message="任务被卡住",
        deep_link="obsidian://open?vault=cc-assistant&file=blocked/036.md",
    )
    assert result.success is True
    payload = captured["body"]
    assert payload["msgtype"] == "markdown"
    content = payload["markdown"]["content"]
    assert "任务被卡住" in content
    assert "obsidian://open?vault=cc-assistant&file=blocked/036.md" in content


async def test_notifier_falls_back_to_text_when_no_deep_link():
    captured: dict = {}
    tool = NotifierTool(
        webhook_url="https://wechat.example/webhook",
        transport=httpx.MockTransport(_capturing_handler(captured)),
    )
    result = await tool.execute(message="hi")
    assert result.success is True
    assert captured["body"]["msgtype"] == "text"
