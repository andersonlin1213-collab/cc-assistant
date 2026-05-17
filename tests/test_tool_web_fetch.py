import httpx

from src.tools.web_fetch import WebFetchTool


def _build_mock_transport(handler):
    """Wrap a request handler in httpx.MockTransport for AsyncClient injection."""
    return httpx.MockTransport(handler)


async def test_fetch_returns_body():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.host == "example.com"
        return httpx.Response(200, text="hello world")

    tool = WebFetchTool(transport=_build_mock_transport(handler))
    result = await tool.execute(url="https://example.com/")

    assert result.success is True
    assert result.output == "hello world"


async def test_fetch_non_2xx_returns_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    tool = WebFetchTool(transport=_build_mock_transport(handler))
    result = await tool.execute(url="https://example.com/missing")

    assert result.success is False
    assert "404" in (result.error or "")


async def test_fetch_truncates_long_body():
    big = "x" * 100_000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=big)

    tool = WebFetchTool(transport=_build_mock_transport(handler))
    result = await tool.execute(url="https://example.com/", max_chars=1000)

    assert result.success is True
    assert len(result.output) <= 1000 + len("\n[...truncated]")
    assert result.output.endswith("[...truncated]")


async def test_fetch_dry_run_does_not_make_request():
    """dry_run skips the actual HTTP call and returns a stub."""
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["n"] += 1
        return httpx.Response(200, text="hi")

    tool = WebFetchTool(transport=_build_mock_transport(handler))
    result = await tool.execute(url="https://example.com/", dry_run=True)

    assert result.success is True
    assert "[dry-run]" in result.output
    assert called["n"] == 0


async def test_fetch_missing_url_returns_error():
    tool = WebFetchTool()
    result = await tool.execute()

    assert result.success is False
    assert "url" in (result.error or "").lower()


async def test_fetch_timeout_returns_error():
    """A timeout on the request surfaces as ToolResult(success=False, error=...)."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("simulated timeout", request=request)

    tool = WebFetchTool(transport=_build_mock_transport(handler))
    result = await tool.execute(url="https://example.com/", timeout_seconds=1)

    assert result.success is False
    assert "timeout" in (result.error or "").lower()
