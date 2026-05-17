import os
from pathlib import Path

from src.lifecycle import read_pid, remove_pid, write_pid


def test_write_and_read_pid(tmp_path):
    pid_path = tmp_path / "agent.pid"
    write_pid(pid_path, 12345)

    assert pid_path.exists()
    assert read_pid(pid_path) == 12345


def test_read_missing_pid_returns_none(tmp_path):
    assert read_pid(tmp_path / "nope.pid") is None


def test_read_garbage_pid_returns_none(tmp_path):
    pid_path = tmp_path / "agent.pid"
    pid_path.write_text("not a number\n", encoding="utf-8")

    assert read_pid(pid_path) is None


def test_remove_pid_removes_file(tmp_path):
    pid_path = tmp_path / "agent.pid"
    write_pid(pid_path, 100)

    remove_pid(pid_path)

    assert not pid_path.exists()


def test_remove_pid_missing_is_noop(tmp_path):
    """Removing a non-existent PID file does not raise."""
    remove_pid(tmp_path / "missing.pid")  # should not raise


def test_write_pid_creates_parent_dirs(tmp_path):
    """write_pid creates the parent directory if needed."""
    pid_path = tmp_path / "deep" / "logs" / "agent.pid"
    write_pid(pid_path, 999)

    assert pid_path.exists()
    assert read_pid(pid_path) == 999


def test_write_pid_uses_current_process_when_no_pid_arg(tmp_path):
    """write_pid() with no pid arg defaults to os.getpid()."""
    pid_path = tmp_path / "agent.pid"
    write_pid(pid_path)

    assert read_pid(pid_path) == os.getpid()
