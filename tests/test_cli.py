import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.cli import build_parser, cmd_status


def test_parser_has_run_subcommand():
    parser = build_parser()
    args = parser.parse_args(["run"])
    assert args.command == "run"
    assert args.dry_run is False


def test_parser_run_dry_run_flag():
    parser = build_parser()
    args = parser.parse_args(["run", "--dry-run"])
    assert args.command == "run"
    assert args.dry_run is True
    assert args.target is None


def test_parser_run_dry_run_with_target(tmp_path):
    parser = build_parser()
    args = parser.parse_args(["run", "--dry-run", "tasks/todo/001-x.md"])
    assert args.dry_run is True
    assert args.target == "tasks/todo/001-x.md"


def test_parser_has_stop_subcommand():
    parser = build_parser()
    args = parser.parse_args(["stop"])
    assert args.command == "stop"


def test_parser_has_status_subcommand():
    parser = build_parser()
    args = parser.parse_args(["status"])
    assert args.command == "status"


def test_status_reports_not_running_when_no_pid_file(tmp_path, capsys):
    """`cc-assistant status` prints 'not running' when no PID file exists."""
    cmd_status(
        pid_file=tmp_path / "agent.pid",
        tasks_dir=tmp_path / "tasks",
        logs_dir=tmp_path / "logs",
    )

    captured = capsys.readouterr()
    assert "not running" in captured.out.lower()


def test_status_reports_running_with_pid(tmp_path, capsys):
    """When PID file exists and process exists, status prints PID + active counts."""
    pid_file = tmp_path / "agent.pid"
    pid_file.write_text("12345\n", encoding="utf-8")

    tasks_dir = tmp_path / "tasks"
    for s in ["backlog", "todo", "doing", "blocked", "review", "done"]:
        (tasks_dir / s).mkdir(parents=True)
    # Add a couple of fake task files
    (tasks_dir / "todo" / "1.md").write_text("---\nid: \"1\"\n---\n", encoding="utf-8")
    (tasks_dir / "doing" / "2.md").write_text("---\nid: \"2\"\n---\n", encoding="utf-8")
    (tasks_dir / "doing" / "3.md").write_text("---\nid: \"3\"\n---\n", encoding="utf-8")

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "agent.jsonl").write_text(
        json.dumps({"ts": "2026-04-26T10:00", "action": "startup", "task_id": "_system",
                    "detail": "agent up", "duration_ms": 0, "status": "success"}) + "\n",
        encoding="utf-8",
    )

    with patch("src.cli.is_pid_alive", return_value=True):
        cmd_status(pid_file=pid_file, tasks_dir=tasks_dir, logs_dir=logs_dir)

    captured = capsys.readouterr()
    assert "12345" in captured.out
    assert "todo" in captured.out
    # Active counts shown
    assert "1" in captured.out  # 1 todo
    assert "2" in captured.out  # 2 doing


def test_status_does_not_kill_running_process(tmp_path, capsys):
    """`cc-assistant status` must NOT terminate the daemon it's checking on.

    Regression: on Windows, `os.kill(pid, 0)` is implemented as
    `TerminateProcess(handle, 0)`, which kills the target process. Status
    must use a probe that does not affect process state.
    """
    import subprocess
    import sys
    import time

    # Spawn a real, long-running child we can probe.
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # Give the OS a moment to register the process before probing.
        time.sleep(0.2)

        pid_file = tmp_path / "agent.pid"
        pid_file.write_text(f"{proc.pid}\n", encoding="utf-8")

        tasks_dir = tmp_path / "tasks"
        for s in ["backlog", "todo", "doing", "blocked", "review", "done"]:
            (tasks_dir / s).mkdir(parents=True)
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()

        cmd_status(pid_file=pid_file, tasks_dir=tasks_dir, logs_dir=logs_dir)

        captured = capsys.readouterr()
        # Liveness must be detected: must report "running", NOT "stale" or "not running".
        assert "stale" not in captured.out.lower(), captured.out
        assert "not running" not in captured.out.lower(), captured.out
        assert f"running (pid={proc.pid})" in captured.out, captured.out

        # The probe must not have affected the child. Give a brief grace
        # window for any signal to propagate, then assert the child is
        # still alive (poll() returns None for a running process).
        time.sleep(0.2)
        assert proc.poll() is None, (
            f"cmd_status terminated the probed process "
            f"(returncode={proc.returncode}); status check must be a no-op probe."
        )
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_cli_run_warns_when_vault_not_initialized(tmp_path, monkeypatch):
    """If tasks/.obsidian/ does not exist, run_startup_checks emits a warning."""
    from src import cli
    (tmp_path / "tasks" / "todo").mkdir(parents=True)
    monkeypatch.setattr(cli.config, "tasks_dir", tmp_path / "tasks")
    monkeypatch.setattr(cli.config, "obsidian_check_process", False)

    warnings = cli.run_startup_checks(cli.config)
    assert any("vault not initialized" in w.lower() for w in warnings)


def test_cli_run_no_warning_when_vault_initialized(tmp_path, monkeypatch):
    from src import cli
    (tmp_path / "tasks" / ".obsidian").mkdir(parents=True)
    (tmp_path / "tasks" / "todo").mkdir()
    monkeypatch.setattr(cli.config, "tasks_dir", tmp_path / "tasks")
    monkeypatch.setattr(cli.config, "obsidian_check_process", False)

    warnings = cli.run_startup_checks(cli.config)
    assert not any("vault not initialized" in w.lower() for w in warnings)


def test_cmd_run_installs_signal_handler_before_start_daemon(monkeypatch, tmp_path):
    """Plan 5a deferred Issue #1: a Ctrl-C arriving while start_daemon is
    setting up (PID write, replay scan, watcher start) used to raise
    KeyboardInterrupt outside the try/finally because make_stop_event ran
    AFTER start_daemon. Signal handler installation must happen first so
    SIGINT during startup just sets the event.

    Test isolation: redirect logs_dir to tmp_path and stub psutil.pid_exists
    so the test ignores any real running daemon's PID file (otherwise the
    'already running' check short-circuits and we never reach the signal
    handler ordering we're trying to verify)."""
    from src import cli

    call_order: list[str] = []
    handle = MagicMock()
    stop_event = MagicMock()
    stop_event.wait.return_value = None

    def fake_make_stop_event(*sigs):
        call_order.append("make_stop_event")
        return stop_event

    def fake_start_daemon(**_kwargs):
        call_order.append("start_daemon")
        return handle

    monkeypatch.setattr(cli.config, "logs_dir", tmp_path)
    monkeypatch.setattr("psutil.pid_exists", lambda pid: False)
    monkeypatch.setattr(cli, "make_stop_event", fake_make_stop_event)
    monkeypatch.setattr(
        "src.runner.start_daemon", fake_start_daemon, raising=True
    )
    monkeypatch.setattr(
        "src.agent.llm.factory.get_llm_router", lambda: MagicMock()
    )
    monkeypatch.setattr(cli, "run_startup_checks", lambda _cfg: [])

    rc = cli.cmd_run(dry_run=False, target=None)

    assert rc == 0
    assert call_order.index("make_stop_event") < call_order.index("start_daemon"), (
        f"make_stop_event must run before start_daemon, got {call_order}"
    )
    handle.stop.assert_called_once()


def test_cmd_run_refuses_to_start_when_daemon_already_running(
    monkeypatch, tmp_path, capsys
):
    """Plan 5a deferred Issue #3: a second `cc-assistant run` while one is
    already running used to silently overwrite the PID file and produce two
    coordinators on the same tasks_dir. cmd_run must probe the existing PID
    and refuse with rc=1 if the process is alive."""
    from src import cli

    pid_file = tmp_path / "agent.pid"
    pid_file.write_text("12345\n", encoding="utf-8")
    monkeypatch.setattr(cli.config, "logs_dir", tmp_path)

    start_daemon_calls = []

    def fake_start_daemon(**kwargs):
        start_daemon_calls.append(kwargs)
        return MagicMock()

    monkeypatch.setattr("src.runner.start_daemon", fake_start_daemon, raising=True)
    monkeypatch.setattr("src.agent.llm.factory.get_llm_router", lambda: MagicMock())
    monkeypatch.setattr(cli, "run_startup_checks", lambda _cfg: [])
    monkeypatch.setattr(cli, "make_stop_event", lambda *sigs: MagicMock())
    # Process is alive
    monkeypatch.setattr("psutil.pid_exists", lambda pid: True)

    rc = cli.cmd_run(dry_run=False, target=None)

    captured = capsys.readouterr()
    assert rc == 1
    assert "already running" in captured.err.lower()
    assert "12345" in captured.err
    assert start_daemon_calls == []  # never started a second daemon
    assert pid_file.exists()  # didn't clobber the live daemon's PID file


def test_cmd_run_clears_stale_pid_file_and_starts(monkeypatch, tmp_path):
    """If a PID file is left over but the recorded process is gone (crash,
    Ctrl-C race before our signal-handler fix landed), cmd_run should
    clean it up and start fresh."""
    from src import cli

    pid_file = tmp_path / "agent.pid"
    pid_file.write_text("99999\n", encoding="utf-8")
    monkeypatch.setattr(cli.config, "logs_dir", tmp_path)

    start_daemon_calls = []

    def fake_start_daemon(**kwargs):
        start_daemon_calls.append(kwargs)
        # The real start_daemon writes the PID; emulate that for assertion.
        kwargs["pid_file"].write_text("77777\n", encoding="utf-8")
        return MagicMock()

    monkeypatch.setattr("src.runner.start_daemon", fake_start_daemon, raising=True)
    monkeypatch.setattr("src.agent.llm.factory.get_llm_router", lambda: MagicMock())
    monkeypatch.setattr(cli, "run_startup_checks", lambda _cfg: [])
    monkeypatch.setattr(cli, "make_stop_event", lambda *sigs: MagicMock())
    # Process is gone
    monkeypatch.setattr("psutil.pid_exists", lambda pid: False)

    rc = cli.cmd_run(dry_run=False, target=None)

    assert rc == 0
    assert len(start_daemon_calls) == 1
    # Stale PID has been replaced by the new daemon's
    assert pid_file.read_text().strip() == "77777"


def test_cmd_stop_prints_pid_even_when_daemon_clears_pid_file(monkeypatch, tmp_path, capsys):
    """Plan 5a deferred Issue #2: cmd_stop must read the PID BEFORE the
    daemon (signaled via stop_daemon_by_pid_file) finishes its own
    finally-block and removes the PID file. Otherwise the success message
    prints 'signal sent to pid None' which is useless to the operator."""
    from src import cli

    pid_file = tmp_path / "agent.pid"
    pid_file.write_text("88888\n", encoding="utf-8")

    monkeypatch.setattr(cli.config, "logs_dir", tmp_path)

    def stop_and_clear(pf):
        # Simulate the daemon's own finally racing ahead and removing the file
        # before cmd_stop gets a chance to read it.
        pf.unlink()
        return True

    monkeypatch.setattr(
        "src.runner.stop_daemon_by_pid_file", stop_and_clear, raising=True
    )

    rc = cli.cmd_stop()

    captured = capsys.readouterr()
    assert rc == 0
    assert "88888" in captured.out
    assert "None" not in captured.out


def test_cmd_run_returns_signal_exit_code_on_sigint(monkeypatch, tmp_path):
    """Plan 5a deferred minor item: cmd_run used to return 0 even when the
    daemon was interrupted by Ctrl-C, hiding the signal cause from any
    wrapping shell/CI. Now returns the conventional 128+signum (130 for SIGINT).

    Test isolation: redirect logs_dir to tmp_path and stub psutil.pid_exists
    so a real running daemon's PID file doesn't short-circuit cmd_run with
    'already running'."""
    import signal as _sig
    import threading

    from src import cli

    handle = MagicMock()
    stop_event = threading.Event()
    stop_event.signum = _sig.SIGINT  # type: ignore[attr-defined]
    stop_event.set()  # so wait() returns immediately

    monkeypatch.setattr(cli.config, "logs_dir", tmp_path)
    monkeypatch.setattr("psutil.pid_exists", lambda pid: False)
    monkeypatch.setattr(cli, "make_stop_event", lambda *sigs: stop_event)
    monkeypatch.setattr(
        "src.runner.start_daemon", lambda **_kw: handle, raising=True
    )
    monkeypatch.setattr("src.agent.llm.factory.get_llm_router", lambda: MagicMock())
    monkeypatch.setattr(cli, "run_startup_checks", lambda _cfg: [])

    rc = cli.cmd_run(dry_run=False, target=None)

    assert rc == 128 + _sig.SIGINT  # 130 on POSIX & Windows
    handle.stop.assert_called_once()


def test_cmd_run_calls_handle_stop_when_start_daemon_raises(monkeypatch, tmp_path):
    """If start_daemon raises (e.g. PID dir missing, replay parse error), the
    signal handler is already installed and we must not crash with
    AttributeError on a None handle in finally.

    Test isolation: same logs_dir + pid_exists pattern as the sibling tests
    so a real running daemon doesn't divert cmd_run before start_daemon
    is even called."""
    from src import cli

    def boom(**_kwargs):
        raise RuntimeError("simulated startup failure")

    monkeypatch.setattr(cli.config, "logs_dir", tmp_path)
    monkeypatch.setattr("psutil.pid_exists", lambda pid: False)
    monkeypatch.setattr("src.runner.start_daemon", boom, raising=True)
    monkeypatch.setattr("src.agent.llm.factory.get_llm_router", lambda: MagicMock())
    monkeypatch.setattr(cli, "run_startup_checks", lambda _cfg: [])
    monkeypatch.setattr(cli, "make_stop_event", lambda *sigs: MagicMock())

    with pytest.raises(RuntimeError, match="simulated startup failure"):
        cli.cmd_run(dry_run=False, target=None)


def test_cli_bootstrap_projects(tmp_path, capsys, monkeypatch):
    """Smoke-test the bootstrap-projects subcommand end-to-end."""
    from src.cli import main as cli_main

    tasks = tmp_path / "tasks"
    tasks.mkdir()
    templates = tasks / "templates"
    templates.mkdir()
    (templates / "project.md").write_text(
        '---\ntype: project\nslug: ""\nstatus: active\nrepo_path: ""\n'
        'priority: P1\ntags: []\nlast_touched: ""\n---\n# \n',
        encoding="utf-8",
    )

    root = tmp_path / "projects-root"
    root.mkdir()
    (root / "evernote").mkdir()
    (root / "alpha-project").mkdir()

    # Point config at our tmp_path tasks dir.
    from src.config import config
    monkeypatch.setattr(config, "tasks_dir", tasks)

    rc = cli_main(["bootstrap-projects", "--projects-root", str(root), "--skip", ""])
    assert rc == 0

    out = capsys.readouterr().out
    assert "evernote" in out
    assert "alpha-project" in out
    assert (tasks / "projects" / "evernote.md").exists()
