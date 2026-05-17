"""Project card checklist handler.

Detects user-driven `- [ ]` → `- [x]` transitions in `## 下一步 (Next actions)`
sections of `tasks/projects/<slug>.md` cards, spawns a corresponding task,
and rewrites the line with a wikilink.

Intentionally does NOT call the LLM. Project card events are pure file
mutations — diff cache, spawn task scaffold, update card.
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path

_STATE_LOCK = threading.Lock()


@dataclass(frozen=True)
class ChecklistItem:
    """A single `- [ ]` / `- [x]` line under `## 下一步`."""
    text: str           # content after the `- [x]` / `- [ ]` prefix, trimmed
    checked: bool       # True if `[x]`, False if `[ ]`
    line_number: int    # 1-based line index in the source for in-place edits


# Tolerate `# 下一步` (H1 typo) in addition to the canonical `## 下一步`.
# Mobile Obsidian users sometimes type a single `#` by mistake; failing
# silently meant no checkbox got spawned and no error surfaced.
_NEXT_ACTIONS_HEADING = re.compile(r"^#{1,2}\s+下一步")
_OTHER_HEADING = re.compile(r"^#{1,2}\s+")
_CHECKLIST_LINE = re.compile(r"^\s*-\s+\[(?P<state>[ xX])\]\s+(?P<text>.*?)\s*$")
# Strip leading `[[stem]] ` wikilink prefix from item text before using it as
# identity. Without this, `rewrite_card_line` re-prepends a new wikilink each
# cycle and `diff_against_cache` sees a new identity → infinite spawn loop.
#
# Inner pattern `[^\]]+` allows the wikilink to contain `[` so that previously
# polluted cards with nested junk like `[[[[a]] [[b]] real text` strip back to
# `real text` after two iterations. The boundary that holds the strip back is
# still strict: closing `]]` must be followed by whitespace, so malformed
# fragments like `[[[[bad]]X]]` (no space after the inner `]]`) fall through
# unchanged — they don't look like a wikilink prefix.
_LEADING_WIKILINK = re.compile(r"^\[\[[^\]]+\]\]\s+")


def parse_next_actions(card_text: str) -> list[ChecklistItem]:
    """Extract checklist items from the `## 下一步` section.

    The section starts at any line beginning with `# 下一步` or `## 下一步`
    (heading-prefix match — tolerant of `## 下一步 (Next actions)` etc., and
    of the H1 typo). It runs until the next H1/H2 heading. Items inside
    `###` sub-headings within that range still count.

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
        # End of section: next H1 or H2 heading.
        if _OTHER_HEADING.match(raw_line):
            in_section = False
            continue
        m = _CHECKLIST_LINE.match(raw_line)
        if m:
            text = m.group("text").strip()
            while True:
                stripped = _LEADING_WIKILINK.sub("", text, count=1)
                if stripped == text:
                    break
                text = stripped
            items.append(
                ChecklistItem(
                    text=text,
                    checked=m.group("state").lower() == "x",
                    line_number=idx,
                )
            )
    return items


def diff_against_cache(
    slug: str, current: list[ChecklistItem], cache_path: Path
) -> list[ChecklistItem]:
    """Diff current checklist against the cache, return items to spawn.

    A "spawn" is any checked item that we haven't seen before — either:
    - previously unchecked → now checked (two-step flow), or
    - brand-new `- [x]` item written directly (one-step flow).

    The cache is updated in-place to reflect the current state regardless
    of the spawn result. First encounter baselines the state AND spawns any
    pre-checked items (so writing `- [x]` on a fresh card just works).

    Item identity = stripped text. Reorder doesn't matter; an edit that
    changes text is treated as remove + add (not a transition).
    """
    with _STATE_LOCK:
        cache = _load_cache(cache_path)

        prev_entry = cache.get(slug)
        cur_unchecked = [i.text for i in current if not i.checked]
        cur_checked = [i.text for i in current if i.checked]

        if prev_entry is None:
            # First encounter: baseline + spawn any pre-checked items.
            cache[slug] = {
                "unchecked_items": cur_unchecked,
                "checked_items": cur_checked,
            }
            _save_cache(cache_path, cache)
            return [i for i in current if i.checked]

        prev_checked = set(prev_entry.get("checked_items", []))

        spawn: list[ChecklistItem] = []
        for item in current:
            if item.checked and item.text not in prev_checked:
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


_ILLEGAL_FS_CHARS = '/:\\*?"<>|`()（）'
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


def spawn_task_from_item(item: ChecklistItem, slug: str, tasks_dir: Path) -> Path:
    """Create tasks/todo/<derived>.md with frontmatter + body for the item."""
    todo_dir = tasks_dir / "todo"
    todo_dir.mkdir(parents=True, exist_ok=True)

    filename = derive_task_filename(item.text, todo_dir)
    path = todo_dir / filename

    # Quote title with single quotes so colons / brackets / other YAML
    # metacharacters in the user's text don't break the frontmatter.
    # YAML escapes a literal single quote inside a single-quoted scalar by
    # doubling it.
    title_yaml = "'" + item.text.replace("'", "''") + "'"
    body = (
        f"---\n"
        f"title: {title_yaml}\n"
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
