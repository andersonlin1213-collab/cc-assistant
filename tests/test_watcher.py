import time
from pathlib import Path

from src.dispatcher.watcher import FileWatcher


def _wait_for(predicate, timeout=3.0, interval=0.05):
    """Poll predicate until True or timeout. Returns True if predicate held."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_watcher_fires_on_md_create(tmp_path):
    """Creating a .md file in a column subfolder triggers the callback."""
    seen: list[Path] = []
    watcher = FileWatcher(
        tasks_dir=tmp_path,
        on_change=lambda p: seen.append(p),
        debounce_seconds=0.1,
    )
    watcher.start()
    try:
        target = tmp_path / "todo"
        target.mkdir()
        (target / "001.md").write_text("hello", encoding="utf-8")
        assert _wait_for(lambda: len(seen) >= 1), f"callback not fired, seen={seen}"
        assert any(p.name == "001.md" for p in seen)
    finally:
        watcher.stop()


def test_watcher_fires_on_md_modify(tmp_path):
    """Modifying an existing .md file in a column subfolder triggers the callback."""
    (tmp_path / "todo").mkdir()
    target = tmp_path / "todo" / "002.md"
    target.write_text("v1", encoding="utf-8")

    seen: list[Path] = []
    watcher = FileWatcher(
        tasks_dir=tmp_path,
        on_change=lambda p: seen.append(p),
        debounce_seconds=0.1,
    )
    watcher.start()
    try:
        time.sleep(0.05)  # let watcher settle
        target.write_text("v2", encoding="utf-8")
        assert _wait_for(lambda: len(seen) >= 1), f"callback not fired, seen={seen}"
    finally:
        watcher.stop()


def test_watcher_ignores_non_md(tmp_path):
    """Non-.md files are filtered out."""
    seen: list[Path] = []
    watcher = FileWatcher(
        tasks_dir=tmp_path,
        on_change=lambda p: seen.append(p),
        debounce_seconds=0.1,
    )
    watcher.start()
    try:
        (tmp_path / "ignore.txt").write_text("x", encoding="utf-8")
        (tmp_path / ".gitkeep").write_text("", encoding="utf-8")
        time.sleep(0.3)  # debounce window + buffer
        assert seen == [], f"non-md files leaked: {seen}"
    finally:
        watcher.stop()


def test_watcher_debounces_rapid_writes(tmp_path):
    """Multiple rapid writes within debounce window produce a single callback."""
    (tmp_path / "todo").mkdir()
    target = tmp_path / "todo" / "003.md"
    target.write_text("init", encoding="utf-8")

    seen: list[Path] = []
    watcher = FileWatcher(
        tasks_dir=tmp_path,
        on_change=lambda p: seen.append(p),
        debounce_seconds=0.3,
    )
    watcher.start()
    try:
        time.sleep(0.05)
        for i in range(5):
            target.write_text(f"v{i}", encoding="utf-8")
            time.sleep(0.02)
        # Before debounce expires, no fire yet (it may have fired once already from initial event flush;
        # after debounce, total should be small)
        time.sleep(0.5)  # allow debounce to settle
        assert len(seen) <= 2, f"debounce failed, got {len(seen)} fires"
        assert len(seen) >= 1, "no fire at all"
    finally:
        watcher.stop()


def test_watcher_suppress_self(tmp_path):
    """Writes inside `suppress_self()` block do not trigger the callback."""
    seen: list[Path] = []
    watcher = FileWatcher(
        tasks_dir=tmp_path,
        on_change=lambda p: seen.append(p),
        debounce_seconds=0.1,
    )
    (tmp_path / "todo").mkdir()
    watcher.start()
    try:
        time.sleep(0.05)
        with watcher.suppress_self():
            (tmp_path / "todo" / "agent.md").write_text("agent write", encoding="utf-8")
            time.sleep(0.3)  # let any in-flight events flush
        # After exiting, suppression buffer should still hold for debounce + small buffer
        time.sleep(0.7)
        assert seen == [], f"agent's own write leaked: {seen}"

        # Sanity: a fresh write (not suppressed) DOES fire
        (tmp_path / "todo" / "human.md").write_text("human write", encoding="utf-8")
        assert _wait_for(lambda: len(seen) >= 1, timeout=2.0)
    finally:
        watcher.stop()


def test_watcher_start_is_idempotent(tmp_path):
    """Calling start() twice does not leak a second observer thread."""
    seen: list[Path] = []
    watcher = FileWatcher(
        tasks_dir=tmp_path,
        on_change=lambda p: seen.append(p),
        debounce_seconds=0.1,
    )
    (tmp_path / "todo").mkdir()
    watcher.start()
    first_observer = watcher._observer
    watcher.start()  # should be no-op
    assert watcher._observer is first_observer, "second start() created a new observer"
    try:
        time.sleep(0.05)
        (tmp_path / "todo" / "x.md").write_text("hi", encoding="utf-8")
        assert _wait_for(lambda: len(seen) >= 1, timeout=2.0)
        # Verify only one fire (no duplicate observers)
        time.sleep(0.5)
        assert len(seen) == 1, f"expected exactly 1 callback, got {len(seen)}: {seen}"
    finally:
        watcher.stop()


def test_watcher_handles_rename(tmp_path):
    """Renaming a .md file within the watched tree fires the callback for the new path."""
    (tmp_path / "todo").mkdir()
    src = tmp_path / "todo" / "old.md"
    src.write_text("body", encoding="utf-8")

    seen: list[Path] = []
    watcher = FileWatcher(
        tasks_dir=tmp_path,
        on_change=lambda p: seen.append(p),
        debounce_seconds=0.1,
    )
    watcher.start()
    try:
        time.sleep(0.1)
        seen.clear()  # discard any startup noise from the existing file
        dst = tmp_path / "todo" / "new.md"
        src.rename(dst)
        assert _wait_for(lambda: any(p.name == "new.md" for p in seen), timeout=3.0), (
            f"rename did not surface dest path. seen={seen}"
        )
    finally:
        watcher.stop()


def test_watcher_ignores_obsidian_internal_files(tmp_path):
    """Files inside .obsidian/, _attachments/, .trash/, templates/, and
    Obsidian Sync conflict files must not trigger the callback."""
    from src.dispatcher.watcher import FileWatcher

    seen: list[Path] = []
    w = FileWatcher(tmp_path, on_change=lambda p: seen.append(p), debounce_seconds=0.1)
    w.start()
    try:
        for col in ("doing", ".obsidian", "_attachments", ".trash", "templates"):
            (tmp_path / col).mkdir(parents=True, exist_ok=True)
        # legitimate edit
        (tmp_path / "doing" / "025.md").write_text("a", encoding="utf-8")
        # noise edits — should be ignored
        (tmp_path / ".obsidian" / "workspace.json").write_text("a", encoding="utf-8")
        (tmp_path / "_attachments" / "img.png").write_text("a", encoding="utf-8")
        (tmp_path / ".trash" / "old.md").write_text("a", encoding="utf-8")
        (tmp_path / "templates" / "default.md").write_text("a", encoding="utf-8")
        # Obsidian Sync conflict file
        (tmp_path / "doing" / "025 (conflict 2026-04-27 12:00).md").write_text(
            "a", encoding="utf-8"
        )

        time.sleep(0.5)
    finally:
        w.stop()

    seen_names = [p.name for p in seen]
    assert "025.md" in seen_names
    # Everything else must be filtered out
    for noise in (
        "workspace.json", "img.png", "old.md", "default.md",
        "025 (conflict 2026-04-27 12:00).md",
    ):
        assert noise not in seen_names, f"watcher should ignore {noise}"


def test_projects_direct_child_card_passes(tmp_path):
    """tasks/projects/<slug>.md must pass through — those events go to
    project_handler (not orchestrator). Sub-subfolders still ignored."""
    from src.dispatcher.watcher import _is_ignored

    p = tmp_path / "tasks" / "projects" / "evernote.md"
    assert _is_ignored(p) is False

    # Sub-subfolder under projects/ is ignored (not a project card)
    sub = tmp_path / "tasks" / "projects" / "drafts" / "wip.md"
    assert _is_ignored(sub) is True


def test_vault_root_md_is_ignored(tmp_path):
    """Files at the vault root (tasks/foo.md) are NOT tasks.

    Mobile Obsidian defaults to creating notes at vault root. Without
    this filter, the daemon would process every such file, fail to parse
    (no frontmatter), and spam `task_malformed` log entries on every
    save. Tasks live exclusively under column subfolders.
    """
    from src.dispatcher.watcher import _is_ignored

    # Vault-root files: README, drafts, scratch
    assert _is_ignored(tmp_path / "tasks" / "README.md") is True
    assert _is_ignored(tmp_path / "tasks" / "测试.md") is True
    assert _is_ignored(tmp_path / "tasks" / "untitled.md") is True


def test_column_subfolder_files_are_not_ignored(tmp_path):
    """Files inside backlog/todo/doing/blocked/review must still pass."""
    from src.dispatcher.watcher import _is_ignored

    for col in ("backlog", "todo", "doing", "blocked", "review"):
        p = tmp_path / "tasks" / col / "001.md"
        assert _is_ignored(p) is False, f"column {col} should not be ignored"


def test_done_monthly_subfolder_files_are_not_ignored(tmp_path):
    """done/ has YYYY-MM subdirs — those .md files must still pass."""
    from src.dispatcher.watcher import _is_ignored

    p = tmp_path / "tasks" / "done" / "2026-04" / "025.md"
    assert _is_ignored(p) is False
