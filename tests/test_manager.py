from datetime import datetime
from pathlib import Path
from src.board.manager import BoardManager
from src.models import TaskIntent, TaskStatus


ALL_STATUSES = ["backlog", "todo", "doing", "blocked", "review", "done"]


def _setup_dirs(base: Path) -> dict[str, Path]:
    dirs = {}
    for status in ALL_STATUSES:
        d = base / "tasks" / status
        d.mkdir(parents=True, exist_ok=True)
        dirs[status] = d
    return dirs


def _create_task_file(directory: Path, filename: str, task_id: str = "001") -> Path:
    path = directory / filename
    path.write_text(
        f'---\nid: "{task_id}"\ntitle: Test\nproject: ""\nparent: null\n'
        f"priority: P1\ntags: []\n"
        f"created: 2026-04-26 14:00\nupdated: 2026-04-26 14:00\n"
        f'auto_approve: true\ndepends_on: []\ninstructions: ""\nsubtasks: []\n---\n\n'
        f"## 任务描述\nTest.\n\n## 对话\n",
        encoding="utf-8",
    )
    return path


def test_move_task_todo_to_doing(tmp_path):
    dirs = _setup_dirs(tmp_path)
    src = _create_task_file(dirs["todo"], "001-test.md")
    manager = BoardManager(tmp_path / "tasks")

    new_path = manager.move_task(src, TaskStatus.DOING)

    assert not src.exists()
    assert new_path.exists()
    assert new_path.parent.name == "doing"


def test_move_to_review(tmp_path):
    dirs = _setup_dirs(tmp_path)
    src = _create_task_file(dirs["doing"], "001-test.md")
    manager = BoardManager(tmp_path / "tasks")

    new_path = manager.move_task(src, TaskStatus.REVIEW)
    assert new_path.parent.name == "review"
    assert new_path.exists()


def test_move_to_backlog(tmp_path):
    dirs = _setup_dirs(tmp_path)
    src = _create_task_file(dirs["todo"], "001-test.md")
    manager = BoardManager(tmp_path / "tasks")

    new_path = manager.move_task(src, TaskStatus.BACKLOG)
    assert new_path.parent.name == "backlog"
    assert new_path.exists()


def test_move_to_done_archives_by_month(tmp_path):
    dirs = _setup_dirs(tmp_path)
    src = _create_task_file(dirs["review"], "001-test.md")
    manager = BoardManager(tmp_path / "tasks")

    new_path = manager.move_task(src, TaskStatus.DONE)

    today = datetime.now()
    expected_dir = dirs["done"] / today.strftime("%Y-%m")
    assert new_path.parent == expected_dir
    assert new_path.exists()


def test_list_tasks_in_status(tmp_path):
    dirs = _setup_dirs(tmp_path)
    _create_task_file(dirs["todo"], "001-task-a.md", "001")
    _create_task_file(dirs["todo"], "002-task-b.md", "002")
    _create_task_file(dirs["review"], "003-task-c.md", "003")

    manager = BoardManager(tmp_path / "tasks")

    todo_files = manager.list_tasks(TaskStatus.TODO)
    assert len(todo_files) == 2

    review_files = manager.list_tasks(TaskStatus.REVIEW)
    assert len(review_files) == 1


def test_list_active_tasks_excludes_backlog_and_done(tmp_path):
    """Active = todo + doing + blocked + review (not backlog, not done)."""
    dirs = _setup_dirs(tmp_path)
    _create_task_file(dirs["backlog"], "001-a.md", "001")
    _create_task_file(dirs["todo"], "002-b.md", "002")
    _create_task_file(dirs["doing"], "003-c.md", "003")
    _create_task_file(dirs["blocked"], "004-d.md", "004")
    _create_task_file(dirs["review"], "005-e.md", "005")
    _create_task_file(dirs["done"], "006-f.md", "006")

    manager = BoardManager(tmp_path / "tasks")
    active = manager.list_active_tasks()

    # backlog (not yet ready) and done (archived) excluded
    assert len(active) == 4


def test_target_for_intent_resume_from_blocked():
    assert BoardManager.target_status_for_intent(
        TaskIntent.RESUME, TaskStatus.BLOCKED
    ) == TaskStatus.DOING


def test_target_for_intent_approve_from_review():
    assert BoardManager.target_status_for_intent(
        TaskIntent.APPROVE, TaskStatus.REVIEW
    ) == TaskStatus.DONE


def test_target_for_intent_reject_from_review():
    assert BoardManager.target_status_for_intent(
        TaskIntent.REJECT, TaskStatus.REVIEW
    ) == TaskStatus.TODO


def test_target_for_intent_pause_from_doing():
    assert BoardManager.target_status_for_intent(
        TaskIntent.PAUSE, TaskStatus.DOING
    ) == TaskStatus.BACKLOG


def test_target_for_intent_invalid_combo_returns_none():
    # resume from todo is meaningless
    assert BoardManager.target_status_for_intent(
        TaskIntent.RESUME, TaskStatus.TODO
    ) is None


from src.models import Project, ProjectStatus


def _create_project_file(directory: Path, slug: str, status: str = "active") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{slug}.md"
    path.write_text(
        f"---\ntype: project\nslug: {slug}\nstatus: {status}\n---\n# {slug}\n",
        encoding="utf-8",
    )
    return path


def test_get_project_returns_project_when_present(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    _create_project_file(tasks / "projects", "evernote", status="paused")

    manager = BoardManager(tasks)
    p = manager.get_project("evernote")

    assert p is not None
    assert p.slug == "evernote"
    assert p.status == ProjectStatus.PAUSED


def test_get_project_returns_none_when_missing(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    manager = BoardManager(tasks)

    assert manager.get_project("nonexistent") is None


def test_get_project_returns_none_when_projects_dir_missing(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()  # No projects/ subdir created.
    manager = BoardManager(tasks)

    assert manager.get_project("any") is None


def test_get_project_returns_none_for_malformed_card(tmp_path):
    """Malformed project cards are skipped silently — same policy as malformed tasks."""
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    proj_dir = tasks / "projects"
    proj_dir.mkdir()
    (proj_dir / "broken.md").write_text("no frontmatter at all\n", encoding="utf-8")

    manager = BoardManager(tasks)
    assert manager.get_project("broken") is None


def test_list_projects(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    _create_project_file(tasks / "projects", "evernote", status="active")
    _create_project_file(tasks / "projects", "alpha-project", status="paused")
    # A malformed card is silently skipped.
    (tasks / "projects" / "broken.md").write_text("nope", encoding="utf-8")

    manager = BoardManager(tasks)
    projects = manager.list_projects()

    slugs = sorted(p.slug for p in projects)
    assert slugs == ["evernote", "alpha-project"]


def test_list_projects_when_dir_missing(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    manager = BoardManager(tasks)
    assert manager.list_projects() == []


def test_get_project_logs_warning_on_malformed(tmp_path, caplog):
    """Malformed project cards emit a warning log so the user sees feedback."""
    import logging

    tasks = tmp_path / "tasks"
    tasks.mkdir()
    proj_dir = tasks / "projects"
    proj_dir.mkdir()
    (proj_dir / "broken.md").write_text("nope no frontmatter\n", encoding="utf-8")

    manager = BoardManager(tasks)
    with caplog.at_level(logging.WARNING, logger="src.board.manager"):
        result = manager.get_project("broken")

    assert result is None
    assert any("malformed" in r.message for r in caplog.records)
    assert any("broken.md" in r.message for r in caplog.records)


def test_list_projects_logs_warning_on_malformed(tmp_path, caplog):
    import logging

    tasks = tmp_path / "tasks"
    tasks.mkdir()
    proj_dir = tasks / "projects"
    proj_dir.mkdir()
    _create_project_file(proj_dir, "evernote", status="active")
    (proj_dir / "broken.md").write_text("nope", encoding="utf-8")

    manager = BoardManager(tasks)
    with caplog.at_level(logging.WARNING, logger="src.board.manager"):
        projects = manager.list_projects()

    assert [p.slug for p in projects] == ["evernote"]
    assert any("malformed" in r.message for r in caplog.records)
