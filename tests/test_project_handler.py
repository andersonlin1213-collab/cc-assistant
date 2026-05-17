import json
import threading
from pathlib import Path

import pytest

from src.board.project_handler import ChecklistItem, diff_against_cache, parse_next_actions
from src.board.project_handler import derive_task_filename
from src.board.project_handler import spawn_task_from_item, rewrite_card_line


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


def test_parse_tolerates_h1_heading_typo():
    """Mobile Obsidian users sometimes type `# 下一步` (H1) instead of the
    canonical `## 下一步` (H2). The parser must still pick up the checklist
    so the typo doesn't silently swallow checkbox spawns. End-of-section
    detection still terminates at the next H1/H2 heading.
    """
    text = """# Some Project

# 下一步 (Next actions)
- [ ] first action
- [x] already done

## 决策记录
- [x] do not include this
"""
    items = parse_next_actions(text)
    assert len(items) == 2
    assert items[0].text == "first action"
    assert items[1].text == "already done"
    assert all(i.text != "do not include this" for i in items)


def test_parse_strips_whitespace_from_item_text():
    """Leading/trailing spaces in item text are normalized."""
    text = """## 下一步 (Next actions)
- [ ]    spaced text
"""
    items = parse_next_actions(text)
    assert items[0].text == "spaced text"


def test_parse_strips_leading_wikilink_prefix():
    """`- [x] [[stem]] canonical` → identity is `canonical`, not `[[stem]] canonical`.

    Without this strip, every cycle `rewrite_card_line` prepends another `[[stem]] `
    to the already-prefixed line, `diff_against_cache` sees a new identity, and the
    same item spawns again → infinite loop. Multiple stacked prefixes from cards
    polluted before this fix landed are stripped iteratively.
    """
    text = """## 下一步 (Next actions)
- [x] [[接入第三方API]] 接入第三方API
- [x] [[outer]] [[inner]] nested prefixes
- [ ] no prefix here
"""
    items = parse_next_actions(text)
    assert [i.text for i in items] == [
        "接入第三方API",
        "nested prefixes",
        "no prefix here",
    ]


def test_parse_leaves_malformed_wikilink_garbage_alone():
    """Strip's boundary: closing `]]` must be followed by whitespace. A
    fragment like `[[[[bad]]X]] still polluted` has `]]X` with no space, so
    nothing looks like a wikilink prefix and the text falls through unchanged.
    Without this guard, the regex could over-eat into the real content."""
    text = """## 下一步 (Next actions)
- [x] [[[[bad]]X]] still polluted
"""
    items = parse_next_actions(text)
    assert items[0].text == "[[[[bad]]X]] still polluted"


def test_parse_strips_nested_polluted_wikilink_prefix():
    """A card polluted by past spawn-loop bug has nested `[[[[stem1]] [[stem2]] real text`.
    The regex iteratively peels two layers (each layer is `[[...]] ` followed by
    whitespace, allowing `[` inside the inner content) until only `real text` remains.
    This is what prevents the same item from being re-spawned cycle after cycle on
    cards that were already polluted before the fix landed."""
    text = """## 下一步 (Next actions)
- [x] [[[[#14briefing-brief]] [[#14briefing-briefin]] #14 briefing接入 alpha-project
"""
    items = parse_next_actions(text)
    assert items[0].text == "#14 briefing接入 alpha-project"


def _state_path(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return logs / "project_checkbox_state.json"


def test_diff_first_scan_baselines_and_spawns_checked_items(tmp_path):
    """No cache entry for slug → baselines state AND spawns pre-checked items
    so that writing `- [x]` directly on a fresh card just works."""
    state = _state_path(tmp_path)
    items = [
        ChecklistItem(text="A", checked=False, line_number=1),
        ChecklistItem(text="B", checked=True, line_number=2),
    ]
    spawn = diff_against_cache("alpha-project", items, state)
    assert len(spawn) == 1 and spawn[0].text == "B"
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


def test_diff_no_spawn_on_already_seen_checked(tmp_path):
    """Item was already checked last time and still checked → don't re-spawn."""
    state = _state_path(tmp_path)
    state.write_text(
        json.dumps({"alpha-project": {"unchecked_items": [], "checked_items": ["A"]}}),
        encoding="utf-8",
    )
    items = [ChecklistItem(text="A", checked=True, line_number=1)]
    spawn = diff_against_cache("alpha-project", items, state)
    assert spawn == []


def test_diff_spawns_brand_new_checked_item(tmp_path):
    """Item not in prev unchecked OR checked → brand-new `- [x]` → spawn."""
    state = _state_path(tmp_path)
    state.write_text(
        json.dumps({"alpha-project": {"unchecked_items": ["A"], "checked_items": ["B"]}}),
        encoding="utf-8",
    )
    items = [
        ChecklistItem(text="A", checked=False, line_number=1),
        ChecklistItem(text="B", checked=True, line_number=2),
        ChecklistItem(text="C", checked=True, line_number=3),
    ]
    spawn = diff_against_cache("alpha-project", items, state)
    assert len(spawn) == 1 and spawn[0].text == "C"


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


def test_derive_filename_strips_backticks_and_parens(tmp_path):
    """Backticks and parens cause downstream poll_error / wikilink confusion;
    they must be sanitized just like fs-illegal chars."""
    todo_dir = tmp_path / "tasks" / "todo"
    todo_dir.mkdir(parents=True)
    name = derive_task_filename(
        "处理 `tasks/doing/foo.md` 的 parse error(`priority: null` 不被接受)",
        todo_dir,
    )
    assert "`" not in name, f"backtick leaked into filename: {name}"
    assert "(" not in name, f"open paren leaked into filename: {name}"
    assert ")" not in name, f"close paren leaked into filename: {name}"
    assert name.endswith(".md")


def test_derive_filename_strips_fullwidth_parens(tmp_path):
    """Full-width Chinese parens（）are also illegal characters in NTFS for
    the same display-confusion reasons; sanitize them too."""
    todo_dir = tmp_path / "tasks" / "todo"
    todo_dir.mkdir(parents=True)
    name = derive_task_filename(
        "物流体系日报（L1）接入调度（手动跑通，等正式群webhook）",
        todo_dir,
    )
    assert "（" not in name, f"fullwidth open paren leaked: {name}"
    assert "）" not in name, f"fullwidth close paren leaked: {name}"


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


def test_spawn_quotes_title_when_text_contains_colon(tmp_path):
    """Real-world bug: an item whose text contains `:` (e.g. mentioning
    `priority: null`) produced unquoted YAML title, which the loader then
    parsed as nested mapping → ScannerError on next daemon start.

    Title MUST be emitted with YAML quoting so colons inside the text
    don't break the document.
    """
    from src.board.parser import parse_task_file
    tasks = tmp_path / "tasks"
    (tasks / "todo").mkdir(parents=True)
    item = ChecklistItem(
        text="处理 `priority: null` 不被接受",
        checked=True,
        line_number=1,
    )

    new_path = spawn_task_from_item(item, "p", tasks)

    # The file must be parseable — if title is unquoted, YAML chokes here.
    task = parse_task_file(new_path)
    assert task.title == "处理 `priority: null` 不被接受"


def test_spawn_creates_task_file_with_correct_frontmatter(tmp_path):
    """spawn_task_from_item writes a tasks/todo/<filename>.md with the right
    frontmatter and body."""
    tasks = tmp_path / "tasks"
    (tasks / "todo").mkdir(parents=True)
    item = ChecklistItem(text="接入第三方 API", checked=True, line_number=10)

    new_path = spawn_task_from_item(item, "alpha-project", tasks)

    assert new_path.exists()
    assert new_path.parent == tasks / "todo"
    # Parse the file to validate frontmatter (title is YAML-quoted, so a
    # raw `in text` check on the un-quoted string would miss).
    from src.board.parser import parse_task_file
    parsed = parse_task_file(new_path)
    assert parsed.title == "接入第三方 API"
    assert parsed.project == "alpha-project"
    assert parsed.auto_approve is False
    # Body references the source project card via wikilink + standard sections
    text = new_path.read_text(encoding="utf-8")
    assert "[[alpha-project]]" in text
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
