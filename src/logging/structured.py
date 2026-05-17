from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from src.models import LogEntry


def rotate_old_logs(logs_dir: Path, retention_days: int = 31) -> int:
    """Move stale `*.jsonl` files from `logs_dir` into a per-month archive.

    A log file is "stale" if its mtime is older than `retention_days` ago.
    Each stale file moves to `logs/archive/<YYYY-MM>/<filename>` where
    `<YYYY-MM>` reflects the file's mtime month — so a 2026-04 task's log
    lands in `archive/2026-04/`, regardless of when this rotation ran.

    Returns the number of files moved.

    Behavior:
      - Active tasks (recent mtime) stay put — their full history is one
        `cat logs/<id>.jsonl` away while they're in flight.
      - Closed tasks (last write was N days ago) get archived; the per-
        task file is still recoverable from `archive/<month>/`.
      - `agent.jsonl` follows the same rule: if no system events landed
        for a full retention window, it rotates. In normal operation it
        keeps appending and never moves.
      - Idempotent: collisions (same filename already in the destination
        bucket from a prior rotation) are skipped with a stderr note,
        leaving the source in place. Caller can investigate the duplicate.

    No size-based rotation. At current scale (sub-MB after weeks of
    dogfood) it would be overkill; revisit if total `logs/` ever crosses
    something like 100MB.
    """
    if not logs_dir.exists():
        return 0
    cutoff = datetime.now() - timedelta(days=retention_days)
    archive_root = logs_dir / "archive"
    moved = 0
    for f in sorted(logs_dir.glob("*.jsonl")):
        if not f.is_file():
            continue
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if mtime >= cutoff:
            continue
        bucket = archive_root / mtime.strftime("%Y-%m")
        bucket.mkdir(parents=True, exist_ok=True)
        dest = bucket / f.name
        if dest.exists():
            print(
                f"[rotate_old_logs] skip {f.name}: {dest} already exists",
                file=sys.stderr,
            )
            continue
        f.rename(dest)
        moved += 1
    return moved


class StructuredLogger:
    """Writes structured JSONL log files — one per task, plus a global system log."""

    def __init__(self, logs_dir: Path) -> None:
        self.logs_dir = logs_dir
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def log(self, entry: LogEntry) -> None:
        """Append a log entry to the task-specific JSONL file."""
        path = self.logs_dir / f"{entry.task_id}.jsonl"
        self._append(path, entry)

    def log_system(self, action: str, detail: str, **kwargs: object) -> None:
        """Log a system-level event to agent.jsonl."""
        entry = LogEntry(task_id="_system", action=action, detail=detail, **kwargs)
        path = self.logs_dir / "agent.jsonl"
        self._append(path, entry)

    def get_task_logs(self, task_id: str) -> list[dict]:
        """Read all log entries for a given task."""
        path = self.logs_dir / f"{task_id}.jsonl"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        return [json.loads(line) for line in lines if line.strip()]

    def _append(self, path: Path, entry: LogEntry) -> None:
        data = entry.model_dump(mode="json")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
