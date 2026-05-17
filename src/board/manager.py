from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

from src.board.project_parser import ProjectFileMalformed, parse_project_file
from src.models import Project, TaskIntent, TaskStatus

_log = logging.getLogger(__name__)


class BoardManager:
    """Manages task files across the six status directories."""

    _INTENT_TARGET = {
        (TaskIntent.RESUME, TaskStatus.BLOCKED): TaskStatus.DOING,
        (TaskIntent.APPROVE, TaskStatus.REVIEW): TaskStatus.DONE,
        (TaskIntent.REJECT, TaskStatus.REVIEW): TaskStatus.TODO,
        (TaskIntent.PAUSE, TaskStatus.DOING): TaskStatus.BACKLOG,
    }

    def __init__(self, tasks_dir: Path) -> None:
        self.tasks_dir = tasks_dir

    @classmethod
    def target_status_for_intent(
        cls, intent: TaskIntent, current: TaskStatus
    ) -> "TaskStatus | None":
        """Return the target column for an intent applied at the current column.

        Returns None if the (intent, current) combination is not valid (e.g. user
        set intent: resume on a task already in todo/). Caller should clear the
        intent and log a warning in that case.
        """
        return cls._INTENT_TARGET.get((intent, current))

    def _status_dir(self, status: TaskStatus) -> Path:
        return self.tasks_dir / status.value

    def move_task(self, source: Path, new_status: TaskStatus) -> Path:
        """Move a task file to a new status directory.

        Done tasks are archived into monthly subdirectories.
        """
        target_dir = self._status_dir(new_status)

        if new_status == TaskStatus.DONE:
            month_dir = target_dir / datetime.now().strftime("%Y-%m")
            month_dir.mkdir(parents=True, exist_ok=True)
            target_dir = month_dir

        target_dir.mkdir(parents=True, exist_ok=True)
        dest = target_dir / source.name
        shutil.move(str(source), str(dest))
        return dest

    def list_tasks(self, status: TaskStatus) -> list[Path]:
        """List .md task files in a status directory.

        Done is recursive (monthly subdirs); others are flat.
        """
        directory = self._status_dir(status)
        if not directory.exists():
            return []
        if status == TaskStatus.DONE:
            return sorted(directory.rglob("*.md"))
        return sorted(directory.glob("*.md"))

    def list_active_tasks(self) -> list[Path]:
        """List active task files (todo + doing + blocked + review).

        Excludes backlog (not yet ready) and done (archived).
        """
        active: list[Path] = []
        for status in (
            TaskStatus.TODO,
            TaskStatus.DOING,
            TaskStatus.BLOCKED,
            TaskStatus.REVIEW,
        ):
            active.extend(self.list_tasks(status))
        return active

    # ---------------------------------------------------------------- #
    # Projects                                                         #
    # ---------------------------------------------------------------- #

    def _projects_dir(self) -> Path:
        return self.tasks_dir / "projects"

    def get_project(self, slug: str) -> "Project | None":
        """Load a single project card by slug, or None if missing/malformed.

        Malformed cards are treated the same as missing — orchestrator should
        not crash because a user typed a stray character into the frontmatter.
        Logs a warning when a card exists but fails to parse, so the user has
        a breadcrumb pointing at the broken file.
        """
        path = self._projects_dir() / f"{slug}.md"
        if not path.exists():
            return None
        try:
            return parse_project_file(path)
        except ProjectFileMalformed as e:
            _log.warning("project card malformed, skipping: %s (%s)", path, e)
            return None

    def list_projects(self) -> list[Project]:
        """List all parseable project cards under tasks/projects/.

        Malformed cards are skipped with a warning logged.
        """
        projects_dir = self._projects_dir()
        if not projects_dir.exists():
            return []
        result: list[Project] = []
        for path in sorted(projects_dir.glob("*.md")):
            try:
                result.append(parse_project_file(path))
            except ProjectFileMalformed as e:
                _log.warning("project card malformed, skipping: %s (%s)", path, e)
                continue
        return result
