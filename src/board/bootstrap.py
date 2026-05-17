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
    """Fill the project template's frontmatter and H1 from scaffold values.

    Each slot must match exactly once; if a slot is missing (e.g. the template
    was edited and a field renamed), raise ValueError so bootstrap fails loudly
    instead of generating a half-filled card.
    """
    text = template
    text = _sub_one(
        text,
        r'^slug:\s*""\s*$',
        f'slug: "{slug}"',
        slot="slug",
    )
    text = _sub_one(
        text,
        r'^repo_path:\s*""\s*$',
        f'repo_path: "{repo_path}"',
        slot="repo_path",
    )
    text = _sub_one(
        text,
        r'^last_touched:\s*""\s*$',
        f"last_touched: {today}",
        slot="last_touched",
    )
    text = _sub_one(
        text,
        r"^#\s*$",
        f"# {slug}",
        slot="H1 title",
    )
    return text


def _sub_one(text: str, pattern: str, repl: str, *, slot: str) -> str:
    """Apply a single MULTILINE regex substitution; raise if it didn't fire."""
    new, n = re.subn(pattern, repl, text, count=1, flags=re.MULTILINE)
    if n == 0:
        raise ValueError(f"template missing slot: {slot}")
    return new
