from pathlib import Path

import pytest

from src.board.bootstrap import BootstrapResult, bootstrap_projects
from src.board.project_parser import parse_project_file


def _make_template(tasks_dir: Path) -> Path:
    templates = tasks_dir / "templates"
    templates.mkdir(parents=True, exist_ok=True)
    template = templates / "project.md"
    template.write_text(
        "---\n"
        "type: project\n"
        'slug: ""\n'
        "status: active\n"
        'repo_path: ""\n'
        "priority: P1\n"
        "tags: []\n"
        'last_touched: ""\n'
        "---\n"
        "# \n\n"
        "## 一句話\n\n",
        encoding="utf-8",
    )
    return template


def _setup_projects_root(tmp_path: Path, names: list[str]) -> Path:
    root = tmp_path / "projects-root"
    root.mkdir()
    for n in names:
        (root / n).mkdir()
    return root


def test_bootstrap_creates_stub_for_each_folder(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    _make_template(tasks)
    root = _setup_projects_root(tmp_path, ["evernote", "alpha-project", "connect-nas"])

    # Skip current project — pretend cc-assitant is the current project.
    result = bootstrap_projects(
        tasks_dir=tasks,
        projects_root=root,
        skip_slug="cc-assitant",
    )

    assert isinstance(result, BootstrapResult)
    assert sorted(result.created) == ["connect-nas", "evernote", "alpha-project"]
    assert result.skipped_existing == []

    proj_dir = tasks / "projects"
    assert (proj_dir / "evernote.md").exists()
    assert (proj_dir / "alpha-project.md").exists()


def test_bootstrap_fills_slug_and_repo_path(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    _make_template(tasks)
    root = _setup_projects_root(tmp_path, ["evernote"])

    bootstrap_projects(tasks_dir=tasks, projects_root=root, skip_slug="cc-assitant")

    project = parse_project_file(tasks / "projects" / "evernote.md")
    assert project.slug == "evernote"
    assert project.repo_path is not None
    assert project.repo_path.endswith("evernote") or "evernote" in project.repo_path


def test_bootstrap_does_not_overwrite_existing(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    _make_template(tasks)
    proj_dir = tasks / "projects"
    proj_dir.mkdir()
    existing = proj_dir / "evernote.md"
    existing.write_text(
        "---\ntype: project\nslug: evernote\nstatus: paused\n---\n# evernote\n手動寫的內容\n",
        encoding="utf-8",
    )
    root = _setup_projects_root(tmp_path, ["evernote", "alpha-project"])

    result = bootstrap_projects(tasks_dir=tasks, projects_root=root, skip_slug="cc-assitant")

    assert result.created == ["alpha-project"]
    assert result.skipped_existing == ["evernote"]
    # Existing file untouched.
    assert "手動寫的內容" in existing.read_text(encoding="utf-8")


def test_bootstrap_skips_skip_slug(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    _make_template(tasks)
    root = _setup_projects_root(tmp_path, ["cc-assitant", "evernote"])

    result = bootstrap_projects(tasks_dir=tasks, projects_root=root, skip_slug="cc-assitant")

    assert result.created == ["evernote"]
    assert "cc-assitant" not in result.created
    assert not (tasks / "projects" / "cc-assitant.md").exists()


def test_bootstrap_creates_projects_dir_if_missing(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    _make_template(tasks)
    root = _setup_projects_root(tmp_path, ["evernote"])
    assert not (tasks / "projects").exists()

    bootstrap_projects(tasks_dir=tasks, projects_root=root, skip_slug=None)

    assert (tasks / "projects").is_dir()


def test_bootstrap_raises_when_root_missing(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    _make_template(tasks)
    missing_root = tmp_path / "does-not-exist"

    with pytest.raises(FileNotFoundError):
        bootstrap_projects(tasks_dir=tasks, projects_root=missing_root, skip_slug=None)


def test_bootstrap_raises_when_template_missing(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    # NO template created
    root = _setup_projects_root(tmp_path, ["evernote"])

    with pytest.raises(FileNotFoundError):
        bootstrap_projects(tasks_dir=tasks, projects_root=root, skip_slug=None)


def test_bootstrap_ignores_dotfiles_and_files(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    _make_template(tasks)
    root = tmp_path / "projects-root"
    root.mkdir()
    (root / "evernote").mkdir()
    (root / ".git").mkdir()
    (root / "README.md").write_text("hi", encoding="utf-8")

    result = bootstrap_projects(tasks_dir=tasks, projects_root=root, skip_slug=None)

    assert result.created == ["evernote"]


def test_bootstrap_raises_when_template_slot_missing(tmp_path):
    """If the template lacks one of the expected slots, fail loudly."""
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    templates = tasks / "templates"
    templates.mkdir()
    # This template has slug, but no repo_path slot.
    (templates / "project.md").write_text(
        '---\ntype: project\nslug: ""\nstatus: active\n'
        'priority: P1\ntags: []\nlast_touched: ""\n---\n# \n',
        encoding="utf-8",
    )
    root = tmp_path / "projects-root"
    root.mkdir()
    (root / "evernote").mkdir()

    with pytest.raises(ValueError, match="repo_path"):
        bootstrap_projects(tasks_dir=tasks, projects_root=root, skip_slug=None)
