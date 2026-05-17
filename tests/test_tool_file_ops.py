from pathlib import Path

from src.tools.file_ops import FileOpsTool


async def test_read_existing_file(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("hello world", encoding="utf-8")

    tool = FileOpsTool()
    result = await tool.execute(operation="read", path=str(f))

    assert result.success is True
    assert result.output == "hello world"


async def test_read_missing_file_returns_error(tmp_path):
    tool = FileOpsTool()
    result = await tool.execute(operation="read", path=str(tmp_path / "nope.txt"))

    assert result.success is False
    assert result.error is not None
    assert "not found" in result.error.lower()


async def test_write_new_file(tmp_path):
    target = tmp_path / "out.txt"
    tool = FileOpsTool()
    result = await tool.execute(
        operation="write",
        path=str(target),
        content="new content",
    )

    assert result.success is True
    assert target.read_text(encoding="utf-8") == "new content"


async def test_write_overwrites_existing(tmp_path):
    target = tmp_path / "existing.txt"
    target.write_text("old", encoding="utf-8")

    tool = FileOpsTool()
    await tool.execute(operation="write", path=str(target), content="new")

    assert target.read_text(encoding="utf-8") == "new"


async def test_write_dry_run_does_not_create_file(tmp_path):
    target = tmp_path / "ghost.txt"
    tool = FileOpsTool()
    result = await tool.execute(
        operation="write",
        path=str(target),
        content="should not exist",
        dry_run=True,
    )

    assert result.success is True
    assert "[dry-run]" in result.output
    assert not target.exists()


async def test_delete_existing_file(tmp_path):
    target = tmp_path / "doomed.txt"
    target.write_text("x", encoding="utf-8")

    tool = FileOpsTool()
    result = await tool.execute(operation="delete", path=str(target))

    assert result.success is True
    assert not target.exists()


async def test_delete_dry_run_does_not_delete(tmp_path):
    target = tmp_path / "saved.txt"
    target.write_text("survives", encoding="utf-8")

    tool = FileOpsTool()
    result = await tool.execute(operation="delete", path=str(target), dry_run=True)

    assert result.success is True
    assert "[dry-run]" in result.output
    assert target.exists()


async def test_unknown_operation_returns_error():
    tool = FileOpsTool()
    result = await tool.execute(operation="lol", path="/tmp/whatever")

    assert result.success is False
    assert "unknown operation" in (result.error or "").lower()


async def test_missing_required_params_returns_error():
    tool = FileOpsTool()
    result = await tool.execute(operation="read")  # no path

    assert result.success is False
    assert "path" in (result.error or "").lower()


async def test_unicode_content_round_trip(tmp_path):
    """Chinese (and other UTF-8) content must round-trip via write+read."""
    target = tmp_path / "chinese.md"
    tool = FileOpsTool()

    text = "你好，世界。\n部署到生产环境。"
    write_result = await tool.execute(operation="write", path=str(target), content=text)
    read_result = await tool.execute(operation="read", path=str(target))

    assert write_result.success
    assert read_result.success
    assert read_result.output == text
