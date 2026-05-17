# Todo Folder Implies Task Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Files dropped into `tasks/todo/` or `tasks/backlog/` run as tasks even with zero frontmatter — daemon synthesizes title from filename stem.

**Architecture:** Single change inside `src/board/parser.py:enrich_minimal_task`. Add an early "title-from-filename" recovery branch: if `meta["title"]` is missing/empty AND `path.parent.name in ("todo", "backlog")`, set title to `path.stem` and continue with the existing id/created/updated enrichment. Watcher (already filters vault root) and orchestrator (already calls enrich before parse) need no changes.

**Tech Stack:** Python 3.13, `python-frontmatter`, pytest.

**Spec:** `docs/superpowers/specs/2026-05-02-todo-folder-implies-task-design.md`

---

## File Plan

**Modified files:**
- `src/board/parser.py` — extend `enrich_minimal_task` (lines 41-81 area) with the `_path_implies_task` rule.
- `tests/test_enrich_minimal_task.py` — refactor 2 existing edge-case tests to use a non-task-implied column (so they continue to assert the original intent without conflicting with the new behavior). Add 8 new tests covering the new rule.
- `tests/test_orchestrator.py` — 1 integration test asserting end-to-end "bare file in todo/" cycle.
- `tasks/README.md` — extend the "最小寫法" section to document the zero-frontmatter shortcut.

**New files:** none.

---

## Task 1: Refactor existing no-op tests to use non-task-implied column

**Files:**
- Modify: `<your-user>/projects/cc-assitant/tests/test_enrich_minimal_task.py`

**Why:** Two existing tests (`test_enrich_is_noop_on_no_frontmatter`, `test_enrich_is_noop_when_title_missing`) place files in `tasks/todo/` and assert enrichment is a no-op. After Task 2's behavior change, those same paths WILL be enriched (title synthesized from filename). Move them to `tasks/doing/` so the original intent — "files lacking the task signal stay no-op" — is still captured. `doing/` keeps strict rules per the spec.

- [ ] **Step 1.1: Read the existing tests**

Open `tests/test_enrich_minimal_task.py` and locate:
- `test_enrich_is_noop_on_no_frontmatter` — currently writes `tasks/todo/raw.md` with body-only content
- `test_enrich_is_noop_when_title_missing` — currently writes `tasks/todo/no-title.md` with frontmatter that lacks `title`

- [ ] **Step 1.2: Move both tests' files to `doing/`**

In `test_enrich_is_noop_on_no_frontmatter`, change:
```python
    f = tasks / "todo" / "raw.md"
```
to:
```python
    f = tasks / "doing" / "raw.md"
```

In `test_enrich_is_noop_when_title_missing`, change:
```python
    f = tasks / "todo" / "no-title.md"
```
to:
```python
    f = tasks / "doing" / "no-title.md"
```

These tests' bodies / assertions are otherwise unchanged. Their docstrings can stay — the intent (no-op when frontmatter lacks task signal) is still being tested.

- [ ] **Step 1.3: Run tests to verify they still pass with the OLD code**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_enrich_minimal_task.py -v`
Expected: PASS — moving the file from todo/ to doing/ shouldn't change outcome under current code (current code returns False for any title-less file regardless of column).

- [ ] **Step 1.4: Commit**

```bash
git add tests/test_enrich_minimal_task.py
git commit -m "test(parser): move no-op enrich tests to doing/ for forward-compat"
```

---

## Task 2: Implement title-from-filename rule for todo/

**Files:**
- Modify: `<your-user>/projects/cc-assitant/src/board/parser.py:41-81`
- Test: `<your-user>/projects/cc-assitant/tests/test_enrich_minimal_task.py`

- [ ] **Step 2.1: Write the failing test**

Append to `tests/test_enrich_minimal_task.py`:

```python
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
```

- [ ] **Step 2.2: Run test to verify it fails**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_enrich_minimal_task.py::test_enrich_synthesizes_title_from_filename_in_todo -v`
Expected: FAIL — `enrich_minimal_task` currently returns False for files without frontmatter; assertion `result is True` fails.

- [ ] **Step 2.3: Implement the rule**

In `src/board/parser.py`, find the body of `enrich_minimal_task` (currently lines 41-81). Replace the entire function with:

```python
def enrich_minimal_task(path: Path, tasks_dir: Path) -> bool:
    """Auto-fill task frontmatter for minimal files.

    Idempotent. Two enrichment paths:

    1. Title-only files (any column): if title is set but id/created/updated
       are missing, fill those.
    2. Bare files in todo/ or backlog/: title is missing too, but the
       file's location signals user intent. Synthesize title = path.stem,
       then fill the rest.

    The id is the next available numeric slot across the entire vault
    (max numeric id of all parseable tasks + 1), zero-padded to three
    digits as a quoted string ("007"). Non-numeric ids in the corpus
    (e.g. "demo-001") are ignored when computing max.

    Concurrency: uses a module-level threading.Lock so two simultaneous
    enrichments allocate distinct sequential ids.

    Returns True iff the file was written.
    """
    with _ENRICH_LOCK:
        text = path.read_text(encoding="utf-8")
        post = frontmatter.loads(text)
        meta = dict(post.metadata or {})
        original_meta = dict(post.metadata or {})

        title = meta.get("title")
        if not title:
            # Recovery: in todo/ or backlog/, file location IS the task signal.
            # Synthesize title from filename stem.
            if _path_implies_task(path) and path.stem:
                meta["title"] = path.stem
            else:
                return False  # bare file outside task-implied folder — skip

        # At this point title is guaranteed to be set (either was set in
        # frontmatter, or synthesized just now).
        if not meta.get("id"):
            meta["id"] = _allocate_next_id(tasks_dir)
        if not meta.get("created"):
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            meta["created"] = mtime.strftime("%Y-%m-%d %H:%M")
        if not meta.get("updated"):
            meta["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Idempotency: only write back if something actually changed.
        if meta == original_meta:
            return False

        post.metadata = meta
        path.write_text(frontmatter.dumps(post), encoding="utf-8")
        return True


def _path_implies_task(path: Path) -> bool:
    """True if the file's direct parent is a column where bare files imply
    user intent (`todo/` or `backlog/` — the natural creation points).

    Direct children only — `tasks/todo/sub/foo.md` does not qualify because
    `path.parent.name` is "sub", not "todo". This matches the watcher's
    column whitelist scope.
    """
    return path.parent.name in ("todo", "backlog")
```

- [ ] **Step 2.4: Run test to verify it passes**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_enrich_minimal_task.py -v`
Expected: PASS — all existing tests + the new one.

- [ ] **Step 2.5: Commit**

```bash
git add src/board/parser.py tests/test_enrich_minimal_task.py
git commit -m "feat(parser): synthesize title from filename for bare todo/ files"
```

---

## Task 3: Coverage — backlog/ + edge cases

**Files:**
- Test: `<your-user>/projects/cc-assitant/tests/test_enrich_minimal_task.py`

- [ ] **Step 3.1: Write the failing tests**

Append to `tests/test_enrich_minimal_task.py`:

```python
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
```

- [ ] **Step 3.2: Run tests to verify they pass**

The Task 2 implementation should already cover all these cases:
- backlog/ — `_path_implies_task` returns True for `path.parent.name == "backlog"`.
- empty title — `if not title:` treats "" same as missing.
- existing title preserved — `if not title:` early-out doesn't fire.
- doing/review/blocked — `_path_implies_task` returns False.
- subfolder — `path.parent.name` is "sub" not "todo", so False.
- empty stem — `path.stem` is "", `if _path_implies_task(path) and path.stem:` short-circuits.

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_enrich_minimal_task.py -v`
Expected: PASS — all tests including 8 new ones.

- [ ] **Step 3.3: Commit**

```bash
git add tests/test_enrich_minimal_task.py
git commit -m "test(parser): cover backlog/empty-title/edge cases for filename-as-title"
```

---

## Task 4: Integration test — bare file in todo/ runs end-to-end

**Files:**
- Test: `<your-user>/projects/cc-assitant/tests/test_orchestrator.py`

- [ ] **Step 4.1: Write the failing test**

Append to `tests/test_orchestrator.py`:

```python
def test_run_cycle_processes_bare_file_in_todo(tmp_path):
    """End-to-end: a body-only file in todo/ becomes a fully-formed task
    on first cycle. Title is synthesized from the filename."""
    import asyncio
    import frontmatter
    from src.board.parser import PLACEHOLDER_TEXT

    tasks = _kanban(tmp_path)
    bare = tasks / "todo" / "集成测试.md"
    bare.write_text("回 ok 即可\n", encoding="utf-8")

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
    asyncio.run(orch.run_cycle(bare))

    # Find the file (may have moved out of todo/)
    candidates = (
        list((tasks / "doing").glob("*.md"))
        + list((tasks / "review").glob("*.md"))
        + list((tasks / "todo").glob("*.md"))
    )
    candidates = [c for c in candidates if c.name != ".gitkeep"]
    assert candidates, "task should still exist somewhere"
    final = candidates[0]

    text = final.read_text(encoding="utf-8")
    post = frontmatter.loads(text)
    assert post.metadata["title"] == "集成测试"
    assert str(post.metadata["id"]) == "001"
    # Cycle ran: AI reply + placeholder appended
    assert "ok" in text
    assert PLACEHOLDER_TEXT in text
    assert llm.chat.await_count == 1
```

- [ ] **Step 4.2: Run test to verify it passes**

The full chain (watcher → orchestrator.run_cycle → enrich_minimal_task → parse → LLM → append_conversation → append_placeholder) is already wired from prior plans. The new rule from Task 2 makes the bare file enrichable, so this should pass without further code changes.

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_orchestrator.py::test_run_cycle_processes_bare_file_in_todo -v`
Expected: PASS.

- [ ] **Step 4.3: Run the full suite**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest 2>&1 | tail -3`
Expected: PASS overall (modulo the pre-existing `test_config_loads_defaults` failure).

- [ ] **Step 4.4: Commit**

```bash
git add tests/test_orchestrator.py
git commit -m "test(orchestrator): end-to-end cycle on bare file in todo/"
```

---

## Task 5: Document the zero-frontmatter shortcut

**Files:**
- Modify: `<your-user>/projects/cc-assitant/tasks/README.md`

- [ ] **Step 5.1: Append docs**

Read the existing "最小寫法 (minimal task)" section in `tasks/README.md`. Below it, append:

```markdown

### 完全不寫 frontmatter(只在 `todo/` 和 `backlog/` 生效)

從 2026-05-02 起,如果文件存在 `tasks/todo/` 或 `tasks/backlog/` 下,連 `title:` 都可以省:

\`\`\`markdown
回 ok 即可
\`\`\`

(沒有 frontmatter,正文也可以隨意短)

存到 `tasks/todo/查詢小米股價.md` —— daemon 看到後會用**檔名(去掉 `.md`)當 title**,自動補 id/created/updated 寫回。

手機 Obsidian 工作流:**先進到 `todo/` 文件夾,點「+」新建 → 命名 → 直接寫正文 → 存**。零 frontmatter。

⚠ 此放寬**僅限 `todo/` 和 `backlog/`**。其他列(`doing/` `blocked/` `review/`)裡的裸文件仍會被拒絕,parser 會 log `task_malformed` —— 那些位置不該手動建文件,有問題會被看見。
```

- [ ] **Step 5.2: Commit**

```bash
git add tasks/README.md
git commit -m "docs(tasks): document zero-frontmatter mobile workflow for todo/"
```

---

## Self-review notes

**Spec coverage check** (against `2026-05-02-todo-folder-implies-task-design.md`):

- Title-from-filename in todo/ → Task 2.
- Same rule in backlog/ → Task 3 (test_enrich_synthesizes_title_from_filename_in_backlog).
- Empty title treated as missing → Task 3 (test_enrich_synthesizes_title_when_title_is_empty_string_in_todo).
- Existing title preserved → Task 3.
- Other columns stay strict → Task 3 (3 tests for doing/, review/, blocked/).
- Subfolder of todo/ doesn't qualify → Task 3.
- Empty filename stem edge case → Task 3.
- End-to-end integration → Task 4.
- Existing tests' intent preserved → Task 1 (refactor to doing/).
- Watcher unchanged → no task (correct: vault-root filtering already in place from `6eac7f6`).
- Orchestrator unchanged → no task (correct: existing enrich call sites pick up new rule for free).
- Parser strict gate unchanged → no task (correct: `_REQUIRED_FRONTMATTER_FIELDS = ("title",)` still enforced; enrichment ensures title is set before parse).
- README docs → Task 5.

**Placeholder scan:** None. Each step has concrete code or commands. The only embedded markdown in Task 5 escapes triple backticks because this plan is itself markdown.

**Type consistency:** `enrich_minimal_task(path: Path, tasks_dir: Path) -> bool` signature unchanged (interface back-compat). New `_path_implies_task(path: Path) -> bool` is private. `path.stem`, `path.parent.name` are both standard pathlib attributes — no custom types introduced. `meta == original_meta` comparison uses dict equality — both are plain dicts.

**Edge case verification:**
- `original_meta = dict(post.metadata or {})` — when frontmatter is None (no `---` block at all), `post.metadata` is `{}`, so `dict({})` = `{}`. Comparison works.
- `if meta == original_meta: return False` — handles the case where title was set, all other fields were set, and nothing actually needed changing. Idempotent.
- After title synthesis, `meta["title"]` is set but `original_meta["title"]` is not (or is empty). So `meta != original_meta`, write happens. Correct.
