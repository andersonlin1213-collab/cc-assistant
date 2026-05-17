# Auto-Enrich Minimal Tasks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users create a task by saving a markdown file with only `title:` in frontmatter; the daemon auto-fills `id`, `created`, `updated` on first parse and writes back.

**Architecture:** New helper `enrich_minimal_task(path, tasks_dir)` in `src/board/parser.py` that does the disk-side enrichment. Parser also relaxes its required-fields gate to `("title",)` and synthesizes defaults for the other three at parse-time (safety net for any caller that bypasses enrichment). The orchestrator calls `enrich_minimal_task` (wrapped in `suppress_self`) at the top of `run_cycle` and inside `replay_pending_intents`, before the existing `parse_task_file` calls.

**Tech Stack:** Python 3.13, `python-frontmatter`, pytest, `threading.Lock`.

**Spec:** `docs/superpowers/specs/2026-05-01-auto-enrich-minimal-tasks-design.md`

---

## File Plan

**New files:**
- `tests/test_enrich_minimal_task.py` — unit tests for the new helper.

**Modified files:**
- `src/board/parser.py` — relax `_REQUIRED_FRONTMATTER_FIELDS`; synthesize defaults in `parse_task_string` for missing id/created/updated; add `enrich_minimal_task` helper + private id-scan helpers.
- `src/agent/orchestrator.py` — call `enrich_minimal_task` (wrapped in `self.suppress_self()`) at the top of `run_cycle` (line 95 area) and inside the per-path loop of `replay_pending_intents` (line 226 area).
- `tests/test_parser.py` — add a case asserting `parse_task_string` accepts title-only input.
- `tests/test_orchestrator.py` — add an integration test asserting end-to-end enrichment + cycle runs once.
- `tasks/README.md` — append a "最小写法" note.

---

## Task 1: enrich_minimal_task — skeleton + happy path

**Files:**
- Modify: `src/board/parser.py`
- Test: `tests/test_enrich_minimal_task.py`

- [ ] **Step 1.1: Write the failing test**

Create `tests/test_enrich_minimal_task.py`:

```python
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
```

- [ ] **Step 1.2: Run test to verify it fails**

Run: `pytest tests/test_enrich_minimal_task.py::test_enrich_fills_id_created_updated_when_only_title -v`
Expected: FAIL with `ImportError: cannot import name 'enrich_minimal_task'`.

- [ ] **Step 1.3: Implement minimal helper**

Append to `src/board/parser.py` (above `parse_task_string`, after `_REQUIRED_FRONTMATTER_FIELDS`):

```python
import threading
from typing import Iterable

import frontmatter as _frontmatter  # already imported above; re-aliasing avoids shadowing

_ENRICH_LOCK = threading.Lock()


def enrich_minimal_task(path: Path, tasks_dir: Path) -> bool:
    """Auto-fill id/created/updated for a title-only task file.

    Idempotent. Reads frontmatter; if `title` is present and any of
    {id, created, updated} are missing or empty, computes values and writes
    the file back. Returns True iff the file was written.

    The id is the next available numeric slot across the entire vault
    (max numeric id of all parseable tasks + 1), zero-padded to three
    digits as a quoted string ("007"). Non-numeric ids in the corpus
    (e.g. "demo-001") are ignored when computing max.

    Concurrency: uses a module-level threading.Lock so two simultaneous
    enrichments allocate distinct sequential ids.
    """
    with _ENRICH_LOCK:
        text = path.read_text(encoding="utf-8")
        post = frontmatter.loads(text)
        meta = post.metadata or {}

        title = meta.get("title")
        if not title:
            return False

        needs_id = not meta.get("id")
        needs_created = not meta.get("created")
        needs_updated = not meta.get("updated")
        if not (needs_id or needs_created or needs_updated):
            return False

        if needs_id:
            meta["id"] = _allocate_next_id(tasks_dir)
        if needs_created:
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            meta["created"] = mtime.strftime("%Y-%m-%d %H:%M")
        if needs_updated:
            meta["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")

        post.metadata = meta
        path.write_text(frontmatter.dumps(post), encoding="utf-8")
        return True


def _allocate_next_id(tasks_dir: Path) -> str:
    """Return next sequential numeric id as zero-padded 3-digit string."""
    existing = _scan_existing_numeric_ids(tasks_dir)
    next_n = (max(existing) + 1) if existing else 1
    return f"{next_n:03d}"


def _scan_existing_numeric_ids(tasks_dir: Path) -> set[int]:
    """Collect all numeric `id` values in vault task files."""
    ids: set[int] = set()
    columns = ("backlog", "todo", "doing", "blocked", "review")
    for col in columns:
        col_dir = tasks_dir / col
        if col_dir.exists():
            for f in col_dir.glob("*.md"):
                ids |= _numeric_ids_in_file(f)
    done_dir = tasks_dir / "done"
    if done_dir.exists():
        for f in done_dir.glob("*/*.md"):
            ids |= _numeric_ids_in_file(f)
    return ids


def _numeric_ids_in_file(path: Path) -> set[int]:
    try:
        text = path.read_text(encoding="utf-8")
        post = frontmatter.loads(text)
        raw = post.metadata.get("id") if post.metadata else None
    except (OSError, ValueError):
        return set()
    if raw in (None, ""):
        return set()
    s = str(raw)
    if s.isdigit():
        return {int(s)}
    return set()
```

(Note: `_frontmatter` alias is unused — drop it. The existing `import frontmatter` at the top of parser.py is what we use.)

- [ ] **Step 1.4: Run test to verify it passes**

Run: `pytest tests/test_enrich_minimal_task.py::test_enrich_fills_id_created_updated_when_only_title -v`
Expected: PASS.

- [ ] **Step 1.5: Commit**

```bash
git add src/board/parser.py tests/test_enrich_minimal_task.py
git commit -m "feat(parser): add enrich_minimal_task helper for title-only tasks"
```

---

## Task 2: enrich is idempotent + handles missing/empty edges

**Files:**
- Test: `tests/test_enrich_minimal_task.py`

- [ ] **Step 2.1: Write the failing tests**

Append to `tests/test_enrich_minimal_task.py`:

```python
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
    f = tasks / "todo" / "raw.md"
    f.write_text("just a body, no frontmatter\n", encoding="utf-8")

    result = enrich_minimal_task(f, tasks)

    assert result is False


def test_enrich_is_noop_when_title_missing(tmp_path):
    """Frontmatter without title → returns False even if other fields present."""
    tasks = _setup_vault(tmp_path)
    f = tasks / "todo" / "no-title.md"
    f.write_text(
        '---\nfoo: bar\nid: "999"\n---\nbody\n',
        encoding="utf-8",
    )

    result = enrich_minimal_task(f, tasks)

    assert result is False


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
```

- [ ] **Step 2.2: Run tests to verify they pass**

The Task 1 implementation already covers these cases (the `if not meta.get("id"):` style guards treat missing AND empty AS missing; missing-title returns early; no-frontmatter falls through `meta = post.metadata or {}` and `not title` returns False).

Run: `pytest tests/test_enrich_minimal_task.py -v`
Expected: PASS, all 4 new tests + the original.

- [ ] **Step 2.3: Commit**

```bash
git add tests/test_enrich_minimal_task.py
git commit -m "test(parser): cover idempotent / empty-id / no-title edges of enrich_minimal_task"
```

---

## Task 3: id allocation — skip existing, ignore non-numeric, first-task = "001"

**Files:**
- Test: `tests/test_enrich_minimal_task.py`

- [ ] **Step 3.1: Write the failing tests**

Append to `tests/test_enrich_minimal_task.py`:

```python
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
    _write_task_with_id(tasks, "done", "002")  # done has YYYY-MM subdirs normally;
    # _write_task_with_id puts it in done/ directly which is fine for the helper.
    # For the legacy id, place under a subdir to exercise that scan path:
    sub = tasks / "done" / "2026-04"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "demo-001.md").write_text(
        '---\nid: "demo-001"\ntitle: legacy\n'
        "created: 2026-04-01 09:00\nupdated: 2026-04-01 09:00\n---\n",
        encoding="utf-8",
    )

    f = tasks / "todo" / "new.md"
    f.write_text("---\ntitle: 新\n---\nbody\n", encoding="utf-8")
    enrich_minimal_task(f, tasks)

    post = frontmatter.loads(f.read_text(encoding="utf-8"))
    # max of (002 in done/, demo-001 ignored) = 2; next = 3
    assert post.metadata["id"] == "003"


def test_first_task_gets_001(tmp_path):
    """Empty vault → first id is '001'."""
    tasks = _setup_vault(tmp_path)
    f = tasks / "todo" / "first.md"
    f.write_text("---\ntitle: 第一个\n---\nbody\n", encoding="utf-8")

    enrich_minimal_task(f, tasks)

    post = frontmatter.loads(f.read_text(encoding="utf-8"))
    assert post.metadata["id"] == "001"
```

- [ ] **Step 3.2: Run tests to verify they pass**

The Task 1 implementation already includes `_scan_existing_numeric_ids` covering both column files and `done/<month>/*.md`, plus the `s.isdigit()` filter for non-numeric ids and the `else 1` fallback for empty vault.

Wait — the helper `_write_task_with_id(tasks, "done", "002")` writes to `tasks/done/002-x.md`, but `_scan_existing_numeric_ids` only looks under `done/*/*.md` (one subdir level). Update the test helper to put done-tasks in a YYYY-MM subdir, OR update the scan to also check `done/*.md` directly. Pick the latter for robustness:

In `src/board/parser.py`, in `_scan_existing_numeric_ids`, replace:
```python
    done_dir = tasks_dir / "done"
    if done_dir.exists():
        for f in done_dir.glob("*/*.md"):
            ids |= _numeric_ids_in_file(f)
```
with:
```python
    done_dir = tasks_dir / "done"
    if done_dir.exists():
        # done/ has YYYY-MM subdirs in normal use, but also allow loose files.
        for f in done_dir.rglob("*.md"):
            ids |= _numeric_ids_in_file(f)
```

Run: `pytest tests/test_enrich_minimal_task.py -v`
Expected: PASS.

- [ ] **Step 3.3: Commit**

```bash
git add src/board/parser.py tests/test_enrich_minimal_task.py
git commit -m "test(parser): cover id allocation across columns + done/ subtree"
```

---

## Task 4: enrichment is thread-safe under contention

**Files:**
- Test: `tests/test_enrich_minimal_task.py`

- [ ] **Step 4.1: Write the failing test**

Append to `tests/test_enrich_minimal_task.py`:

```python
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
```

- [ ] **Step 4.2: Run test to verify it passes**

The lock added in Task 1 (`_ENRICH_LOCK = threading.Lock()` wrapping the whole helper body) already serializes the read+write critical section, so each thread sees the previous thread's write before computing its own next id.

Run: `pytest tests/test_enrich_minimal_task.py -v`
Expected: PASS, including the new concurrency test.

- [ ] **Step 4.3: Commit**

```bash
git add tests/test_enrich_minimal_task.py
git commit -m "test(parser): assert enrich is thread-safe under concurrent calls"
```

---

## Task 5: parser accepts title-only and synthesizes defaults

**Files:**
- Modify: `src/board/parser.py`
- Test: `tests/test_parser.py`

**Why:** Even though enrichment writes back before parse in normal flow, parsers can be called by other consumers (tests, ad-hoc scripts, replay paths). Relaxing the gate to require only `title` ensures a robust safety net: parse never crashes on a "almost-task" file, and synthesizes safe defaults for missing fields.

- [ ] **Step 5.1: Write the failing test**

Append to `tests/test_parser.py`:

```python
def test_parse_accepts_title_only_with_synthesized_defaults():
    """Parser must not crash on a file with only `title` in frontmatter.

    It returns a Task whose id is empty, created/updated default to a
    sentinel datetime, and other fields use their model defaults. This
    is the safety-net behavior for callers that bypass enrichment.
    """
    text = "---\ntitle: minimal\n---\n## 任务描述\nbody\n"
    task = parse_task_string(text)
    assert task.title == "minimal"
    assert task.id == ""  # synthesized empty so caller can detect "needs enrich"
    # created/updated must be a parseable datetime (we use epoch as sentinel)
    from datetime import datetime
    assert isinstance(task.created, datetime)
    assert isinstance(task.updated, datetime)
```

- [ ] **Step 5.2: Run test to verify it fails**

Run: `pytest tests/test_parser.py::test_parse_accepts_title_only_with_synthesized_defaults -v`
Expected: FAIL with `TaskFileMalformed: missing required frontmatter field 'id'`.

- [ ] **Step 5.3: Implement relaxation + defaults**

In `src/board/parser.py`, change the constant:

```python
_REQUIRED_FRONTMATTER_FIELDS = ("title",)
```

Then in `parse_task_string`, replace the `try: created = _parse_datetime(meta["created"])` block (lines 56-60) with:

```python
    # `created` and `updated` may be absent on minimal task files that haven't
    # been enriched yet. Use the epoch as a sentinel — visible to readers as
    # 1970-01-01 — and let the enrichment path overwrite it on first daemon
    # touch. Any explicit value, well-formed or not, is parsed normally.
    try:
        created = _parse_datetime(meta["created"]) if meta.get("created") else datetime.fromtimestamp(0)
        updated = _parse_datetime(meta["updated"]) if meta.get("updated") else datetime.fromtimestamp(0)
    except ValueError as e:
        raise TaskFileMalformed(f"unparseable datetime{where}: {e}") from e
```

And replace the `id=str(meta["id"])` line in the `Task(...)` return (line 90) with:

```python
        id=str(meta["id"]) if meta.get("id") else "",
```

- [ ] **Step 5.4: Run test to verify it passes**

Run: `pytest tests/test_parser.py -v`
Expected: PASS, including the new test and all existing parser tests.

- [ ] **Step 5.5: Run the full suite to catch regressions**

Run: `pytest -v`
Expected: PASS overall. Existing tests that intentionally feed missing-id frontmatter to assert `TaskFileMalformed` will now fail — they need updating (see Step 5.6).

- [ ] **Step 5.6: Update existing tests that expected raises on missing id**

Search: `pytest -v 2>&1 | grep FAIL` and look for any test that asserts `TaskFileMalformed` is raised due to missing id/created/updated. Update each: either remove the test (relaxation makes it irrelevant), or change the expectation to assert the synthesized defaults.

Specifically check `tests/test_parser.py` for any `with pytest.raises(TaskFileMalformed)` blocks with frontmatter that omits id/created/updated; convert each to assert `parse_task_string` returns a Task with synthesized defaults instead. The single hard-required field is now `title` — any test feeding frontmatter without `title` should still raise.

Run: `pytest -v`
Expected: PASS.

- [ ] **Step 5.7: Commit**

```bash
git add src/board/parser.py tests/test_parser.py
git commit -m "feat(parser): relax required fields to title-only with synthesized defaults"
```

---

## Task 6: Orchestrator.run_cycle calls enrich before parse

**Files:**
- Modify: `src/agent/orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 6.1: Write the failing test**

Append to `tests/test_orchestrator.py`:

```python
import asyncio


def test_run_cycle_enriches_minimal_task_before_parsing(tmp_path):
    """A title-only file in todo/ becomes a fully-formed task on first cycle.

    End-to-end: drop a minimal file → run_cycle → file gains id, created,
    updated; LLM is called once; conversation entry was appended.
    """
    tasks = _kanban(tmp_path)  # existing test helper that creates tasks/<col>/
    minimal = tasks / "todo" / "新需求.md"
    minimal.write_text(
        "---\ntitle: 写一句 pong\n---\n## 任务描述\n回 pong\n",
        encoding="utf-8",
    )

    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "rules.md").write_text("# rules\n", encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()

    llm = _llm_with_responses(_final_text("pong"))
    orch = Orchestrator(
        tasks_dir=tasks,
        skills_dir=skills,
        logs_dir=logs,
        llm=llm,
        tools=[],
        suppress_self=_noop_suppress,
    )
    asyncio.run(orch.run_cycle(minimal))

    # File now has full frontmatter; LLM was called exactly once.
    import frontmatter
    final_path = minimal if minimal.exists() else next((tasks / "doing").glob("*.md"))
    post = frontmatter.loads(final_path.read_text(encoding="utf-8"))
    assert str(post.metadata["id"]) == "001"
    assert post.metadata["title"] == "写一句 pong"
    assert "created" in post.metadata
    assert "updated" in post.metadata
    assert llm.chat.await_count == 1
```

(Use whatever existing helpers `_kanban`, `_llm_with_responses`, `_final_text`, `_noop_suppress` your test file already defines for orchestrator tests. If they're not present, copy from the project-paused tests written in the multi-project plan.)

- [ ] **Step 6.2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator.py::test_run_cycle_enriches_minimal_task_before_parsing -v`
Expected: FAIL — orchestrator does not call enrich, so the parse synthesizes empty id and the file on disk never gets the new fields.

- [ ] **Step 6.3: Wire enrich into run_cycle**

In `src/agent/orchestrator.py`, at the top of the file:

```python
from src.board.parser import TaskFileMalformed, enrich_minimal_task, parse_task_file
```

(Add `enrich_minimal_task` to the existing import.)

Then in `run_cycle` (line 77 area), insert just BEFORE the `try: task = parse_task_file(path)` block (around line 94):

```python
            # Auto-enrich title-only minimal tasks so users can drop a file with
            # just `title:` and a body. The write-back is wrapped in suppress_self
            # so it doesn't re-trigger this watcher event. No-op for any file
            # that already has id/created/updated.
            with self.suppress_self():
                try:
                    enrich_minimal_task(path, self.tasks_dir)
                except OSError as e:
                    self.logger.log_system(
                        action="enrich_failed",
                        detail=f"path={path} err={e}",
                        status="error",
                    )
                    return
```

- [ ] **Step 6.4: Run test to verify it passes**

Run: `pytest tests/test_orchestrator.py::test_run_cycle_enriches_minimal_task_before_parsing -v`
Expected: PASS.

- [ ] **Step 6.5: Run the full suite**

Run: `pytest -v`
Expected: PASS.

- [ ] **Step 6.6: Commit**

```bash
git add src/agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): enrich minimal task before parse in run_cycle"
```

---

## Task 7: Orchestrator.replay_pending_intents calls enrich before parse

**Files:**
- Modify: `src/agent/orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 7.1: Write the failing test**

Append to `tests/test_orchestrator.py`:

```python
def test_replay_pending_intents_enriches_minimal_tasks(tmp_path):
    """Daemon startup replay must enrich title-only files it scans.

    Setup: a minimal title-only task with `intent: resume` in blocked/.
    Without enrichment, parse_task_file would still succeed (with synthesized
    empty id) — but enrichment writes the proper fields back to disk, which
    is the contract guaranteed by replay.
    """
    tasks = _kanban(tmp_path)
    minimal = tasks / "blocked" / "to-resume.md"
    minimal.write_text(
        "---\ntitle: 续一下\nintent: resume\n---\n## 任务描述\n继续\n",
        encoding="utf-8",
    )

    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "rules.md").write_text("# rules\n", encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()

    llm = _llm_with_responses(_final_text("ok"))
    orch = Orchestrator(
        tasks_dir=tasks,
        skills_dir=skills,
        logs_dir=logs,
        llm=llm,
        tools=[],
        suppress_self=_noop_suppress,
    )
    asyncio.run(orch.replay_pending_intents())

    # File should be enriched: even after intent moved it, the destination
    # file's frontmatter has id/created/updated filled.
    import frontmatter
    candidates = list((tasks / "doing").glob("*.md")) + list((tasks / "blocked").glob("*.md"))
    assert candidates, "task should still exist somewhere after replay"
    post = frontmatter.loads(candidates[0].read_text(encoding="utf-8"))
    assert str(post.metadata["id"]) == "001"
    assert "created" in post.metadata
```

- [ ] **Step 7.2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator.py::test_replay_pending_intents_enriches_minimal_tasks -v`
Expected: FAIL — replay parses without enriching, so the file on disk never gains the synthesized fields.

- [ ] **Step 7.3: Wire enrich into replay_pending_intents**

In `src/agent/orchestrator.py`, in `replay_pending_intents` (line 206), inside the `for path in self.manager.list_tasks(status):` loop (line 225), insert BEFORE the existing `try: task = parse_task_file(path)` (line 226):

```python
                with self.suppress_self():
                    try:
                        enrich_minimal_task(path, self.tasks_dir)
                    except OSError as e:
                        self.logger.log_system(
                            action="replay_enrich_failed",
                            detail=f"path={path} err={e}",
                            status="error",
                        )
                        continue
```

- [ ] **Step 7.4: Run test to verify it passes**

Run: `pytest tests/test_orchestrator.py::test_replay_pending_intents_enriches_minimal_tasks -v`
Expected: PASS.

- [ ] **Step 7.5: Run the full suite**

Run: `pytest -v`
Expected: PASS.

- [ ] **Step 7.6: Commit**

```bash
git add src/agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): enrich minimal task before parse in replay_pending_intents"
```

---

## Task 8: Document the minimal-task workflow

**Files:**
- Modify: `tasks/README.md`

- [ ] **Step 8.1: Append minimal-write usage note**

Append to `tasks/README.md`:

```markdown

## 最小寫法 (minimal task)

從 2026-05-01 起,新建任務檔的最少寫法:

```yaml
---
title: 山西去年净利润
---

我想看陕西门店去年净利润...
```

存到 `tasks/todo/<任意檔名>.md` 即可。daemon 第一次跑這個檔的時候會自動補上 `id`(全 vault 下個編號)、`created`(檔的 mtime)、`updated`(現在),寫回文件 frontmatter。文件名不會被改。

需要更多欄位(`project` / `priority` / `who` / `auto_approve` 等)的時候再寫;沒寫的都用模型預設值。

更完整的範本見 `templates/full.md`。
```

- [ ] **Step 8.2: Commit**

```bash
git add tasks/README.md
git commit -m "docs(tasks): document minimal task frontmatter (title-only)"
```

---

## Self-review notes

**Spec coverage check** (against `2026-05-01-auto-enrich-minimal-tasks-design.md`):

- enrich_minimal_task helper (idempotent, title-only enrichment) → Tasks 1, 2.
- id allocation across vault (max numeric + 1, ignore non-numeric, "001" if empty) → Task 3.
- threading.Lock for concurrent enrichment → Tasks 1 (impl), 4 (test).
- Parser relaxation to `("title",)` + synthesized defaults → Task 5.
- Orchestrator.run_cycle calls enrich → Task 6.
- Orchestrator.replay_pending_intents calls enrich → Task 7.
- Watcher suppress_self wrapping the write-back → Tasks 6, 7.
- README docs → Task 8.
- New `tasks/templates/full.md` already added in 2026-05-01 commit `941cc81` (out of scope here).

**Placeholder scan:** None. Each step has concrete code or commands. The note in Step 6.1 about reusing test helpers (`_kanban`, `_llm_with_responses`, etc.) refers to helpers that already exist in `tests/test_orchestrator.py` from the multi-project plan — they're not placeholders, they're acknowledgment of established conventions.

**Type consistency:** `enrich_minimal_task(path: Path, tasks_dir: Path) -> bool` used identically in all 4 call sites (Tasks 1 helper, Task 6 run_cycle, Task 7 replay). `_allocate_next_id` returns `str` (zero-padded). `_scan_existing_numeric_ids` returns `set[int]`. Module-level lock named `_ENRICH_LOCK`. Consistent throughout.

**Scope:** One coherent feature, ~7 tasks, all touching `src/board/parser.py` + `src/agent/orchestrator.py` + tests + one README. Single implementation plan is appropriate.
