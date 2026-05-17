import json
from src.logging.structured import StructuredLogger
from src.models import LogEntry


def test_log_creates_file(tmp_path):
    logger = StructuredLogger(tmp_path)
    entry = LogEntry(
        task_id="001",
        action="test_action",
        detail="testing",
        duration_ms=100,
        status="success",
    )
    logger.log(entry)

    log_file = tmp_path / "001.jsonl"
    assert log_file.exists()
    line = log_file.read_text(encoding="utf-8").strip()
    data = json.loads(line)
    assert data["task_id"] == "001"
    assert data["action"] == "test_action"


def test_log_appends_multiple(tmp_path):
    logger = StructuredLogger(tmp_path)
    for i in range(3):
        entry = LogEntry(
            task_id="001", action=f"step_{i}", detail=f"step {i}", status="success"
        )
        logger.log(entry)

    lines = (tmp_path / "001.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3


def test_log_system_event(tmp_path):
    logger = StructuredLogger(tmp_path)
    logger.log_system("startup", "Agent started")

    log_file = tmp_path / "agent.jsonl"
    assert log_file.exists()
    data = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert data["action"] == "startup"
    assert data["task_id"] == "_system"


def test_get_task_logs(tmp_path):
    logger = StructuredLogger(tmp_path)
    for i in range(3):
        logger.log(
            LogEntry(
                task_id="002", action=f"step_{i}", detail=f"d{i}", status="success"
            )
        )

    logs = logger.get_task_logs("002")
    assert len(logs) == 3
    assert logs[0]["action"] == "step_0"


# ------------------------------------------------------------------ #
# rotate_old_logs                                                     #
# ------------------------------------------------------------------ #


def test_rotate_old_logs_moves_files_older_than_retention(tmp_path):
    """A file whose mtime is older than retention_days is moved into
    logs/archive/<YYYY-MM>/ based on the file's mtime month."""
    import os
    from datetime import datetime, timedelta
    from src.logging.structured import rotate_old_logs

    old = tmp_path / "001.jsonl"
    old.write_text('{"task_id": "001"}\n', encoding="utf-8")
    # Backdate to 60 days ago — month-bucket comes from this mtime.
    old_mtime = datetime.now() - timedelta(days=60)
    os.utime(old, (old_mtime.timestamp(), old_mtime.timestamp()))

    moved = rotate_old_logs(tmp_path, retention_days=31)
    assert moved == 1
    assert not old.exists()
    bucket = tmp_path / "archive" / old_mtime.strftime("%Y-%m")
    assert (bucket / "001.jsonl").exists()


def test_rotate_old_logs_leaves_recent_files(tmp_path):
    """Active task logs (mtime within retention window) stay where they
    are — moving them mid-task would orphan the in-flight history."""
    from src.logging.structured import rotate_old_logs

    fresh = tmp_path / "002.jsonl"
    fresh.write_text('{"task_id": "002"}\n', encoding="utf-8")

    moved = rotate_old_logs(tmp_path, retention_days=31)
    assert moved == 0
    assert fresh.exists()
    assert not (tmp_path / "archive").exists()


def test_rotate_old_logs_skips_collisions(tmp_path, capsys):
    """If the destination filename already exists in the archive bucket
    (rotation ran twice in the same month, or task id was reused), the
    source is left in place and a stderr note is printed. No silent
    overwrite — the duplicate is something the operator should look at."""
    import os
    from datetime import datetime, timedelta
    from src.logging.structured import rotate_old_logs

    old = tmp_path / "003.jsonl"
    old.write_text("v2\n", encoding="utf-8")
    old_mtime = datetime.now() - timedelta(days=60)
    os.utime(old, (old_mtime.timestamp(), old_mtime.timestamp()))

    bucket = tmp_path / "archive" / old_mtime.strftime("%Y-%m")
    bucket.mkdir(parents=True)
    pre_existing = bucket / "003.jsonl"
    pre_existing.write_text("v1\n", encoding="utf-8")

    moved = rotate_old_logs(tmp_path, retention_days=31)
    assert moved == 0
    assert old.exists()  # source preserved
    assert pre_existing.read_text(encoding="utf-8") == "v1\n"  # not clobbered
    captured = capsys.readouterr()
    assert "skip 003.jsonl" in captured.err


def test_rotate_old_logs_handles_missing_dir(tmp_path):
    """A logs_dir that doesn't exist yet is a no-op (returns 0). Lets
    start_daemon call rotate_old_logs unconditionally without first
    creating the directory."""
    from src.logging.structured import rotate_old_logs
    moved = rotate_old_logs(tmp_path / "nonexistent", retention_days=31)
    assert moved == 0
