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
