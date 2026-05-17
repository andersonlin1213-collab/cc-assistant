"""Smoke test that verifies the cc-assistant entry point is wired correctly."""

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_cli_help_runs():
    """`uv run cc-assistant --help` exits 0 and prints subcommand names."""
    result = subprocess.run(
        ["uv", "run", "cc-assistant", "--help"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "run" in result.stdout
    assert "stop" in result.stdout
    assert "status" in result.stdout


def test_cli_status_runs_without_error():
    """`uv run cc-assistant status` exits 0 even when no daemon is running."""
    result = subprocess.run(
        ["uv", "run", "cc-assistant", "status"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "cc-assistant" in result.stdout.lower()
