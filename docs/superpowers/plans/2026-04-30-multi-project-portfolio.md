# Multi-Project Portfolio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add project-level cards to the existing Obsidian vault so the cc-assistant can manage 14 projects from one place, including a `status: paused` switch that stops the orchestrator from advancing that project's tasks.

**Architecture:** New `tasks/projects/<slug>.md` cards parsed by a dedicated `Project` parser (separate from the task parser). The `Task` model already has a `project: str` field; the orchestrator gains a pre-cycle filter that reads the corresponding project card and skips the task if `status != active` (unless the task is already in `doing/`). A `bootstrap-projects` CLI subcommand scaffolds stub cards for sibling project folders. Watcher ignores `projects/` so project edits don't trigger a task cycle.

**Tech Stack:** Python 3.13, Pydantic v2, `python-frontmatter`, watchdog, pytest, argparse.

**Spec:** `docs/superpowers/specs/2026-04-30-multi-project-portfolio-design.md`

---

## File Plan

**New files:**
- `src/board/project_parser.py` — parses `tasks/projects/<slug>.md` into `Project` model.
- `src/board/bootstrap.py` — bootstrap logic for `cc-assistant bootstrap-projects`.
- `tasks/templates/project.md` — Obsidian template for new project cards.
- `tasks/projects.base` — Obsidian Base view grouped by status.
- `tests/test_project_parser.py` — unit tests for project parser.
- `tests/test_bootstrap.py` — unit tests for bootstrap logic.

**Modified files:**
- `src/models.py` — add `ProjectStatus` enum + `Project` model.
- `src/board/manager.py` — add `get_project(slug)` and `list_projects()`.
- `src/agent/orchestrator.py` — add `_skip_for_paused_project()` filter; hook into `run_cycle` and `on_poll`.
- `src/dispatcher/watcher.py` — add `/projects/` to `_IGNORE_PATH_FRAGMENTS`.
- `src/cli.py` — add `bootstrap-projects` subcommand.
- `tasks/views.base` — exclude `projects/` folder from task views.
- `tests/test_models.py` — add tests for new types.
- `tests/test_manager.py` — add tests for project lookup.
- `tests/test_orchestrator.py` — add tests for paused-project filter.
- `tests/test_watcher.py` — add test for projects/ ignore.

---

## Task 1: ProjectStatus enum + Project model

**Files:**
- Modify: `src/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1.1: Write the failing test**

Add to `tests/test_models.py`:

```python
from datetime import datetime
from src.models import Project, ProjectStatus


def test_project_status_values():
    assert ProjectStatus.ACTIVE.value == "active"
    assert ProjectStatus.PAUSED.value == "paused"
    assert ProjectStatus.ARCHIVED.value == "archived"


def test_project_minimal():
    p = Project(slug="evernote")
    assert p.slug == "evernote"
    assert p.status == ProjectStatus.ACTIVE
    assert p.priority is None
    assert p.repo_path is None
    assert p.tags == []
    assert p.last_touched is None
    assert p.title == ""
    assert p.body == ""
    assert p.source_path is None


def test_project_full():
    p = Project(
        slug="evernote",
        status=ProjectStatus.PAUSED,
        repo_path="../../evernote",
        priority="P1",
        tags=["migration", "knowledge"],
        last_touched=datetime(2026, 4, 30),
        title="evernote",
        body="## 一句話\n...",
    )
    assert p.status == ProjectStatus.PAUSED
    assert p.priority == "P1"
    assert p.tags == ["migration", "knowledge"]
```

- [ ] **Step 1.2: Run test to verify it fails**

Run: `pytest tests/test_models.py::test_project_status_values tests/test_models.py::test_project_minimal tests/test_models.py::test_project_full -v`
Expected: FAIL with `ImportError: cannot import name 'Project'`.

- [ ] **Step 1.3: Add the model**

Append to `src/models.py`:

```python
class ProjectStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class Project(BaseModel):
    """A portfolio-level project card living at tasks/projects/<slug>.md.

    Distinct from Task: a Project does not move through columns and is not
    advanced by an LLM cycle. The Orchestrator reads it only to decide
    whether to advance tasks that reference it via Task.project.
    """

    slug: str
    status: ProjectStatus = ProjectStatus.ACTIVE
    repo_path: Optional[str] = None
    priority: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    last_touched: Optional[datetime] = None
    title: str = ""
    body: str = ""
    source_path: Optional[str] = None
```

- [ ] **Step 1.4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS, all tests including the three new ones.

- [ ] **Step 1.5: Commit**

```bash
git add src/models.py tests/test_models.py
git commit -m "feat(models): add Project model and ProjectStatus enum"
```

---

## Task 2: Project parser

**Files:**
- Create: `src/board/project_parser.py`
- Test: `tests/test_project_parser.py`

- [ ] **Step 2.1: Write the failing test**

Create `tests/test_project_parser.py`:

```python
from datetime import datetime
from pathlib import Path

import pytest

from src.board.project_parser import (
    ProjectFileMalformed,
    parse_project_file,
    parse_project_string,
)
from src.models import ProjectStatus


SAMPLE_PROJECT = """\
---
type: project
slug: evernote
status: active
repo_path: ../../evernote
priority: P1
tags: [migration, knowledge]
last_touched: 2026-04-30
---
# evernote

## 一句話
匯入舊筆記。
"""


def test_parse_basic():
    p = parse_project_string(SAMPLE_PROJECT)
    assert p.slug == "evernote"
    assert p.status == ProjectStatus.ACTIVE
    assert p.repo_path == "../../evernote"
    assert p.priority == "P1"
    assert p.tags == ["migration", "knowledge"]
    assert p.last_touched == datetime(2026, 4, 30)


def test_parse_status_default_when_missing():
    text = """---
type: project
slug: foo
---
# foo
"""
    p = parse_project_string(text)
    assert p.status == ProjectStatus.ACTIVE


def test_parse_status_default_when_unknown():
    """Unrecognized status string falls back to ACTIVE (parser logs caller-side)."""
    text = """---
type: project
slug: foo
status: somethingweird
---
"""
    p = parse_project_string(text)
    assert p.status == ProjectStatus.ACTIVE


def test_parse_status_paused():
    text = """---
type: project
slug: foo
status: paused
---
"""
    p = parse_project_string(text)
    assert p.status == ProjectStatus.PAUSED


def test_parse_missing_slug_raises():
    text = """---
type: project
status: active
---
"""
    with pytest.raises(ProjectFileMalformed):
        parse_project_string(text)


def test_parse_no_frontmatter_raises():
    with pytest.raises(ProjectFileMalformed):
        parse_project_string("just a body")


def test_parse_body_extracted():
    p = parse_project_string(SAMPLE_PROJECT)
    assert "## 一句話" in p.body
    assert "匯入舊筆記" in p.body


def test_parse_file_sets_source_path(tmp_path: Path):
    f = tmp_path / "evernote.md"
    f.write_text(SAMPLE_PROJECT, encoding="utf-8")
    p = parse_project_file(f)
    assert p.source_path == str(f)
```

- [ ] **Step 2.2: Run test to verify it fails**

Run: `pytest tests/test_project_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.board.project_parser'`.

- [ ] **Step 2.3: Implement the parser**

Create `src/board/project_parser.py`:

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import frontmatter

from src.models import Project, ProjectStatus


class ProjectFileMalformed(ValueError):
    """Raised when a project card lacks the frontmatter required to be a Project.

    Mirrors TaskFileMalformed in src.board.parser. Caller should log + skip.
    """


def parse_project_string(text: str, source_path: str | None = None) -> Project:
    post = frontmatter.loads(text)
    meta = post.metadata
    body = post.content

    where = f" in {source_path}" if source_path else ""
    if not meta:
        raise ProjectFileMalformed(f"no frontmatter found{where}")
    slug = meta.get("slug")
    if not slug:
        raise ProjectFileMalformed(f"missing required frontmatter field 'slug'{where}")

    status_raw = meta.get("status", "active") or "active"
    try:
        status = ProjectStatus(str(status_raw))
    except ValueError:
        status = ProjectStatus.ACTIVE  # unknown → active; caller may log

    last_touched_raw = meta.get("last_touched")
    last_touched = _parse_datetime_or_none(last_touched_raw)

    repo_path_raw = meta.get("repo_path")
    repo_path = str(repo_path_raw) if repo_path_raw not in (None, "") else None

    priority_raw = meta.get("priority")
    priority = str(priority_raw) if priority_raw not in (None, "") else None

    tags = meta.get("tags", []) or []

    title = ""
    stripped = body.lstrip()
    if stripped.startswith("# "):
        title = stripped.split("\n", 1)[0][2:].strip()

    return Project(
        slug=str(slug),
        status=status,
        repo_path=repo_path,
        priority=priority,
        tags=[str(t) for t in tags],
        last_touched=last_touched,
        title=title,
        body=body,
        source_path=source_path,
    )


def parse_project_file(path: Path) -> Project:
    text = path.read_text(encoding="utf-8")
    return parse_project_string(text, source_path=str(path))


def _parse_datetime_or_none(value) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    if hasattr(value, "year") and hasattr(value, "month"):  # date object
        return datetime(value.year, value.month, value.day)
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None
```

- [ ] **Step 2.4: Run test to verify it passes**

Run: `pytest tests/test_project_parser.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 2.5: Commit**

```bash
git add src/board/project_parser.py tests/test_project_parser.py
git commit -m "feat(parser): add Project parser with frontmatter validation"
```

---

## Task 3: BoardManager — get_project / list_projects

**Files:**
- Modify: `src/board/manager.py`
- Test: `tests/test_manager.py`

- [ ] **Step 3.1: Write the failing tests**

Append to `tests/test_manager.py`:

```python
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
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `pytest tests/test_manager.py -v -k project`
Expected: FAIL — `BoardManager` has no `get_project` method.

- [ ] **Step 3.3: Implement methods**

Modify `src/board/manager.py`:

At the top, after existing imports, add:
```python
from src.board.project_parser import ProjectFileMalformed, parse_project_file
from src.models import Project, TaskIntent, TaskStatus
```

(Replace the existing `from src.models import TaskIntent, TaskStatus` line with the line above.)

Inside the `BoardManager` class, after `list_active_tasks`, add:

```python
    # ---------------------------------------------------------------- #
    # Projects                                                         #
    # ---------------------------------------------------------------- #

    def _projects_dir(self) -> Path:
        return self.tasks_dir / "projects"

    def get_project(self, slug: str) -> "Project | None":
        """Load a single project card by slug, or None if missing/malformed.

        Malformed cards are treated the same as missing — orchestrator should
        not crash because a user typed a stray character into the frontmatter.
        """
        path = self._projects_dir() / f"{slug}.md"
        if not path.exists():
            return None
        try:
            return parse_project_file(path)
        except ProjectFileMalformed:
            return None

    def list_projects(self) -> list[Project]:
        """List all parseable project cards under tasks/projects/.

        Malformed cards are skipped silently.
        """
        projects_dir = self._projects_dir()
        if not projects_dir.exists():
            return []
        result: list[Project] = []
        for path in sorted(projects_dir.glob("*.md")):
            try:
                result.append(parse_project_file(path))
            except ProjectFileMalformed:
                continue
        return result
```

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `pytest tests/test_manager.py -v`
Expected: PASS, all existing tests + 6 new ones.

- [ ] **Step 3.5: Commit**

```bash
git add src/board/manager.py tests/test_manager.py
git commit -m "feat(manager): add get_project and list_projects"
```

---

## Task 4: Watcher ignores projects/ folder

**Files:**
- Modify: `src/dispatcher/watcher.py:17-26`
- Test: `tests/test_watcher.py`

**Why:** Project cards do not represent tasks the orchestrator should run a cycle on. Filtering them at the watcher level keeps the orchestrator's surface clean and prevents "TaskFileMalformed: missing field id" log spam every time the user toggles a project status. Project status is read on demand by `get_project`, not via watcher events.

- [ ] **Step 4.1: Write the failing test**

Append to `tests/test_watcher.py` (consult the file for style; look for existing `test_*ignored*` tests as a model):

```python
def test_projects_folder_is_ignored(tmp_path):
    """Edits under tasks/projects/ should NOT trigger the watcher callback.

    Project cards are read on demand by the orchestrator, not via fs events.
    """
    from src.dispatcher.watcher import _is_ignored

    p = tmp_path / "tasks" / "projects" / "evernote.md"
    assert _is_ignored(p) is True

    # Also test the Windows-style separator branch
    from pathlib import PureWindowsPath
    win_path = PureWindowsPath(r"C:\Users\foo\tasks\projects\alpha-project.md")
    assert _is_ignored(win_path) is True
```

- [ ] **Step 4.2: Run test to verify it fails**

Run: `pytest tests/test_watcher.py::test_projects_folder_is_ignored -v`
Expected: FAIL — `_is_ignored` returns False for `tasks/projects/...`.

- [ ] **Step 4.3: Add /projects/ to ignore fragments**

In `src/dispatcher/watcher.py`, change the `_IGNORE_PATH_FRAGMENTS` tuple (currently lines 17-26) to:

```python
_IGNORE_PATH_FRAGMENTS = (
    "/.obsidian/",
    "\\.obsidian\\",          # Windows
    "/_attachments/",
    "\\_attachments\\",
    "/.trash/",
    "\\.trash\\",
    "/templates/",
    "\\templates\\",
    "/projects/",
    "\\projects\\",
)
```

- [ ] **Step 4.4: Run tests to verify they pass**

Run: `pytest tests/test_watcher.py -v`
Expected: PASS, all watcher tests.

- [ ] **Step 4.5: Commit**

```bash
git add src/dispatcher/watcher.py tests/test_watcher.py
git commit -m "feat(watcher): ignore tasks/projects/ from fs events"
```

---

## Task 5: Orchestrator filter — skip tasks for paused projects

**Files:**
- Modify: `src/agent/orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 5.1: Write the failing test**

Append to `tests/test_orchestrator.py`:

```python
import asyncio


def _write_project_card(tasks_dir: Path, slug: str, status: str) -> None:
    proj_dir = tasks_dir / "projects"
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / f"{slug}.md").write_text(
        f"---\ntype: project\nslug: {slug}\nstatus: {status}\n---\n# {slug}\n",
        encoding="utf-8",
    )


def _write_task_into(tasks_dir: Path, column: str, project: str = "") -> Path:
    column_dir = tasks_dir / column
    column_dir.mkdir(parents=True, exist_ok=True)
    task = _make_task(id="999", title="t", project=project)
    p = column_dir / "999-t.md"
    write_task_file(task, p)
    return p


def _orchestrator_with_mock_llm(tasks_dir: Path, tmp_path: Path):
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "rules.md").write_text("# rules\n", encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()

    llm = _llm_with_responses(_final_text("done"))
    return Orchestrator(
        tasks_dir=tasks_dir,
        skills_dir=skills,
        logs_dir=logs,
        llm=llm,
        tools=[],
        suppress_self=_noop_suppress,
    ), llm


def test_run_cycle_skips_todo_task_when_project_paused(tmp_path):
    tasks = _kanban(tmp_path)
    _write_project_card(tasks, "evernote", "paused")
    path = _write_task_into(tasks, "todo", project="evernote")

    orch, llm = _orchestrator_with_mock_llm(tasks, tmp_path)
    asyncio.run(orch.run_cycle(path))

    # File untouched: task still in todo/, no LLM call made.
    assert path.exists()
    assert llm.chat.await_count == 0


def test_run_cycle_skips_todo_task_when_project_archived(tmp_path):
    tasks = _kanban(tmp_path)
    _write_project_card(tasks, "evernote", "archived")
    path = _write_task_into(tasks, "todo", project="evernote")

    orch, llm = _orchestrator_with_mock_llm(tasks, tmp_path)
    asyncio.run(orch.run_cycle(path))

    assert path.exists()
    assert llm.chat.await_count == 0


def test_run_cycle_processes_todo_task_when_project_active(tmp_path):
    tasks = _kanban(tmp_path)
    _write_project_card(tasks, "evernote", "active")
    path = _write_task_into(tasks, "todo", project="evernote")

    orch, llm = _orchestrator_with_mock_llm(tasks, tmp_path)
    asyncio.run(orch.run_cycle(path))

    # Cycle ran (LLM was called) and the file has moved to doing/.
    assert llm.chat.await_count == 1
    assert not path.exists()
    assert any((tasks / "doing").glob("*.md"))


def test_run_cycle_processes_task_with_no_project_field(tmp_path):
    """Tasks without a project: field run unfiltered (back-compat)."""
    tasks = _kanban(tmp_path)
    path = _write_task_into(tasks, "todo", project="")

    orch, llm = _orchestrator_with_mock_llm(tasks, tmp_path)
    asyncio.run(orch.run_cycle(path))

    assert llm.chat.await_count == 1


def test_run_cycle_processes_task_when_project_card_missing(tmp_path):
    """If the project card doesn't exist, don't filter — log + run.

    Avoids daemon getting stuck on a typo'd project slug.
    """
    tasks = _kanban(tmp_path)
    path = _write_task_into(tasks, "todo", project="nonexistent")

    orch, llm = _orchestrator_with_mock_llm(tasks, tmp_path)
    asyncio.run(orch.run_cycle(path))

    assert llm.chat.await_count == 1


def test_run_cycle_does_not_filter_doing_tasks_when_project_paused(tmp_path):
    """Tasks already in doing/ keep running even after their project is paused.

    Spec: paused 不打斷正在跑的任務.
    """
    tasks = _kanban(tmp_path)
    _write_project_card(tasks, "evernote", "paused")
    path = _write_task_into(tasks, "doing", project="evernote")

    orch, llm = _orchestrator_with_mock_llm(tasks, tmp_path)
    asyncio.run(orch.run_cycle(path))

    assert llm.chat.await_count == 1
```

- [ ] **Step 5.2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator.py -v -k "project"`
Expected: FAIL — orchestrator does not filter on project status, so the paused tests still call the LLM and move the file.

- [ ] **Step 5.3: Implement the filter**

In `src/agent/orchestrator.py`, find the `run_cycle` method (around line 76). After the malformed-task `return` (around line 104), and BEFORE the `if task.intent is not None:` block, insert:

```python
            # Multi-project filter: skip tasks whose project card is paused
            # or archived. Tasks already in doing/ are exempt — paused means
            # "don't start new", not "kill in flight".
            if self._skip_for_paused_project(task, current_status):
                self.logger.log(LogEntry(
                    task_id=task.id, action="cycle_skipped",
                    detail=f"project={task.project} status=paused/archived",
                ))
                return
```

Then, in the same class, add this private method (place it near the other `_*` helpers, e.g. after `_status_from_path`):

```python
    def _skip_for_paused_project(self, task: Task, current_status: TaskStatus) -> bool:
        """Return True if this task should be held due to its project's status.

        Logic:
          - No project field → don't filter (back-compat).
          - Already in doing/ → don't filter (do not interrupt running work).
          - Project card missing → don't filter (avoid getting stuck on typos).
          - Project card unparseable → don't filter (handled as missing in manager).
          - Project status active → don't filter.
          - Project status paused or archived → SKIP.
        """
        if not task.project:
            return False
        if current_status == TaskStatus.DOING:
            return False
        project = self.manager.get_project(task.project)
        if project is None:
            return False
        from src.models import ProjectStatus
        return project.status != ProjectStatus.ACTIVE
```

- [ ] **Step 5.4: Run tests to verify they pass**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS, all existing orchestrator tests + 6 new project-filter tests.

- [ ] **Step 5.5: Run the full test suite to catch regressions**

Run: `pytest -v`
Expected: PASS, ~250 tests (previous 240 + ~14 new from Tasks 1-5).

- [ ] **Step 5.6: Commit**

```bash
git add src/agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): skip tasks whose project is paused or archived"
```

---

## Task 6: Project card template

**Files:**
- Create: `tasks/templates/project.md`

- [ ] **Step 6.1: Create the template file**

Write to `tasks/templates/project.md`:

```markdown
---
type: project
slug: ""
status: active
repo_path: ""
priority: P1
tags: []
last_touched: ""
---
# 

## 一句話


## 現在的焦點


## 下一步 (Next actions)
- [ ] 

## 決策記錄
- 

## 待解決的問題
- 

## 回顧 / 暫停原因

```

- [ ] **Step 6.2: Verify watcher does NOT pick this up**

The template lives under `tasks/templates/`, which is already in `_IGNORE_PATH_FRAGMENTS`. No code change needed — confirm by inspection.

- [ ] **Step 6.3: Commit**

```bash
git add tasks/templates/project.md
git commit -m "feat(templates): add project card template"
```

---

## Task 7: Obsidian project view + exclude projects/ from task views

**Files:**
- Create: `tasks/projects.base`
- Modify: `tasks/views.base:1-6`

- [ ] **Step 7.1: Create projects.base view**

Write to `tasks/projects.base`:

```yaml
filters:
  and:
    - file.ext == "md"
    - file.inFolder("projects")
views:
  - type: cards
    name: 全部項目
    filters:
      and:
        - status != "archived"
    order:
      - file.name
      - status
      - priority
      - last_touched
    group_by: status
  - type: cards
    name: Active
    filters:
      and:
        - status == "active"
    order:
      - priority
      - last_touched
      - file.name
  - type: cards
    name: Paused
    filters:
      and:
        - status == "paused"
    order:
      - last_touched
      - file.name
  - type: cards
    name: Archived
    filters:
      and:
        - status == "archived"
    order:
      - last_touched
      - file.name
```

- [ ] **Step 7.2: Exclude projects/ from views.base task views**

In `tasks/views.base`, change the top-level filter (lines 1-6) from:

```yaml
filters:
  and:
    - file.ext == "md"
    - '!file.inFolder("templates")'
    - '!file.inFolder("_attachments")'
    - file.name != "README"
```

To:

```yaml
filters:
  and:
    - file.ext == "md"
    - '!file.inFolder("templates")'
    - '!file.inFolder("_attachments")'
    - '!file.inFolder("projects")'
    - file.name != "README"
```

- [ ] **Step 7.3: Commit**

```bash
git add tasks/projects.base tasks/views.base
git commit -m "feat(obsidian): add projects.base view and exclude projects/ from task views"
```

---

## Task 8: bootstrap-projects CLI command

**Files:**
- Create: `src/board/bootstrap.py`
- Create: `tests/test_bootstrap.py`
- Modify: `src/cli.py`

- [ ] **Step 8.1: Write the failing test**

Create `tests/test_bootstrap.py`:

```python
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
```

- [ ] **Step 8.2: Run tests to verify they fail**

Run: `pytest tests/test_bootstrap.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.board.bootstrap'`.

- [ ] **Step 8.3: Implement bootstrap logic**

Create `src/board/bootstrap.py`:

```python
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class BootstrapResult:
    created: list[str] = field(default_factory=list)
    skipped_existing: list[str] = field(default_factory=list)


def bootstrap_projects(
    tasks_dir: Path,
    projects_root: Path,
    skip_slug: str | None = None,
) -> BootstrapResult:
    """Scaffold a project card for each direct subfolder of `projects_root`.

    - `tasks_dir`: the Obsidian vault root (the existing tasks/ directory).
    - `projects_root`: the parent directory containing project subfolders.
    - `skip_slug`: a folder name to skip (typically the vault's own project,
      whose card is hand-written instead of stub-generated).

    Skips folders that are dotfiles (e.g. `.git`) or non-directories.
    Skips folders whose card already exists at tasks/projects/<slug>.md.
    """
    if not projects_root.exists():
        raise FileNotFoundError(f"projects_root does not exist: {projects_root}")
    if not projects_root.is_dir():
        raise FileNotFoundError(f"projects_root is not a directory: {projects_root}")

    template_path = tasks_dir / "templates" / "project.md"
    if not template_path.exists():
        raise FileNotFoundError(f"missing template: {template_path}")

    template_text = template_path.read_text(encoding="utf-8")
    out_dir = tasks_dir / "projects"
    out_dir.mkdir(parents=True, exist_ok=True)

    result = BootstrapResult()
    for entry in sorted(projects_root.iterdir()):
        if not entry.is_dir():
            continue
        slug = entry.name
        if slug.startswith("."):
            continue
        if skip_slug is not None and slug == skip_slug:
            continue

        target = out_dir / f"{slug}.md"
        if target.exists():
            result.skipped_existing.append(slug)
            continue

        repo_path_rel = _relpath_from_vault(entry, tasks_dir)
        body = _fill_template(
            template_text,
            slug=slug,
            repo_path=repo_path_rel,
            today=date.today().isoformat(),
        )
        target.write_text(body, encoding="utf-8")
        result.created.append(slug)

    return result


def _relpath_from_vault(repo_dir: Path, tasks_dir: Path) -> str:
    """Compute a POSIX-style relative path from tasks_dir to repo_dir.

    Used as the `repo_path` frontmatter value so it works on both Windows
    and POSIX hosts. If the two paths are on different drives (Windows),
    fall back to absolute path.
    """
    try:
        rel = os.path.relpath(repo_dir.resolve(), tasks_dir.resolve())
    except ValueError:
        return str(repo_dir.resolve()).replace("\\", "/")
    return rel.replace("\\", "/")


def _fill_template(template: str, slug: str, repo_path: str, today: str) -> str:
    """Fill the project template's frontmatter and H1 from scaffold values."""
    text = template
    text = re.sub(r'^slug:\s*""\s*$', f'slug: "{slug}"', text, count=1, flags=re.MULTILINE)
    text = re.sub(
        r'^repo_path:\s*""\s*$',
        f'repo_path: "{repo_path}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r'^last_touched:\s*""\s*$',
        f"last_touched: {today}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    # Replace the empty H1 line "# " with "# <slug>".
    text = re.sub(r"^#\s*$", f"# {slug}", text, count=1, flags=re.MULTILINE)
    return text
```

- [ ] **Step 8.4: Run tests to verify they pass**

Run: `pytest tests/test_bootstrap.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 8.5: Wire bootstrap into the CLI**

Modify `src/cli.py`. In `build_parser`, after the `status` subparser registration (around line 37), add:

```python
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
        default="cc-assitant",
        help="Slug to skip (the vault's own project). Default: cc-assitant.",
    )
```

In `main`, after the `status` branch (around line 216), add:

```python
    if args.command == "bootstrap-projects":
        return cmd_bootstrap_projects(
            projects_root=args.projects_root,
            skip_slug=args.skip,
        )
```

Add the new command function above `main` (e.g. after `cmd_status`):

```python
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
```

- [ ] **Step 8.6: Add a CLI smoke test**

Append to `tests/test_cli.py` (or create if absent — check first):

```python
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
```

- [ ] **Step 8.7: Run tests to verify they pass**

Run: `pytest tests/test_bootstrap.py tests/test_cli.py -v`
Expected: PASS, all bootstrap tests + the CLI smoke test.

- [ ] **Step 8.8: Run the full suite**

Run: `pytest -v`
Expected: PASS.

- [ ] **Step 8.9: Commit**

```bash
git add src/board/bootstrap.py src/cli.py tests/test_bootstrap.py tests/test_cli.py
git commit -m "feat(cli): add bootstrap-projects subcommand"
```

---

## Task 9: Update tasks/README.md to document the projects/ folder

**Files:**
- Modify: `tasks/README.md`

- [ ] **Step 9.1: Append project-related docs**

Append to `tasks/README.md`:

```markdown

## 跨項目視圖

從 2026-04-30 起,vault 同時管理多個項目:

- **項目卡** 在 `projects/` 底下,每個項目一張 `.md`。
- 開 `projects.base` 看跨項目看板(Active / Paused / Archived 分組)。
- 新項目卡:從 `templates/project.md` 複製到 `projects/<slug>.md`,填好 frontmatter。
- 暫停某個項目:把那張卡片的 `status` 改成 `paused`(或 `archived`)。daemon 會跳過該項目下還沒進 doing/ 的任務,正在跑的不打斷。
- 任務檔的 frontmatter 要填 `project: <slug>`,daemon 才知道任務屬於哪個項目;沒填就視為通用任務,不受項目狀態影響。
- 用 `cc-assistant bootstrap-projects` 為 `projects/` 下沒卡的鄰居資料夾自動產 stub 卡。
```

- [ ] **Step 9.2: Commit**

```bash
git add tasks/README.md
git commit -m "docs(tasks): explain projects/ folder and pause workflow"
```

---

## Task 10: Run bootstrap on the user's actual project tree

This is a manual one-shot for the user. After all code tasks are merged.

- [ ] **Step 10.1: Verify the projects-root inference**

Run: `cc-assistant bootstrap-projects --projects-root <your-user>/projects --skip cc-assitant`

Expected output: lists the new cards created, e.g.:
```
created N project card(s):
  + alpha-project
  + beta-project
  + gamma-project
  + my-side-app
  + ...
```

- [ ] **Step 10.2: Open Obsidian on desktop, verify**

- Open `tasks/` vault in Obsidian.
- Open `projects.base` view → should see all 13 new cards under "Active".
- Open one card (e.g. `evernote.md`) → Properties panel shows `slug`, `status`, `repo_path`, `priority`, `tags`, `last_touched`.

- [ ] **Step 10.3: Manually write the cc-assitant card**

Bootstrap deliberately skips the vault's own project. Hand-write `tasks/projects/cc-assitant.md` using the template, since this card has the most existing context to fill (Plan 5a, Plan 5b, current state, etc.).

- [ ] **Step 10.4: Commit the new project cards**

```bash
git add tasks/projects/
git commit -m "chore(projects): bootstrap cards for sibling project folders"
```

- [ ] **Step 10.5: Smoke test the pause flow on phone**

(Best-effort; does not block plan completion.)
1. Wait for Obsidian Sync to land the new cards on phone.
2. Open `evernote.md` in Obsidian mobile, change `status:` from `active` to `paused`.
3. Create a dummy task in `todo/` with `project: evernote` frontmatter (use the default task template).
4. Wait for daemon poll (or trigger via watcher) → confirm the dummy task does NOT advance to doing/.
5. Change `status:` back to `active` → next poll, task advances.

---

## Self-review notes

**Spec coverage check** (against `2026-04-30-multi-project-portfolio-design.md`):

- `tasks/projects/` folder + per-project `.md` cards → Tasks 6, 8, 10.
- Project frontmatter schema (type/slug/status/repo_path/priority/tags/last_touched) → Tasks 1, 2, 6.
- Range B body (一句話, 現在的焦點, 下一步, 決策記錄, 待解決的問題, 回顧/暫停原因) → Task 6.
- Task → project link via `project:` field → already in `Task` model and parser; new orchestrator filter wired in Task 5.
- Orchestrator pre-cycle filter that respects `status` → Task 5.
- `paused` does not interrupt running tasks → Task 5 (DOING column exempt).
- bootstrap-projects CLI → Task 8.
- bootstrap skips vault's own project → Task 8 (`--skip cc-assitant` default).
- Errors: missing card / wrong status / missing slug / duplicate slug → handled in Tasks 2, 3, 5; `list_projects` policy in `BoardManager`.
- `projects.base` view + exclude `projects/` from `views.base` → Task 7.
- Watcher does not trigger cycles on project edits → Task 4.
- README docs → Task 9.

**Placeholder scan:** None — every step has concrete code or commands.

**Type consistency:** `ProjectStatus` used uniformly in models, parser, manager, orchestrator. `Project.slug: str` used as the lookup key throughout. `BootstrapResult` is the dataclass returned by `bootstrap_projects`; CLI uses `.created` and `.skipped_existing`.
