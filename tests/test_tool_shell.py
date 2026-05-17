import sys

import pytest

from src.tools.shell import ShellTool


async def test_shell_runs_simple_command():
    tool = ShellTool()
    # `python -c` works on all platforms; avoid `echo` which differs across shells.
    result = await tool.execute(
        command=f'{sys.executable} -c "print(1 + 2)"'
    )

    assert result.success is True
    assert result.output.strip() == "3"
    assert result.metadata is not None
    assert result.metadata["returncode"] == 0


async def test_shell_captures_stderr_on_failure():
    tool = ShellTool()
    result = await tool.execute(
        command=f'{sys.executable} -c "import sys; sys.stderr.write(\\"oops\\"); sys.exit(2)"'
    )

    assert result.success is False
    assert result.error is not None
    assert "oops" in result.error
    assert result.metadata["returncode"] == 2


async def test_shell_dry_run_does_not_execute():
    """A dry_run shell call must not actually run anything."""
    tool = ShellTool()
    # Use a command that would have an observable side effect if it ran:
    # writing a file. But since we're in dry_run mode, no file is created.
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        marker = Path(td) / "marker.txt"
        cmd = f'{sys.executable} -c "open(r\\"{marker}\\", \\"w\\").write(\\"ran\\")"'

        result = await tool.execute(command=cmd, dry_run=True)

        assert result.success is True
        assert "[dry-run]" in result.output
        assert not marker.exists()


async def test_shell_timeout():
    tool = ShellTool()
    # Sleep longer than the timeout
    result = await tool.execute(
        command=f'{sys.executable} -c "import time; time.sleep(2)"',
        timeout_seconds=1,
    )

    assert result.success is False
    assert "timed out" in (result.error or "").lower()


async def test_shell_missing_command_returns_error():
    tool = ShellTool()
    result = await tool.execute()  # no command

    assert result.success is False
    assert "command" in (result.error or "").lower()


async def test_shell_timeout_metadata():
    """Timeout populates metadata.timed_out=True and metadata.returncode=None."""
    tool = ShellTool()
    result = await tool.execute(
        command=f'{sys.executable} -c "import time; time.sleep(2)"',
        timeout_seconds=1,
    )

    assert result.success is False
    assert result.metadata is not None
    assert result.metadata["timed_out"] is True
    assert result.metadata["returncode"] is None
