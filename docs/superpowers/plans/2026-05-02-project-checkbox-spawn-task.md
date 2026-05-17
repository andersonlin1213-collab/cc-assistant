# Project Card Checkbox Spawns Task Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ticking a `- [ ]` under `## 下一步` of any project card spawns a task in `tasks/todo/` and rewrites the line with a wikilink.

**Architecture:** New module `src/board/project_handler.py` with pure functions for parse / diff / spawn / rewrite. Watcher allows `tasks/projects/<slug>.md` events through (currently filtered). The factory's `on_task_change` callback routes events: project cards → `process_project_card`, columns → `orchestrator.run_cycle`. State diff against `logs/project_checkbox_state.json` ensures first-scan baselines without retroactive spawning.

**Tech Stack:** Python 3.13, `python-frontmatter`, pytest, `re`, `json`, `threading`.

**Spec:** `docs/superpowers/specs/2026-05-02-project-checkbox-spawn-task-design.md`

---

## File Plan

**New files:**
- `src/board/project_handler.py` — module with `process_project_card`, `parse_next_actions`, `diff_against_cache`, `spawn_task_from_item`, `rewrite_card_line`, `ChecklistItem` dataclass.
- `tests/test_project_handler.py` — 13 unit tests.

**Modified files:**
- `src/dispatcher/watcher.py` — drop `/projects/` and `\projects\` from `_IGNORE_PATH_FRAGMENTS`; add `_PROJECT_FOLDER_NAME = "projects"` to whitelist alongside `_COLUMN_NAMES`.
- `src/agent/factory.py` — wrap `on_task_change` callback with a path-based router.
- `src/agent/orchestrator.py` — extend startup replay to baseline project card states (no spawning).
- `tests/test_watcher.py` — flip the `test_projects_folder_is_ignored` test to assert direct-child project cards pass through.
- `tests/test_orchestrator.py` — 5 integration tests for the spawn flow.
- `tasks/README.md` — append "勾選派單" workflow note.

---

## Task 1: Watcher allows project card events through

**Files:**
- Modify: `<your-user>/projects/cc-assitant/src/dispatcher/watcher.py`
- Test: `<your-user>/projects/cc-assitant/tests/test_watcher.py`

- [ ] **Step 1.1: Update the existing test that asserts projects/ is ignored**

The current `test_projects_folder_is_ignored` (in `tests/test_watcher.py`, around line 209) asserts `_is_ignored(tasks/projects/evernote.md) is True`. After this change, project cards must pass through. Replace that test with the inverse assertion plus coverage for the still-ignored cases (sub-subfolders, vault root).

In `tests/test_watcher.py`, replace:

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

with:

```python
def test_projects_direct_child_card_passes(tmp_path):
    """tasks/projects/<slug>.md must pass through — those events go to
    project_handler (not orchestrator). Sub-subfolders still ignored."""
    from src.dispatcher.watcher import _is_ignored

    p = tmp_path / "tasks" / "projects" / "evernote.md"
    assert _is_ignored(p) is False

    # Sub-subfolder under projects/ is ignored (not a project card)
    sub = tmp_path / "tasks" / "projects" / "drafts" / "wip.md"
    assert _is_ignored(sub) is True
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_watcher.py::test_projects_direct_child_card_passes -v`
Expected: FAIL — current `_is_ignored` returns True for `tasks/projects/evernote.md` due to the `/projects/` fragment match.

- [ ] **Step 1.3: Update the watcher**

In `<your-user>/projects/cc-assitant/src/dispatcher/watcher.py`:

3a. Replace the `_IGNORE_PATH_FRAGMENTS` tuple (lines 17-28) with:

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
)
```

(Removed `/projects/` and `\projects\`.)

3b. After the existing `_COLUMN_NAMES = frozenset(...)` line, add:

```python
_PROJECT_FOLDER_NAME = "projects"
```

3c. In `_is_ignored`, after the `if parent_name in _COLUMN_NAMES: return False` line, add:

```python
    if parent_name == _PROJECT_FOLDER_NAME:
        # tasks/projects/<slug>.md — project cards. Routed to project_handler
        # by the factory's on_task_change wrapper, not orchestrator.run_cycle.
        return False
```

So the resulting `_is_ignored` becomes:

```python
def _is_ignored(path: Path) -> bool:
    p = str(path)
    if any(frag in p for frag in _IGNORE_PATH_FRAGMENTS):
        return True
    if " (conflict " in path.name:
        return True
    parent_name = path.parent.name
    if parent_name in _COLUMN_NAMES:
        return False
    if parent_name == _PROJECT_FOLDER_NAME:
        return False
    grandparent = path.parent.parent
    if grandparent != path.parent and grandparent.name == "done":
        return False
    return True
```

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_watcher.py -v`
Expected: PASS — all watcher tests including the new direct-child assertion.

- [ ] **Step 1.5: Commit**

```bash
git add src/dispatcher/watcher.py tests/test_watcher.py
git commit -m "feat(watcher): allow tasks/projects/<slug>.md events through"
```

---

## Task 2: Parse `## 下一步` checklist

**Files:**
- Create: `<your-user>/projects/cc-assitant/src/board/project_handler.py`
- Test: `<your-user>/projects/cc-assitant/tests/test_project_handler.py`

- [ ] **Step 2.1: Write the failing tests**

Create `tests/test_project_handler.py`:

```python
from pathlib import Path

import pytest

from src.board.project_handler import ChecklistItem, parse_next_actions


def test_parse_extracts_checklist_items():
    """`- [ ]` and `- [x]` lines under `## 下一步` are extracted in order."""
    text = """
# Some Project

## 一句話
A description.

## 下一步 (Next actions)
- [ ] First action
- [x] Already done
- [ ] Second action

## 決策記錄
- 不该被收
"""
    items = parse_next_actions(text)
    assert len(items) == 3
    assert items[0] == ChecklistItem(text="First action", checked=False, line_number=8)
    assert items[1] == ChecklistItem(text="Already done", checked=True, line_number=9)
    assert items[2] == ChecklistItem(text="Second action", checked=False, line_number=10)


def test_parse_returns_empty_when_section_missing():
    """No `## 下一步` heading → empty list, no error."""
    text = "# A project\n\n## 决策\n- [x] something\n"
    assert parse_next_actions(text) == []


def test_parse_stops_at_next_h2():
    """Items under sub-headings or after the next `## ` are not included."""
    text = """## 下一步 (Next actions)
- [ ] keep this
- [x] and this

## 决策记录
- [x] do not include this
"""
    items = parse_next_actions(text)
    assert len(items) == 2
    assert all(i.text != "do not include this" for i in items)


def test_parse_ignores_subheadings_within_section():
    """`### subheading` inside `## 下一步` doesn't terminate the section,
    but checklist items continue to be picked from non-heading lines."""
    text = """## 下一步 (Next actions)
- [ ] top-level item

### A sub-grouping
- [ ] sub-item still counts
"""
    items = parse_next_actions(text)
    assert len(items) == 2
    assert items[0].text == "top-level item"
    assert items[1].text == "sub-item still counts"


def test_parse_strips_whitespace_from_item_text():
    """Leading/trailing spaces in item text are normalized."""
    text = """## 下一步 (Next actions)
- [ ]    spaced text   
"""
    items = parse_next_actions(text)
    assert items[0].text == "spaced text"
```

- [ ] **Step 2.2: Run tests to verify they fail**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_project_handler.py -v`
Expected: FAIL — `ImportError: cannot import name 'ChecklistItem' from 'src.board.project_handler'` (module doesn't exist yet).

- [ ] **Step 2.3: Create the module skeleton with the parser**

Create `src/board/project_handler.py`:

```python
"""Project card checklist handler.

Detects user-driven `- [ ]` → `- [x]` transitions in `## 下一步 (Next actions)`
sections of `tasks/projects/<slug>.md` cards, spawns a corresponding task,
and rewrites the line with a wikilink.

Intentionally does NOT call the LLM. Project card events are pure file
mutations — diff cache, spawn task scaffold, update card.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ChecklistItem:
    """A single `- [ ]` / `- [x]` line under `## 下一步`."""
    text: str           # content after the `- [x]` / `- [ ]` prefix, trimmed
    checked: bool       # True if `[x]`, False if `[ ]`
    line_number: int    # 1-based line index in the source for in-place edits


_NEXT_ACTIONS_HEADING = re.compile(r"^##\s+下一步")
_OTHER_H2 = re.compile(r"^##\s+")
_CHECKLIST_LINE = re.compile(r"^\s*-\s+\[(?P<state>[ xX])\]\s+(?P<text>.*?)\s*$")


def parse_next_actions(card_text: str) -> list[ChecklistItem]:
    """Extract checklist items from the `## 下一步` section.

    The section starts at any line beginning with `## 下一步` (heading-prefix
    match — tolerant of `## 下一步 (Next actions)` / `## 下一步` / etc.) and
    runs until the next `## ` heading at the same level. Items inside `###`
    sub-headings within that range still count.

    Returns items in the order they appear. line_number is 1-based.
    """
    items: list[ChecklistItem] = []
    in_section = False
    for idx, raw_line in enumerate(card_text.splitlines(), start=1):
        if _NEXT_ACTIONS_HEADING.match(raw_line):
            in_section = True
            continue
        if not in_section:
            continue
        # End of section: next H2 (`## anything`) — but NOT H3+ (`### ...`).
        if _OTHER_H2.match(raw_line) and not raw_line.startswith("##  "):
            # match for `## ` at start; we already handled `## 下一步` above
            in_section = False
            continue
        m = _CHECKLIST_LINE.match(raw_line)
        if m:
            items.append(
                ChecklistItem(
                    text=m.group("text").strip(),
                    checked=m.group("state").lower() == "x",
                    line_number=idx,
                )
            )
    return items
```

- [ ] **Step 2.4: Run tests to verify they pass**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_project_handler.py -v`
Expected: PASS — all 5 parse tests.

- [ ] **Step 2.5: Commit**

```bash
git add src/board/project_handler.py tests/test_project_handler.py
git commit -m "feat(project-handler): parse `## 下一步` checklist into ChecklistItem list"
```

---

## Task 3: State file IO + diff logic

**Files:**
- Modify: `<your-user>/projects/cc-assitant/src/board/project_handler.py`
- Test: `<your-user>/projects/cc-assitant/tests/test_project_handler.py`

- [ ] **Step 3.1: Write the failing tests**

Append to `tests/test_project_handler.py`:

```python
import json
import threading

from src.board.project_handler import diff_against_cache


def _state_path(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return logs / "project_checkbox_state.json"


def test_diff_first_scan_returns_empty_and_populates_cache(tmp_path):
    """No cache entry for slug → returns []; cache file gets populated."""
    state = _state_path(tmp_path)
    items = [
        ChecklistItem(text="A", checked=False, line_number=1),
        ChecklistItem(text="B", checked=True, line_number=2),
    ]
    spawn = diff_against_cache("alpha-project", items, state)
    assert spawn == []
    data = json.loads(state.read_text(encoding="utf-8"))
    assert data["alpha-project"]["unchecked_items"] == ["A"]
    assert data["alpha-project"]["checked_items"] == ["B"]


def test_diff_returns_newly_checked_items(tmp_path):
    """Item that was unchecked in cache and is now checked → in spawn list."""
    state = _state_path(tmp_path)
    state.write_text(
        json.dumps({"alpha-project": {"unchecked_items": ["A"], "checked_items": []}}),
        encoding="utf-8",
    )
    items = [ChecklistItem(text="A", checked=True, line_number=1)]
    spawn = diff_against_cache("alpha-project", items, state)
    assert len(spawn) == 1 and spawn[0].text == "A"
    data = json.loads(state.read_text(encoding="utf-8"))
    assert data["alpha-project"]["checked_items"] == ["A"]
    assert data["alpha-project"]["unchecked_items"] == []


def test_diff_no_spawn_on_undo(tmp_path):
    """Item was checked, now unchecked → NOT in spawn list (cache updated)."""
    state = _state_path(tmp_path)
    state.write_text(
        json.dumps({"alpha-project": {"unchecked_items": [], "checked_items": ["A"]}}),
        encoding="utf-8",
    )
    items = [ChecklistItem(text="A", checked=False, line_number=1)]
    spawn = diff_against_cache("alpha-project", items, state)
    assert spawn == []
    data = json.loads(state.read_text(encoding="utf-8"))
    assert data["alpha-project"]["unchecked_items"] == ["A"]


def test_diff_no_spawn_on_added_unchecked(tmp_path):
    """New `[ ]` line added → cache updated, not in spawn list."""
    state = _state_path(tmp_path)
    state.write_text(
        json.dumps({"alpha-project": {"unchecked_items": ["A"], "checked_items": []}}),
        encoding="utf-8",
    )
    items = [
        ChecklistItem(text="A", checked=False, line_number=1),
        ChecklistItem(text="B", checked=False, line_number=2),
    ]
    spawn = diff_against_cache("alpha-project", items, state)
    assert spawn == []
    data = json.loads(state.read_text(encoding="utf-8"))
    assert sorted(data["alpha-project"]["unchecked_items"]) == ["A", "B"]


def test_diff_no_spawn_on_text_edit(tmp_path):
    """Old text removed, new text added as unchecked → not in spawn list."""
    state = _state_path(tmp_path)
    state.write_text(
        json.dumps({"alpha-project": {"unchecked_items": ["old text"], "checked_items": []}}),
        encoding="utf-8",
    )
    items = [ChecklistItem(text="new text", checked=False, line_number=1)]
    spawn = diff_against_cache("alpha-project", items, state)
    assert spawn == []


def test_diff_state_file_concurrent_writes_serialize(tmp_path):
    """Two threads writing different slugs end up with both persisted."""
    state = _state_path(tmp_path)
    items_a = [ChecklistItem(text="A", checked=False, line_number=1)]
    items_b = [ChecklistItem(text="B", checked=False, line_number=1)]

    def worker(slug, items):
        diff_against_cache(slug, items, state)

    t1 = threading.Thread(target=worker, args=("p1", items_a))
    t2 = threading.Thread(target=worker, args=("p2", items_b))
    t1.start(); t2.start()
    t1.join(); t2.join()

    data = json.loads(state.read_text(encoding="utf-8"))
    assert "p1" in data
    assert "p2" in data
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_project_handler.py -v -k "diff"`
Expected: FAIL — `cannot import name 'diff_against_cache'`.

- [ ] **Step 3.3: Implement diff + state file IO**

Append to `src/board/project_handler.py`:

```python
import json
import threading
from pathlib import Path

_STATE_LOCK = threading.Lock()


def diff_against_cache(
    slug: str, current: list[ChecklistItem], cache_path: Path
) -> list[ChecklistItem]:
    """Diff current checklist against the cache, return items to spawn.

    A "spawn" is any item that is checked NOW but was unchecked LAST.
    The cache is updated in-place to reflect the current state regardless
    of the spawn result. First encounter (no cache entry for slug) baselines
    the state and returns an empty spawn list — never retro-spawn.

    Item identity = stripped text. Reorder doesn't matter; an edit that
    changes text is treated as remove + add (not a transition).
    """
    with _STATE_LOCK:
        cache = _load_cache(cache_path)

        prev_entry = cache.get(slug)
        cur_unchecked = [i.text for i in current if not i.checked]
        cur_checked = [i.text for i in current if i.checked]

        if prev_entry is None:
            # First encounter: baseline only.
            cache[slug] = {
                "unchecked_items": cur_unchecked,
                "checked_items": cur_checked,
            }
            _save_cache(cache_path, cache)
            return []

        prev_unchecked = set(prev_entry.get("unchecked_items", []))
        prev_checked = set(prev_entry.get("checked_items", []))

        spawn: list[ChecklistItem] = []
        for item in current:
            if item.checked and item.text in prev_unchecked:
                # Was unchecked before, now checked → spawn.
                spawn.append(item)

        cache[slug] = {
            "unchecked_items": cur_unchecked,
            "checked_items": cur_checked,
        }
        _save_cache(cache_path, cache)
        return spawn


def _load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Corrupt or unreadable — start fresh; this only loses the in-memory
        # snapshot, project cards will be re-baselined on next encounter.
        return {}


def _save_cache(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
```

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_project_handler.py -v`
Expected: PASS — all 5 parse + 6 diff tests.

- [ ] **Step 3.5: Commit**

```bash
git add src/board/project_handler.py tests/test_project_handler.py
git commit -m "feat(project-handler): state diff against logs/project_checkbox_state.json"
```

---

## Task 4: Filename derivation

**Files:**
- Modify: `<your-user>/projects/cc-assitant/src/board/project_handler.py`
- Test: `<your-user>/projects/cc-assitant/tests/test_project_handler.py`

- [ ] **Step 4.1: Write the failing tests**

Append to `tests/test_project_handler.py`:

```python
from src.board.project_handler import derive_task_filename


def test_derive_filename_chinese_text(tmp_path):
    """Chinese item text is preserved as-is in the filename (spaces stripped)."""
    todo_dir = tmp_path / "tasks" / "todo"
    todo_dir.mkdir(parents=True)
    name = derive_task_filename("接入第三方 API 拿凭证模板", todo_dir)
    assert name == "接入第三方API拿凭证模板.md"


def test_derive_filename_sanitizes_special_chars(tmp_path):
    """Filesystem-illegal chars become `-`."""
    todo_dir = tmp_path / "tasks" / "todo"
    todo_dir.mkdir(parents=True)
    name = derive_task_filename('改/写: 评估*?"<>|文档', todo_dir)
    # Each illegal char (/ : * ? " < > |) → "-"; spaces stripped.
    assert "/" not in name and ":" not in name and "*" not in name
    assert name.endswith(".md")


def test_derive_filename_collision_appends_suffix(tmp_path):
    """If `<text>.md` exists, suffix with `-2`, `-3`, ..."""
    todo_dir = tmp_path / "tasks" / "todo"
    todo_dir.mkdir(parents=True)
    (todo_dir / "重复.md").write_text("x", encoding="utf-8")
    name = derive_task_filename("重复", todo_dir)
    assert name == "重复-2.md"

    (todo_dir / "重复-2.md").write_text("x", encoding="utf-8")
    name2 = derive_task_filename("重复", todo_dir)
    assert name2 == "重复-3.md"


def test_derive_filename_truncates_at_50_chars(tmp_path):
    """Long item text → truncated stem at 50 chars (plus `.md`)."""
    todo_dir = tmp_path / "tasks" / "todo"
    todo_dir.mkdir(parents=True)
    long_text = "a" * 100
    name = derive_task_filename(long_text, todo_dir)
    stem = name[:-3]  # strip ".md"
    assert len(stem) <= 50
```

- [ ] **Step 4.2: Run tests to verify they fail**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_project_handler.py -v -k derive_filename`
Expected: FAIL — `cannot import name 'derive_task_filename'`.

- [ ] **Step 4.3: Implement derive_task_filename**

Append to `src/board/project_handler.py`:

```python
_ILLEGAL_FS_CHARS = '/:\\*?"<>|'
_FILENAME_MAX_STEM = 50


def derive_task_filename(item_text: str, todo_dir: Path) -> str:
    """Convert item text into a unique `.md` filename inside `todo_dir`.

    - Whitespace is removed (Chinese-friendly).
    - Filesystem-illegal chars (`/ : \\ * ? " < > |`) become `-`.
    - Stem capped at 50 chars.
    - Collisions append `-2`, `-3`, ... until unique.
    """
    stem = _sanitize_stem(item_text)
    if not stem:
        stem = "task"
    if len(stem) > _FILENAME_MAX_STEM:
        stem = stem[:_FILENAME_MAX_STEM]

    candidate = f"{stem}.md"
    if not (todo_dir / candidate).exists():
        return candidate

    counter = 2
    while True:
        candidate = f"{stem}-{counter}.md"
        if not (todo_dir / candidate).exists():
            return candidate
        counter += 1


def _sanitize_stem(text: str) -> str:
    out = []
    for ch in text:
        if ch.isspace():
            continue
        if ch in _ILLEGAL_FS_CHARS:
            out.append("-")
        else:
            out.append(ch)
    return "".join(out)
```

- [ ] **Step 4.4: Run tests to verify they pass**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_project_handler.py -v`
Expected: PASS.

- [ ] **Step 4.5: Commit**

```bash
git add src/board/project_handler.py tests/test_project_handler.py
git commit -m "feat(project-handler): derive_task_filename with sanitization + collision suffix"
```

---

## Task 5: Spawn task + rewrite project card

**Files:**
- Modify: `<your-user>/projects/cc-assitant/src/board/project_handler.py`
- Test: `<your-user>/projects/cc-assitant/tests/test_project_handler.py`

- [ ] **Step 5.1: Write the failing tests**

Append to `tests/test_project_handler.py`:

```python
from src.board.project_handler import spawn_task_from_item, rewrite_card_line


def test_spawn_creates_task_file_with_correct_frontmatter(tmp_path):
    """spawn_task_from_item writes a tasks/todo/<filename>.md with the right
    frontmatter and body."""
    tasks = tmp_path / "tasks"
    (tasks / "todo").mkdir(parents=True)
    item = ChecklistItem(text="接入第三方 API", checked=True, line_number=10)

    new_path = spawn_task_from_item(item, "alpha-project", tasks)

    assert new_path.exists()
    assert new_path.parent == tasks / "todo"
    text = new_path.read_text(encoding="utf-8")
    # Frontmatter contains key fields
    assert "title: 接入第三方 API" in text
    assert "project: alpha-project" in text
    assert "auto_approve: false" in text
    # Body references the source project card via wikilink
    assert "[[alpha-project]]" in text
    # Has the standard task body sections
    assert "## 任务描述" in text
    assert "## 对话" in text


def test_spawn_returns_path_for_wikilink(tmp_path):
    """The path returned exposes the filename stem used in the rewrite step."""
    tasks = tmp_path / "tasks"
    (tasks / "todo").mkdir(parents=True)
    item = ChecklistItem(text="一件事", checked=True, line_number=1)

    new_path = spawn_task_from_item(item, "p", tasks)

    assert new_path.stem  # non-empty stem
    assert new_path.suffix == ".md"


def test_rewrite_line_replaces_checked_box_with_wikilink(tmp_path):
    """rewrite_card_line edits the `- [x] <text>` line to add `[[link]]` prefix."""
    card = tmp_path / "card.md"
    card.write_text(
        "## 下一步 (Next actions)\n"
        "- [ ] 第一件\n"
        "- [x] 接入第三方 API\n"
        "- [ ] 第三件\n",
        encoding="utf-8",
    )
    item = ChecklistItem(text="接入第三方 API", checked=True, line_number=3)

    rewrite_card_line(card, item, task_filename="接入第三方API")

    text = card.read_text(encoding="utf-8")
    assert "- [x] [[接入第三方API]] 接入第三方 API" in text
    # Other lines untouched
    assert "- [ ] 第一件" in text
    assert "- [ ] 第三件" in text


def test_rewrite_line_is_idempotent(tmp_path):
    """If line already has `[[wikilink]]` prefix, no change."""
    card = tmp_path / "card.md"
    original = (
        "## 下一步 (Next actions)\n"
        "- [x] [[接入第三方API]] 接入第三方 API\n"
    )
    card.write_text(original, encoding="utf-8")
    item = ChecklistItem(text="接入第三方 API", checked=True, line_number=2)

    rewrite_card_line(card, item, task_filename="接入第三方API")

    assert card.read_text(encoding="utf-8") == original
```

- [ ] **Step 5.2: Run tests to verify they fail**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_project_handler.py -v -k "spawn or rewrite"`
Expected: FAIL — neither function exists yet.

- [ ] **Step 5.3: Implement spawn + rewrite**

Append to `src/board/project_handler.py`:

```python
def spawn_task_from_item(item: ChecklistItem, slug: str, tasks_dir: Path) -> Path:
    """Create tasks/todo/<derived>.md with frontmatter + body for the item."""
    todo_dir = tasks_dir / "todo"
    todo_dir.mkdir(parents=True, exist_ok=True)

    filename = derive_task_filename(item.text, todo_dir)
    path = todo_dir / filename

    body = (
        f"---\n"
        f"title: {item.text}\n"
        f"project: {slug}\n"
        f"auto_approve: false\n"
        f"---\n\n"
        f"## 任务描述\n"
        f"{item.text}\n\n"
        f"(从项目卡 [[{slug}]] 派单)\n\n"
        f"## 对话\n"
    )
    path.write_text(body, encoding="utf-8")
    return path


def rewrite_card_line(path: Path, item: ChecklistItem, task_filename: str) -> None:
    """Rewrite `- [x] <text>` → `- [x] [[<filename_stem>]] <text>` on the
    matching line in the project card. Idempotent: if the wikilink prefix is
    already present, no write happens.

    `task_filename` may be either bare stem (`接入第三方API`) or with `.md`
    suffix; the stem is used in the wikilink.
    """
    stem = task_filename[:-3] if task_filename.endswith(".md") else task_filename
    wikilink_prefix = f"[[{stem}]]"

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    target_idx = item.line_number - 1
    if target_idx < 0 or target_idx >= len(lines):
        return

    line = lines[target_idx]
    # Idempotency: skip if wikilink already there.
    if wikilink_prefix in line:
        return

    # Replace `- [x] <text>` (preserving any leading whitespace, the [x] case,
    # and trailing newline) with `- [x] [[stem]] <text>`.
    m = _CHECKLIST_LINE.match(line.rstrip("\n").rstrip("\r"))
    if not m:
        return
    state = m.group("state")
    new_line = f"- [{state}] {wikilink_prefix} {item.text}"
    if line.endswith("\r\n"):
        new_line += "\r\n"
    elif line.endswith("\n"):
        new_line += "\n"
    lines[target_idx] = new_line

    path.write_text("".join(lines), encoding="utf-8")
```

- [ ] **Step 5.4: Run tests to verify they pass**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_project_handler.py -v`
Expected: PASS — all 13 unit tests.

- [ ] **Step 5.5: Commit**

```bash
git add src/board/project_handler.py tests/test_project_handler.py
git commit -m "feat(project-handler): spawn task + rewrite card line with wikilink"
```

---

## Task 6: process_project_card glue + factory routing

**Files:**
- Modify: `<your-user>/projects/cc-assitant/src/board/project_handler.py`
- Modify: `<your-user>/projects/cc-assitant/src/agent/factory.py`
- Test: `<your-user>/projects/cc-assitant/tests/test_orchestrator.py`

- [ ] **Step 6.1: Write the failing integration test**

Append to `tests/test_orchestrator.py`:

```python
def test_project_card_checkbox_click_spawns_task_and_updates_card(tmp_path):
    """E2E: tick a `[x]` in `## 下一步` → file appears in tasks/todo/ and
    project card line gains a `[[wikilink]]` prefix.

    First scan baselines without spawning, then a second scan with the box
    flipped triggers the spawn.
    """
    from contextlib import contextmanager
    from src.board.project_handler import process_project_card

    tasks = _kanban(tmp_path)
    projects = tasks / "projects"
    projects.mkdir()
    logs = tmp_path / "logs"
    logs.mkdir()

    @contextmanager
    def _ss():
        yield

    card = projects / "demo.md"
    card.write_text(
        "## 下一步 (Next actions)\n"
        "- [ ] 第一件事\n"
        "- [ ] 第二件事\n",
        encoding="utf-8",
    )

    # First scan — baseline only.
    process_project_card(card, tasks, logs, _ss)
    assert list((tasks / "todo").glob("*.md")) == [], "no tasks should spawn on first scan"

    # User ticks the first box.
    card.write_text(
        "## 下一步 (Next actions)\n"
        "- [x] 第一件事\n"
        "- [ ] 第二件事\n",
        encoding="utf-8",
    )

    process_project_card(card, tasks, logs, _ss)

    spawned = list((tasks / "todo").glob("*.md"))
    assert len(spawned) == 1, f"expected 1 task file, got {[p.name for p in spawned]}"
    spawned_path = spawned[0]

    text = spawned_path.read_text(encoding="utf-8")
    assert "title: 第一件事" in text
    assert "project: demo" in text

    card_text = card.read_text(encoding="utf-8")
    assert "[[" in card_text
    assert "第一件事" in card_text
```

- [ ] **Step 6.2: Run test to verify it fails**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_orchestrator.py::test_project_card_checkbox_click_spawns_task_and_updates_card -v`
Expected: FAIL — `cannot import name 'process_project_card'`.

- [ ] **Step 6.3: Implement process_project_card**

Append to `src/board/project_handler.py`:

```python
def process_project_card(
    card_path: Path,
    tasks_dir: Path,
    logs_dir: Path,
    suppress_self,
) -> None:
    """Diff the card's `## 下一步` checklist against cache, spawn tasks
    for newly-checked items, rewrite those lines with wikilinks. Pure file
    mutations — no LLM call.

    `suppress_self` is the watcher's suppression context manager (callable
    returning a context manager). Wraps the daemon's own writes so they
    don't re-trigger the watcher.

    `card_path` is `tasks/projects/<slug>.md`. The slug is derived from
    `card_path.stem`.
    """
    slug = card_path.stem
    state_path = logs_dir / "project_checkbox_state.json"

    try:
        text = card_path.read_text(encoding="utf-8")
    except OSError:
        return

    items = parse_next_actions(text)
    spawn_list = diff_against_cache(slug, items, state_path)

    if not spawn_list:
        return

    with suppress_self():
        for item in spawn_list:
            new_path = spawn_task_from_item(item, slug, tasks_dir)
            rewrite_card_line(card_path, item, new_path.stem)
```

- [ ] **Step 6.4: Run test to verify it passes**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_orchestrator.py::test_project_card_checkbox_click_spawns_task_and_updates_card -v`
Expected: PASS.

- [ ] **Step 6.5: Wire the routing in factory**

In `<your-user>/projects/cc-assitant/src/agent/factory.py`, find the `coordinator.set_callbacks(...)` block in `build_orchestrator_and_coordinator` (around line 50). Replace:

```python
    coordinator.set_callbacks(
        on_task_change=lambda p: _run_async(orchestrator.run_cycle(p)),
        on_poll=lambda: _run_async(orchestrator.on_poll()),
    )
```

with:

```python
    from src.board.project_handler import process_project_card

    def _routed_on_change(path):
        # Route project card events to project_handler (no LLM); everything
        # else goes to the orchestrator's run_cycle.
        if path.parent.name == "projects" and path.parent.parent == tasks_dir:
            try:
                process_project_card(
                    path,
                    tasks_dir=tasks_dir,
                    logs_dir=logs_dir,
                    suppress_self=coordinator.suppress_self,
                )
            except Exception:  # pylint: disable=broad-except
                # Project card errors must not kill the watcher thread.
                import logging
                logging.getLogger(__name__).exception(
                    "project_handler failed for %s", path
                )
            return
        _run_async(orchestrator.run_cycle(path))

    coordinator.set_callbacks(
        on_task_change=_routed_on_change,
        on_poll=lambda: _run_async(orchestrator.on_poll()),
    )
```

- [ ] **Step 6.6: Run the full suite**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest 2>&1 | tail -3`
Expected: PASS overall (modulo the pre-existing `test_config_loads_defaults` failure).

- [ ] **Step 6.7: Commit**

```bash
git add src/board/project_handler.py src/agent/factory.py tests/test_orchestrator.py
git commit -m "feat(factory): route project card events to project_handler not orchestrator"
```

---

## Task 7: Replay scan baselines project cards on startup

**Files:**
- Modify: `<your-user>/projects/cc-assitant/src/agent/orchestrator.py`
- Test: `<your-user>/projects/cc-assitant/tests/test_orchestrator.py`

**Why:** Without this, the very first time daemon scans a project card is when the user clicks a checkbox after starting the daemon. If the cache is empty at that moment, `diff_against_cache` would baseline (no spawn) — but then the user's NEW click is lost because we treated this as "first encounter". Result: the click does nothing. Instead, baseline ALL existing cards at startup so the first user click is a real diff.

- [ ] **Step 7.1: Write the failing test**

Append to `tests/test_orchestrator.py`:

```python
def test_startup_replay_baselines_existing_project_cards(tmp_path):
    """On daemon startup, all existing project cards have their checklists
    baselined into the state file — without spawning any tasks."""
    import asyncio
    import json

    tasks = _kanban(tmp_path)
    projects = tasks / "projects"
    projects.mkdir()
    (projects / "alpha.md").write_text(
        "## 下一步 (Next actions)\n- [ ] thing-a\n- [x] already-done\n",
        encoding="utf-8",
    )
    (projects / "beta.md").write_text(
        "## 下一步 (Next actions)\n- [ ] thing-b\n",
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

    # State file populated for both slugs
    state = json.loads((logs / "project_checkbox_state.json").read_text(encoding="utf-8"))
    assert "alpha" in state
    assert "beta" in state
    assert state["alpha"]["unchecked_items"] == ["thing-a"]
    assert state["alpha"]["checked_items"] == ["already-done"]

    # No tasks were spawned — all items existed before, none transitioned.
    assert list((tasks / "todo").glob("*.md")) == []
    # LLM not called.
    assert llm.chat.await_count == 0
```

- [ ] **Step 7.2: Run test to verify it fails**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_orchestrator.py::test_startup_replay_baselines_existing_project_cards -v`
Expected: FAIL — replay doesn't touch project cards yet, so the state file never gets created.

- [ ] **Step 7.3: Extend replay_pending_intents**

In `<your-user>/projects/cc-assitant/src/agent/orchestrator.py`, find `replay_pending_intents` (around line 240). Right BEFORE the `if processed > 0:` log line at the end of the function, insert:

```python
        # Baseline project card states so the first post-startup user click
        # is a real diff (not a "first encounter" no-op).
        from src.board.project_handler import process_project_card
        projects_dir = self.tasks_dir / "projects"
        if projects_dir.exists():
            for card_path in sorted(projects_dir.glob("*.md")):
                with self.suppress_self():
                    try:
                        process_project_card(
                            card_path,
                            tasks_dir=self.tasks_dir,
                            logs_dir=self.logger.logs_dir,
                            suppress_self=self.suppress_self,
                        )
                    except Exception as e:  # pylint: disable=broad-except
                        self.logger.log_system(
                            action="replay_project_card_failed",
                            detail=f"path={card_path} err={e}",
                            status="error",
                        )
```

(Note: `self.logger.logs_dir` should already exist as the `StructuredLogger` has the logs dir. If not, use `self.tasks_dir.parent / "logs"` or pass `logs_dir` from the constructor — check the existing `Orchestrator.__init__` for how `logs_dir` is stored, and use that. If `Orchestrator` doesn't keep `logs_dir` directly, use `self.logger.path.parent` since `StructuredLogger` likely opens `logs/agent.jsonl`.)

If `Orchestrator` doesn't expose `logs_dir`, the cleanest fix is to add it. Inspect `src/agent/orchestrator.py:__init__` around lines 51-71 to see what's stored. If `logs_dir` isn't an instance attribute, store it: `self.logs_dir = logs_dir` in `__init__`. Then use `self.logs_dir` in the replay block above.

- [ ] **Step 7.4: Run test to verify it passes**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_orchestrator.py::test_startup_replay_baselines_existing_project_cards -v`
Expected: PASS.

- [ ] **Step 7.5: Run the full suite**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest 2>&1 | tail -3`
Expected: PASS overall.

- [ ] **Step 7.6: Commit**

```bash
git add src/agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): baseline project card states on startup replay"
```

---

## Task 8: Document the checkbox-spawn workflow

**Files:**
- Modify: `<your-user>/projects/cc-assitant/tasks/README.md`

- [ ] **Step 8.1: Append docs**

Append to `tasks/README.md`:

```markdown

## 從項目卡派單(勾選 checkbox)

從 2026-05-02 起,項目卡 `tasks/projects/<slug>.md` 的 `## 下一步 (Next actions)` 章節下,**點任意 `- [ ]` checkbox 變成 `- [x]`**,daemon 會自動:

1. 在 `tasks/todo/<檔名>.md` 建一個新 task,frontmatter 自動帶 `project: <slug>`
2. 把項目卡那一行改成 `- [x] [[檔名]] 原本文字`(可點 wikilink 跳到 task)
3. 觸發 task pipeline,daemon 跑一輪 LLM,給你 [AI] 回覆 + placeholder

⚠ 規則:
- **只在 `## 下一步` 章節下**生效。其他章節(`決策記錄` `待解決的問題` 等)的 checkbox 不會被識別為派單動作。
- **章節 heading 必須以 `## 下一步` 開頭** —— 改成 `## TODO` 之類的就不認了。
- **新加 `- [ ]`、撤銷 `[x]→[ ]`、編輯文字、重新排序** —— 全部不觸發,只更新 cache。
- **首次掃描**(daemon 上線時)所有現存 checkbox 不論 `[ ]` 或 `[x]` 都進 cache 不派單。只有**之後**的勾選動作才會派單。
- 派單後 task 在 `tasks/todo/`,默認 `auto_approve: false`,跑完進 `review/` 等你審。
```

- [ ] **Step 8.2: Commit**

```bash
git add tasks/README.md
git commit -m "docs(tasks): document project card checkbox spawn workflow"
```

---

## Self-review notes

**Spec coverage check** (against `2026-05-02-project-checkbox-spawn-task-design.md`):

- Watcher un-ignore + direct-children rule → Task 1.
- `parse_next_actions` (`## 下一步` only, stops at next H2) → Task 2.
- State diff (first-scan baseline, new [x] spawn, undo/edit/reorder no-spawn) → Task 3.
- Filename derivation (Chinese, sanitization, collision suffix, length cap) → Task 4.
- Spawn task + rewrite card line with wikilink + idempotent rewrite → Task 5.
- `process_project_card` orchestration + factory routing → Task 6.
- Replay startup baseline → Task 7.
- README docs → Task 8.

**Placeholder scan:** None. Each step has concrete code or commands. The note in Step 7.3 about `self.logger.logs_dir` is conditional — read the actual code, use the right attribute. That's a safe instruction (the engineer can resolve from the existing class), not a placeholder.

**Type consistency:** `ChecklistItem(text, checked, line_number)` used identically across parse/diff/spawn/rewrite. `process_project_card(card_path, tasks_dir, logs_dir, suppress_self)` signature consistent with both factory wiring (Task 6) and replay (Task 7). State file path `logs/project_checkbox_state.json` consistent in tests and code.

**Edge case verification:**
- Re-running diff on the same state (no changes) → `cur_unchecked == prev_unchecked` set, no items in `prev_unchecked` for current `[x]` items → empty spawn list. Correct.
- Item with same text added twice in current list → spawn list may include duplicates if both are checked. `diff_against_cache` doesn't dedupe by text on `current` because `current` is a list. Acceptable: identical-text duplicates are user error to begin with.
- Idempotency of `rewrite_card_line`: explicit check via `wikilink_prefix in line`. Confirmed by Task 5's `test_rewrite_line_is_idempotent`.
