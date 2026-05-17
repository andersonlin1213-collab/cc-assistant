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
