import json

import httpx

from src.tools.api_caller import ApiCallerTool


def _echo_handler(captured):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content.decode("utf-8") if request.content else ""
        return httpx.Response(200, json={"received": "ok"})

    return handler


async def test_get_request():
    captured: dict = {}
    tool = ApiCallerTool(transport=httpx.MockTransport(_echo_handler(captured)))

    result = await tool.execute(method="GET", url="https://api.example.com/users")

    assert result.success is True
    assert captured["method"] == "GET"
    body = json.loads(result.output)
    assert body["received"] == "ok"


async def test_post_with_json_body():
    captured: dict = {}
    tool = ApiCallerTool(transport=httpx.MockTransport(_echo_handler(captured)))

    result = await tool.execute(
        method="POST",
        url="https://api.example.com/users",
        json_body={"name": "alice"},
    )

    assert result.success is True
    assert captured["method"] == "POST"
    sent = json.loads(captured["body"])
    assert sent == {"name": "alice"}


async def test_query_params_in_url():
    captured: dict = {}
    tool = ApiCallerTool(transport=httpx.MockTransport(_echo_handler(captured)))

    await tool.execute(
        method="GET",
        url="https://api.example.com/search",
        query_params={"q": "hello", "page": 2},
    )

    assert "q=hello" in captured["url"]
    assert "page=2" in captured["url"]


async def test_custom_headers_passed():
    captured: dict = {}
    tool = ApiCallerTool(transport=httpx.MockTransport(_echo_handler(captured)))

    await tool.execute(
        method="GET",
        url="https://api.example.com/me",
        headers={"Authorization": "Bearer xyz"},
    )

    assert captured["headers"].get("authorization") == "Bearer xyz"


async def test_dry_run_skips_get_too():
    """For an api_caller, GET could still be expensive — dry_run skips ALL methods."""
    called = {"n": 0}

    def handler(request):
        called["n"] += 1
        return httpx.Response(200)

    tool = ApiCallerTool(transport=httpx.MockTransport(handler))
    result = await tool.execute(
        method="GET", url="https://api.example.com/foo", dry_run=True
    )

    assert result.success is True
    assert "[dry-run]" in result.output
    assert called["n"] == 0


async def test_non_2xx_returns_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    tool = ApiCallerTool(transport=httpx.MockTransport(handler))
    result = await tool.execute(method="GET", url="https://api.example.com/secret")

    assert result.success is False
    assert "403" in (result.error or "")


async def test_missing_method_returns_error():
    tool = ApiCallerTool()
    result = await tool.execute(url="https://api.example.com")

    assert result.success is False
    assert "method" in (result.error or "").lower()


async def test_missing_url_returns_error():
    tool = ApiCallerTool()
    result = await tool.execute(method="GET")

    assert result.success is False
    assert "url" in (result.error or "").lower()
