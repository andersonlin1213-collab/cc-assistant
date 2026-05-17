from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import Optional

from src.config import config
from src.lifecycle import is_pid_alive, make_stop_event, read_pid


def build_parser() -> argparse.ArgumentParser:
    """Build the cc-assistant CLI argparse parser."""
    parser = argparse.ArgumentParser(
        prog="cc-assistant",
        description="Local AI Task Automation Agent — kanban-driven daemon.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Start the agent daemon (foreground).")
    p_run.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate one cycle (or all active tasks) without writing or committing.",
    )
    p_run.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Path to a single task file (used with --dry-run). Default: all active tasks.",
    )

    sub.add_parser("stop", help="Send SIGTERM to the running agent (reads logs/agent.pid).")
    sub.add_parser("status", help="Print agent status: PID, active task counts, recent log lines.")

    p_boot = sub.add_parser(
        "bootstrap-projects",
        help="Scaffold project cards under tasks/projects/ for each sibling project folder.",
    )
    p_boot.add_argument(
        "--projects-root",
        default=None,
        help="Parent dir containing project folders. Default: parent of cc-assistant repo.",
    )
    p_boot.add_argument(
        "--skip",
        default="cc-assistant-vault",
        help="Slug to skip (the vault's own project). Default: cc-assistant-vault.",
    )

    return parser


def run_startup_checks(cfg) -> list[str]:
    """Return a list of human-readable warnings; empty if all OK.

    Plan 5b: ensure (a) the Obsidian vault is initialized at tasks/.obsidian/,
    and (b) the Obsidian desktop process is running so Sync can land bytes.
    Both checks are warnings, not failures — the daemon is allowed to start
    without Obsidian (e.g. for dry-run or headless testing).
    """
    warnings: list[str] = []
    vault_marker = cfg.tasks_dir / ".obsidian"
    if not vault_marker.exists():
        warnings.append(
            "Vault not initialized: open `tasks/` in Obsidian once to create "
            ".obsidian/ before relying on Sync."
        )
    if cfg.obsidian_check_process:
        try:
            import psutil
            running = any(
                "obsidian" in (p.info.get("name") or "").lower()
                for p in psutil.process_iter(["name"])
            )
            if not running:
                warnings.append(
                    "Obsidian desktop process not detected; Obsidian Sync "
                    "cannot land changes on disk while the app is closed."
                )
        except Exception:
            # psutil failures should not block startup
            pass
    return warnings


def cmd_run(dry_run: bool, target: Optional[str]) -> int:
    from src.agent.llm.factory import get_llm_router

    # Pass the router as `llm`; Orchestrator's __init__ detects LLMRouter
    # vs plain LLMClient and unpacks accordingly.
    llm = get_llm_router()
    pid_file = config.logs_dir / "agent.pid"

    if dry_run:
        from src.runner import run_one_dry_cycle

        target_path = Path(target) if target else None
        asyncio.run(run_one_dry_cycle(
            tasks_dir=config.tasks_dir,
            skills_dir=config.skills_dir,
            logs_dir=config.logs_dir,
            llm=llm,
            target_path=target_path,
        ))
        print("dry-run complete (see logs/agent.jsonl for details)")
        return 0

    from src.runner import start_daemon
    from src.lifecycle import remove_pid

    # Refuse to start a second daemon on the same tasks_dir. A live PID file
    # whose process still exists means another `cc-assistant run` is already
    # the watcher/scheduler owner; without this guard the second invocation
    # silently clobbers the PID file and produces two coordinators on the
    # same kanban directory. Plan 5a deferred review issue #3.
    existing_pid = read_pid(pid_file)
    if existing_pid is not None:
        import psutil
        if psutil.pid_exists(existing_pid):
            print(
                f"cc-assistant already running (pid={existing_pid}). "
                f"Use `cc-assistant stop` first.",
                file=sys.stderr,
            )
            return 1
        # Stale PID — process is gone. Clean up and proceed.
        remove_pid(pid_file)

    for w in run_startup_checks(config):
        print(f"[warn] {w}", file=sys.stderr)

    # Install signal handlers BEFORE start_daemon so that a Ctrl-C arriving
    # mid-startup (between PID write, replay scan, and watcher start) sets
    # the event instead of raising KeyboardInterrupt past our try/finally.
    # Plan 5a deferred review issue #1.
    stop_event = make_stop_event()

    handle = None
    try:
        handle = start_daemon(
            tasks_dir=config.tasks_dir,
            skills_dir=config.skills_dir,
            logs_dir=config.logs_dir,
            llm=llm,
            pid_file=pid_file,
        )
        print(f"cc-assistant running (pid={os.getpid()}). Ctrl-C to stop.")
        stop_event.wait()
    finally:
        if handle is not None:
            handle.stop()

    print("cc-assistant stopped.")
    # Convention: exit 128+signum when a signal woke the wait, 0 otherwise.
    # Plan 5a deferred review minor item.
    signum = getattr(stop_event, "signum", None)
    if isinstance(signum, int):
        return 128 + signum
    return 0


def cmd_stop() -> int:
    from src.runner import stop_daemon_by_pid_file

    pid_file = config.logs_dir / "agent.pid"
    # Read the PID BEFORE signaling: the daemon's own finally-block calls
    # remove_pid as part of shutdown, which can race ahead of us reading
    # the file and produce "signal sent to pid None" in the success message.
    # Plan 5a deferred review issue #2.
    pid = read_pid(pid_file)
    if stop_daemon_by_pid_file(pid_file):
        print(f"signal sent to pid {pid}")
        return 0
    print("no running daemon found")
    return 1


def cmd_status(
    pid_file: Path,
    tasks_dir: Path,
    logs_dir: Path,
) -> int:
    pid = read_pid(pid_file)
    if pid is None:
        print("cc-assistant: not running (no PID file)")
        return 0

    if not is_pid_alive(pid):
        print(f"cc-assistant: stale PID file at {pid_file} (pid {pid} not running)")
        return 0

    print(f"cc-assistant: running (pid={pid})")
    print()
    print("Active tasks by column:")
    column_names = ["backlog", "todo", "doing", "blocked", "review"]
    for name in column_names:
        d = tasks_dir / name
        count = sum(1 for _ in d.glob("*.md")) if d.exists() else 0
        print(f"  {name:<10} {count}")

    # Recent system log lines
    agent_log = logs_dir / "agent.jsonl"
    if agent_log.exists():
        print()
        print("Recent agent log:")
        lines = agent_log.read_text(encoding="utf-8").strip().split("\n")
        for line in lines[-10:]:
            print(f"  {line}")

    return 0


def cmd_bootstrap_projects(projects_root: Optional[str], skip_slug: Optional[str]) -> int:
    """Implement the `bootstrap-projects` CLI command."""
    from src.board.bootstrap import bootstrap_projects

    if projects_root is not None:
        root = Path(projects_root).resolve()
    else:
        # Default: the parent of the cc-assistant repo (which is config.tasks_dir's
        # grandparent). Layout: <projects-root>/cc-assitant/tasks/.
        root = config.tasks_dir.resolve().parent.parent

    skip = skip_slug if skip_slug not in (None, "") else None

    try:
        result = bootstrap_projects(
            tasks_dir=config.tasks_dir,
            projects_root=root,
            skip_slug=skip,
        )
    except FileNotFoundError as e:
        print(f"bootstrap-projects: {e}", file=sys.stderr)
        return 1

    if result.created:
        print(f"created {len(result.created)} project card(s):")
        for slug in result.created:
            print(f"  + {slug}")
    if result.skipped_existing:
        print(f"skipped {len(result.skipped_existing)} existing card(s):")
        for slug in result.skipped_existing:
            print(f"  = {slug}")
    if not result.created and not result.skipped_existing:
        print("no project folders found under", root)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        return cmd_run(dry_run=args.dry_run, target=args.target)
    if args.command == "stop":
        return cmd_stop()
    if args.command == "status":
        return cmd_status(
            pid_file=config.logs_dir / "agent.pid",
            tasks_dir=config.tasks_dir,
            logs_dir=config.logs_dir,
        )
    if args.command == "bootstrap-projects":
        return cmd_bootstrap_projects(
            projects_root=args.projects_root,
            skip_slug=args.skip,
        )
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
