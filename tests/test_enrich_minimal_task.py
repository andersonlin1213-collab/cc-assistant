from datetime import datetime
from pathlib import Path

import frontmatter
import pytest

from src.board.parser import enrich_minimal_task


def _setup_vault(tmp_path: Path) -> Path:
    """Create a tasks/ scaffold with empty column dirs. Return tasks_dir."""
    tasks = tmp_path / "tasks"
    for col in ("backlog", "todo", "doing", "blocked", "review", "done"):
        (tasks / col).mkdir(parents=True)
    return tasks


def test_enrich_fills_id_created_updated_when_only_title(tmp_path):
    """Title-only frontmatter gets id, created, updated added; returns True."""
    tasks = _setup_vault(tmp_path)
    f = tasks / "todo" / "demo.md"
    f.write_text("---\ntitle: 测试\n---\n正文\n", encoding="utf-8")

    result = enrich_minimal_task(f, tasks)

    assert result is True
    post = frontmatter.loads(f.read_text(encoding="utf-8"))
    assert post.metadata["title"] == "测试"
    assert str(post.metadata["id"]) == "001"
    # created/updated must be parseable as YYYY-MM-DD HH:MM
    datetime.strptime(str(post.metadata["created"]), "%Y-%m-%d %H:%M")
    datetime.strptime(str(post.metadata["updated"]), "%Y-%m-%d %H:%M")
    # Body preserved
    assert "正文" in post.content


def test_enrich_is_noop_on_complete_file(tmp_path):
    """File with all 4 fields → returns False, content unchanged."""
    tasks = _setup_vault(tmp_path)
    f = tasks / "todo" / "complete.md"
    original = (
        "---\n"
        'id: "042"\n'
        "title: 已完整\n"
        "created: 2026-04-01 09:00\n"
        "updated: 2026-04-01 09:00\n"
        "---\n"
        "正文\n"
    )
    f.write_text(original, encoding="utf-8")

    result = enrich_minimal_task(f, tasks)

    assert result is False
    assert f.read_text(encoding="utf-8") == original


def test_enrich_is_noop_on_no_frontmatter(tmp_path):
    """File with body only → returns False, untouched."""
    tasks = _setup_vault(tmp_path)
    f = tasks / "doing" / "raw.md"
    original = "just a body, no frontmatter\n"
    f.write_text(original, encoding="utf-8")

    result = enrich_minimal_task(f, tasks)

    assert result is False
    assert f.read_text(encoding="utf-8") == original


def test_enrich_is_noop_when_title_missing(tmp_path):
    """Frontmatter without title → returns False even if other fields present."""
    tasks = _setup_vault(tmp_path)
    f = tasks / "doing" / "no-title.md"
    original = '---\nfoo: bar\nid: "999"\n---\nbody\n'
    f.write_text(original, encoding="utf-8")

    result = enrich_minimal_task(f, tasks)

    assert result is False
    assert f.read_text(encoding="utf-8") == original


def test_enrich_treats_empty_id_as_missing(tmp_path):
    """`id: ""` → enrichment fills it in, returns True."""
    tasks = _setup_vault(tmp_path)
    f = tasks / "todo" / "empty-id.md"
    f.write_text(
        '---\ntitle: 测试\nid: ""\ncreated: 2026-04-01 09:00\nupdated: 2026-04-01 09:00\n---\n',
        encoding="utf-8",
    )

    result = enrich_minimal_task(f, tasks)

    assert result is True
    post = frontmatter.loads(f.read_text(encoding="utf-8"))
    assert post.metadata["id"] == "001"
    assert str(post.metadata["created"]) == "2026-04-01 09:00"
    assert str(post.metadata["updated"]) == "2026-04-01 09:00"


def _write_task_with_id(tasks_dir: Path, column: str, task_id: str) -> Path:
    """Helper to drop a fully-formed task file with a given id."""
    column_dir = tasks_dir / column
    column_dir.mkdir(parents=True, exist_ok=True)
    p = column_dir / f"{task_id}-x.md"
    p.write_text(
        f'---\nid: "{task_id}"\ntitle: x\n'
        "created: 2026-04-01 09:00\nupdated: 2026-04-01 09:00\n---\n",
        encoding="utf-8",
    )
    return p


def test_next_id_skips_existing_max(tmp_path):
    tasks = _setup_vault(tmp_path)
    _write_task_with_id(tasks, "todo", "004")
    _write_task_with_id(tasks, "doing", "007")
    _write_task_with_id(tasks, "review", "002")

    f = tasks / "todo" / "new.md"
    f.write_text("---\ntitle: 新\n---\nbody\n", encoding="utf-8")
    enrich_minimal_task(f, tasks)

    post = frontmatter.loads(f.read_text(encoding="utf-8"))
    assert post.metadata["id"] == "008"


def test_next_id_ignores_non_numeric(tmp_path):
    """Legacy ids like 'demo-001' are skipped when computing max."""
    tasks = _setup_vault(tmp_path)
    # Place a numeric-id task in done/<month>/ to exercise the done subtree path.
    sub = tasks / "done" / "2026-04"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "002-x.md").write_text(
        '---\nid: "002"\ntitle: x\n'
        "created: 2026-04-01 09:00\nupdated: 2026-04-01 09:00\n---\n",
        encoding="utf-8",
    )
    # And a legacy non-numeric id alongside it.
    (sub / "demo-001.md").write_text(
        '---\nid: "demo-001"\ntitle: legacy\n'
        "created: 2026-04-01 09:00\nupdated: 2026-04-01 09:00\n---\n",
        encoding="utf-8",
    )

    f = tasks / "todo" / "new.md"
    f.write_text("---\ntitle: 新\n---\nbody\n", encoding="utf-8")
    enrich_minimal_task(f, tasks)

    post = frontmatter.loads(f.read_text(encoding="utf-8"))
    # max of (002 in done/2026-04, demo-001 ignored) = 2; next = 3
    assert post.metadata["id"] == "003"


def test_first_task_gets_001(tmp_path):
    """Empty vault → first id is '001'."""
    tasks = _setup_vault(tmp_path)
    f = tasks / "todo" / "first.md"
    f.write_text("---\ntitle: 第一个\n---\nbody\n", encoding="utf-8")

    enrich_minimal_task(f, tasks)

    post = frontmatter.loads(f.read_text(encoding="utf-8"))
    assert post.metadata["id"] == "001"


def test_concurrent_enrichment_allocates_distinct_ids(tmp_path):
    """Two threads enriching different files concurrently get sequential ids."""
    import threading

    tasks = _setup_vault(tmp_path)
    f1 = tasks / "todo" / "a.md"
    f2 = tasks / "todo" / "b.md"
    f1.write_text("---\ntitle: A\n---\n", encoding="utf-8")
    f2.write_text("---\ntitle: B\n---\n", encoding="utf-8")

    results: list[bool] = []
    barrier = threading.Barrier(2)

    def worker(p: Path) -> None:
        barrier.wait()
        results.append(enrich_minimal_task(p, tasks))

    t1 = threading.Thread(target=worker, args=(f1,))
    t2 = threading.Thread(target=worker, args=(f2,))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert results == [True, True]
    id1 = frontmatter.loads(f1.read_text(encoding="utf-8")).metadata["id"]
    id2 = frontmatter.loads(f2.read_text(encoding="utf-8")).metadata["id"]
    assert {id1, id2} == {"001", "002"}


def test_enrich_synthesizes_title_from_filename_in_todo(tmp_path):
    """Bare file in todo/ — daemon takes filename as title."""
    tasks = _setup_vault(tmp_path)
    f = tasks / "todo" / "查询小米股价.md"
    f.write_text("帮我查最近一个月的港股小米走势\n", encoding="utf-8")

    result = enrich_minimal_task(f, tasks)

    assert result is True
    post = frontmatter.loads(f.read_text(encoding="utf-8"))
    assert post.metadata["title"] == "查询小米股价"
    assert str(post.metadata["id"]) == "001"
    assert "created" in post.metadata
    assert "updated" in post.metadata
    assert "帮我查最近一个月" in post.content


def test_enrich_synthesizes_title_from_filename_in_backlog(tmp_path):
    """Same as todo/ — backlog/ also implies task."""
    tasks = _setup_vault(tmp_path)
    f = tasks / "backlog" / "未来想做的事.md"
    f.write_text("body\n", encoding="utf-8")

    assert enrich_minimal_task(f, tasks) is True
    post = frontmatter.loads(f.read_text(encoding="utf-8"))
    assert post.metadata["title"] == "未来想做的事"


def test_enrich_synthesizes_title_when_title_is_empty_string_in_todo(tmp_path):
    """`title: ""` in todo/ → treated as missing, filename used."""
    tasks = _setup_vault(tmp_path)
    f = tasks / "todo" / "空title.md"
    f.write_text(
        '---\ntitle: ""\nid: "999"\ncreated: 2026-04-01 09:00\nupdated: 2026-04-01 09:00\n---\nbody\n',
        encoding="utf-8",
    )

    assert enrich_minimal_task(f, tasks) is True
    post = frontmatter.loads(f.read_text(encoding="utf-8"))
    assert post.metadata["title"] == "空title"
    # Existing id is preserved (already a valid id; only title was missing)
    assert str(post.metadata["id"]) == "999"


def test_enrich_preserves_existing_title_in_todo(tmp_path):
    """If todo/ file already has a real title, filename is NOT used."""
    tasks = _setup_vault(tmp_path)
    f = tasks / "todo" / "filename-not-used.md"
    f.write_text(
        '---\ntitle: 真实标题\n---\nbody\n',
        encoding="utf-8",
    )

    assert enrich_minimal_task(f, tasks) is True  # id/created/updated still need filling
    post = frontmatter.loads(f.read_text(encoding="utf-8"))
    assert post.metadata["title"] == "真实标题"
    assert post.metadata["title"] != "filename-not-used"


def test_enrich_does_not_synthesize_title_in_doing(tmp_path):
    """A bare file in doing/ stays bare. Title-only rule doesn't apply there."""
    tasks = _setup_vault(tmp_path)
    f = tasks / "doing" / "bare-file.md"
    original = "body only\n"
    f.write_text(original, encoding="utf-8")

    assert enrich_minimal_task(f, tasks) is False
    assert f.read_text(encoding="utf-8") == original


def test_enrich_does_not_synthesize_title_in_review(tmp_path):
    """review/ also keeps strict requirements."""
    tasks = _setup_vault(tmp_path)
    f = tasks / "review" / "bare.md"
    original = "body\n"
    f.write_text(original, encoding="utf-8")

    assert enrich_minimal_task(f, tasks) is False
    assert f.read_text(encoding="utf-8") == original


def test_enrich_does_not_synthesize_title_in_blocked(tmp_path):
    """blocked/ also keeps strict requirements."""
    tasks = _setup_vault(tmp_path)
    f = tasks / "blocked" / "bare.md"
    original = "body\n"
    f.write_text(original, encoding="utf-8")

    assert enrich_minimal_task(f, tasks) is False
    assert f.read_text(encoding="utf-8") == original


def test_enrich_does_not_synthesize_title_in_subfolder_of_todo(tmp_path):
    """`todo/sub/foo.md` — direct-child rule rejects sub-subfolders."""
    tasks = _setup_vault(tmp_path)
    sub = tasks / "todo" / "sub"
    sub.mkdir(parents=True)
    f = sub / "foo.md"
    original = "body\n"
    f.write_text(original, encoding="utf-8")

    assert enrich_minimal_task(f, tasks) is False
    assert f.read_text(encoding="utf-8") == original


def test_enrich_skips_when_filename_stem_is_empty(tmp_path):
    """File literally named `.md` has empty stem → cannot derive title."""
    tasks = _setup_vault(tmp_path)
    f = tasks / "todo" / ".md"
    original = "body\n"
    f.write_text(original, encoding="utf-8")

    assert enrich_minimal_task(f, tasks) is False
    # File untouched
    assert f.read_text(encoding="utf-8") == original
