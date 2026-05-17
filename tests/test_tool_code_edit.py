from src.tools.code_edit import CodeEditTool


async def test_read_lines_full_file(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("line1\nline2\nline3\n", encoding="utf-8")

    tool = CodeEditTool()
    result = await tool.execute(operation="read_lines", path=str(f))

    assert result.success is True
    assert "line1" in result.output
    assert "line3" in result.output


async def test_read_lines_range(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("a\nb\nc\nd\ne\n", encoding="utf-8")

    tool = CodeEditTool()
    result = await tool.execute(
        operation="read_lines", path=str(f), start_line=2, end_line=4
    )

    assert result.success is True
    # Lines 2-4 of "a/b/c/d/e" are b, c, d
    assert "b" in result.output
    assert "c" in result.output
    assert "d" in result.output
    assert "a" not in result.output.split("\n")[0]  # 'a' is line 1, excluded


async def test_read_lines_missing_file_returns_error(tmp_path):
    tool = CodeEditTool()
    result = await tool.execute(operation="read_lines", path=str(tmp_path / "nope.py"))

    assert result.success is False
    assert "not found" in (result.error or "").lower()


async def test_replace_in_file_unique_match(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("def foo():\n    return 1\n", encoding="utf-8")

    tool = CodeEditTool()
    result = await tool.execute(
        operation="replace_in_file",
        path=str(f),
        search="return 1",
        replace="return 42",
    )

    assert result.success is True
    assert f.read_text(encoding="utf-8") == "def foo():\n    return 42\n"


async def test_replace_in_file_no_match_returns_error(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("def foo():\n    return 1\n", encoding="utf-8")

    tool = CodeEditTool()
    result = await tool.execute(
        operation="replace_in_file",
        path=str(f),
        search="not present",
        replace="something",
    )

    assert result.success is False
    assert "no match" in (result.error or "").lower()
    assert f.read_text(encoding="utf-8") == "def foo():\n    return 1\n"  # unchanged


async def test_replace_in_file_multiple_matches_returns_error(tmp_path):
    """If search matches more than once, fail loudly — protects against accidental edits."""
    f = tmp_path / "code.py"
    f.write_text("x = 1\ny = 1\nz = 1\n", encoding="utf-8")

    tool = CodeEditTool()
    result = await tool.execute(
        operation="replace_in_file",
        path=str(f),
        search="= 1",
        replace="= 2",
    )

    assert result.success is False
    assert "multiple" in (result.error or "").lower()
    assert "3" in (result.error or "")  # mentions the count
    # File unchanged
    assert "x = 1" in f.read_text(encoding="utf-8")


async def test_replace_dry_run_does_not_write(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("hello\n", encoding="utf-8")

    tool = CodeEditTool()
    result = await tool.execute(
        operation="replace_in_file",
        path=str(f),
        search="hello",
        replace="goodbye",
        dry_run=True,
    )

    assert result.success is True
    assert "[dry-run]" in result.output
    assert f.read_text(encoding="utf-8") == "hello\n"  # unchanged


async def test_unknown_operation_returns_error():
    tool = CodeEditTool()
    result = await tool.execute(operation="weird", path="/tmp/x")

    assert result.success is False
    assert "unknown operation" in (result.error or "").lower()
