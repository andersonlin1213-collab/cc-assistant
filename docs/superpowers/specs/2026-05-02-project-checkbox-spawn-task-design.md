# Project Card Checkbox Spawns Task — Design Spec

**Status:** Approved 2026-05-02.
**Goal:** When the user ticks a `- [ ]` checkbox under the `## 下一步 (Next actions)` section of a project card (`tasks/projects/<slug>.md`), daemon spawns a corresponding task file in `tasks/todo/` and rewrites the line in the project card to include a wikilink to the new task.

## Why

Project cards already document what's next per project (`下一步` lists are populated across all 14 cards). Today, turning a "next action" into an actual daemon-runnable task is fully manual: open `tasks/todo/`, create new file, type frontmatter, copy the action text, save. That friction defeats the point of having structured project cards.

This is the second of two UX enhancements proposed back when project cards were created. The first (zero-frontmatter task creation in `tasks/todo/`) shipped on 2026-05-02. This spec connects project cards directly to the task pipeline, so the user's mental flow matches the file behavior: "click checkbox → daemon picks it up".

## Non-Goals

- **Auto-checking when task completes** — when the spawned task moves to `done/`, the project card's `[x]` stays. The two states (intent-to-do vs. completed) intentionally tracked separately. Future enhancement could close the loop.
- **Spawning from `decision log` / `open issues` / other checklist sections** — only `## 下一步` triggers. Other sections may legitimately have `- [x]` for chronicling done facts (e.g., `## 决策记录: - [x] 选定 DeepSeek API`), and we don't want those to spawn.
- **Real-time bidirectional sync between card and tasks** — once a task is spawned, the card's wikilink is the only ongoing connection. No live propagation of updates.
- **Spawning when daemon is offline** — replay scan on daemon startup catches up state diffs, but only for project cards changed since the last cache update. Out-of-band edits the daemon never saw don't retroactively trigger.
- **Multi-user / concurrent project card edits** — single-process daemon assumption.

## Architecture

Five layers, each minimal:

### 1. Watcher: stop ignoring `tasks/projects/`

`src/dispatcher/watcher.py:_IGNORE_PATH_FRAGMENTS` currently includes `/projects/` and `\projects\`. Remove those entries. But: project card events must NOT route to `Orchestrator.run_cycle` (project cards aren't tasks, never call LLM). Instead, the dispatcher coordinator routes events based on path:

- `tasks/projects/<slug>.md` → `process_project_card(path)` (new)
- everything else (column files) → `Orchestrator.run_cycle` (existing)

### 2. New module: `src/board/project_handler.py`

```python
def process_project_card(path: Path, tasks_dir: Path, logs_dir: Path,
                        suppress_self: Callable) -> None:
    """Diff project card checklist against cache, spawn tasks for newly-checked
    items, update cache and the card's checklist lines.
    """

def parse_next_actions(card_text: str) -> list[ChecklistItem]:
    """Extract checklist items in the `## 下一步 (Next actions)` section.

    Returns list of ChecklistItem(text, checked). Items outside that section
    are ignored. Section ends at next `## ` heading.
    """

@dataclass
class ChecklistItem:
    text: str       # the line content after `- [x]` / `- [ ]`
    checked: bool   # True if `[x]`, False if `[ ]`
    line_number: int  # position in source for in-place edits

def diff_against_cache(slug: str, current: list[ChecklistItem],
                      cache_path: Path) -> list[ChecklistItem]:
    """Returns list of items that are checked NOW but were unchecked LAST.
    Updates the cache file in place. Empty list means no spawning to do.
    Returns [] on first encounter (no cache entry yet) — populates cache instead.
    """

def spawn_task_from_item(item: ChecklistItem, slug: str,
                         tasks_dir: Path) -> Path:
    """Create tasks/todo/<derived-filename>.md, return the file path."""

def rewrite_card_line(path: Path, item: ChecklistItem,
                      task_filename: str, suppress_self: Callable) -> None:
    """Replace `- [x] <text>` with `- [x] [[<task-filename>]] <text>` on the
    matching line. Idempotent — if the wikilink prefix already exists, no-op.
    Wrapped in suppress_self to avoid re-triggering the watcher.
    """
```

### 3. State cache file: `logs/project_checkbox_state.json`

```json
{
  "alpha-project": {
    "checked_items": ["接入第三方 API 拿模板", "周报推送频率确认"],
    "unchecked_items": ["月底对账流程"]
  },
  "my-community-agent": { ... }
}
```

Item identity = the line text (after stripping `- [ ]` / `- [x]` and trimming). Reorder doesn't change identity. Edit changes identity (old text disappears, new text added as unchecked → no spawn from that single change; spawn happens later if user ticks).

Concurrency: module-level `threading.Lock` wraps read-then-write of this file (same pattern as `_ENRICH_LOCK`).

### 4. Orchestrator startup: replay scan also touches projects/

`Orchestrator.replay_pending_intents` (or a sibling method) iterates over `tasks/projects/*.md` once at daemon startup. For each: call `process_project_card`. If cache has no entry for that slug → populate (no spawn). If cache has entry → diff and spawn. This catches state changes that landed via Obsidian Sync while the daemon was offline.

### 5. Routing decision in coordinator

`src/dispatcher/coordinator.py` currently exposes `on_task_change` and `on_poll`. We need a third callback or a routing layer that inspects the changed path. Cleanest: the watcher's `on_change` callback (already a single function) inspects the path and dispatches to either the orchestrator or the project handler.

Smallest delta: in `src/cli.py`'s `cmd_run`, where the orchestrator and watcher are wired up, wrap the existing `on_change` handler with a router. Pseudo:

```python
def routed_on_change(path: Path):
    if path.parent.name == "projects" and path.parent.parent == config.tasks_dir:
        process_project_card(path, ...)
    else:
        await orchestrator.run_cycle(path)
```

## Data Flow Example

User opens `tasks/projects/alpha-project.md` in Obsidian, sees:

```markdown
## 下一步 (Next actions)
- [ ] 接入第三方 API 拿模板
- [ ] 周报推送频率确认
- [ ] 月底对账流程
```

Cache state for `alpha-project`:
```json
{"checked_items": [], "unchecked_items": ["接入第三方 API 拿模板", "周报推送频率确认", "月底对账流程"]}
```

User taps the first checkbox. File becomes:
```markdown
## 下一步 (Next actions)
- [x] 接入第三方 API 拿模板
- [ ] 周报推送频率确认
- [ ] 月底对账流程
```

Save. Watcher fires → `process_project_card`:

1. Parse current state: `checked=["接入第三方..."], unchecked=["周报推送...", "月底对账..."]`
2. Diff: "接入第三方 API 拿模板" was unchecked, now checked → spawn list = ["接入第三方 API 拿模板"]
3. For each item:
   - Sanitize text → filename `接入第三方API拿模板.md`
   - Create `tasks/todo/接入第三方API拿模板.md` with frontmatter `title: 接入第三方 API 拿模板`, `project: alpha-project`, `auto_approve: false`, body: `## 任务描述\n接入第三方 API 拿模板\n\n(从项目卡 [[alpha-project]] 派单)\n\n## 对话\n`
4. Rewrite the line in project card:
   ```
   - [x] [[接入第三方API拿模板]] 接入第三方 API 拿模板
   ```
5. Update cache:
   ```json
   {"checked_items": ["接入第三方 API 拿模板"], "unchecked_items": ["周报推送...", "月底对账..."]}
   ```
6. Watcher's `suppress_self` swallows the daemon's writes to both files.
7. The new task in `tasks/todo/` triggers a separate watcher event AFTER the suppression window — that's the normal task pipeline, runs the LLM cycle and appends placeholder.

## First-Time Scan Behavior

A project card the daemon has never processed (no cache entry for its slug):
- Parse current state. All items, regardless of `[ ]` or `[x]`, get logged into the cache as their current state.
- **No spawning.** Even if there are existing `- [x]` items pre-dating the feature, nothing is retro-spawned.

This is the critical safety property. On feature launch, all 14 existing project cards' checklists go into the cache silently on the first daemon scan. From that point forward, only NEW transitions ([ ]→[x]) trigger spawns.

## Edge Cases

- **Section heading variation**: only `## 下一步 (Next actions)` matches exactly. If user renames to `## TODO` or `## Next`, that section becomes invisible to the daemon. Acceptable trade-off — strict match prevents false positives.
- **Multiple checkboxes ticked in one save**: spawn each, in source-line order. Cache update batched (one write at end).
- **Filename collision**: if `tasks/todo/接入第三方API拿模板.md` already exists when daemon tries to spawn, append `-2`, `-3` until free. Wikilink in card uses the actually-used filename.
- **Identical text appears twice in checklist** (`- [ ] foo`, `- [ ] foo`): cache treats them as one entry (set semantics by text). If user clicks one of them, both lines have the same text, both get rewritten with the same wikilink (point to the single spawned task). Probably fine — duplicate entries are user error to begin with.
- **Empty `## 下一步` section**: parse returns `[]`, diff returns `[]`, no-op. Cache may still create an empty entry for the slug.
- **Project card with no frontmatter / unparseable**: `project_handler` parses just the markdown body for the `## 下一步` section; frontmatter parse failure is logged but doesn't block checkbox processing. Action: log `project_card_malformed`, continue with body parsing.
- **`## 下一步` heading absent entirely**: empty checklist, same as empty section.
- **User undoes (`[x]` → `[ ]`)**: cache moves item from checked back to unchecked. No reverse action — the spawned task already exists in `tasks/todo/`. Acceptable: undo on the project card doesn't undo the spawn.
- **User edits item text**: old text disappears from cache (orphan), new text appears as unchecked. No spawn from this single edit. User clicks new text → spawn.
- **Item text contains filesystem-illegal chars** (`/`, `\`, `:`, `*`, `?`, `"`, `<`, `>`, `|`): replaced with `-` in filename. Original text preserved in title/body.
- **Item text > 50 chars**: filename truncated at 50, original full text preserved in title/body.
- **Path with `tasks/projects/sub/foo.md`** (sub-subfolder): direct-children-only rule — only `tasks/projects/<slug>.md` qualifies. Sub-subfolders ignored.
- **Concurrent saves on different project cards**: handled by `_PROJECT_STATE_LOCK` around cache read+write.

## Files Changed

- `src/dispatcher/watcher.py` — remove `/projects/` / `\projects\` from `_IGNORE_PATH_FRAGMENTS`.
- `src/board/project_handler.py` — new module (~150 lines): parse, diff, spawn, rewrite, state file IO.
- `src/cli.py` (or wherever orchestrator + watcher are wired) — add path-routing wrapper around `on_change`.
- `src/agent/orchestrator.py` — extend `replay_pending_intents` (or add `replay_project_cards`) to call `process_project_card` for each `tasks/projects/<slug>.md` at startup, populating cache without spawning.
- `tests/test_project_handler.py` — new file, ~13 unit tests.
- `tests/test_orchestrator.py` (or new `tests/test_project_handler_integration.py`) — ~5 integration tests.
- `tasks/README.md` — append section explaining "勾选派单" workflow.

## Testing Summary

13 unit tests in `test_project_handler.py`:

| Test | Asserts |
|---|---|
| `parse_next_actions_extracts_checklist` | Picks up `- [ ]` / `- [x]` lines under `## 下一步`, preserves order |
| `parse_next_actions_handles_missing_section` | Returns `[]`, no error |
| `parse_next_actions_stops_at_next_h2` | `## 决策记录` items not included |
| `parse_next_actions_skips_subheading_items` | `### something` followed by `- [ ]` not in scope |
| `diff_returns_newly_checked_items` | Cache had `[ ]`, now `[x]` → returned in spawn list |
| `diff_no_spawn_on_undo` | Cache had `[x]`, now `[ ]` → not in spawn list, cache updated |
| `diff_no_spawn_on_added_unchecked` | New `[ ]` line added → cache updated, not in spawn list |
| `diff_no_spawn_on_text_edit` | Old text removed, new text added as unchecked → not in spawn list |
| `diff_first_scan_returns_empty` | No cache entry for slug → returns `[]`, populates cache |
| `derive_filename_chinese_text` | "接入第三方 API" → `接入第三方API.md` (spaces stripped) |
| `derive_filename_sanitizes_special_chars` | `/ : * ? " < > \|` replaced with `-` |
| `derive_filename_collision_appends_suffix` | Existing file with same name → `-2.md` |
| `state_file_concurrent_writes_serialized` | Two threads writing different slugs → both persisted |

5 integration tests:

| Test | Asserts |
|---|---|
| `click_checkbox_spawns_task_and_updates_card` | E2E: tick `[x]` → file appears in todo/ with right frontmatter, card line gets wikilink prefix |
| `multiple_checkboxes_in_one_save_spawn_multiple` | Tick 3 boxes, save once → 3 task files, 3 lines rewritten |
| `malformed_project_card_logs_and_continues` | Card with broken frontmatter → log entry, daemon doesn't crash |
| `watcher_routes_project_card_to_handler_not_orchestrator` | LLM mock not called when project card changes |
| `replay_populates_cache_without_spawning` | Daemon startup with pre-existing checked items → cache file appears, no tasks spawned |

## Compatibility

- Existing project cards are unchanged in structure — no migration needed. First daemon scan after this feature ships records their state to cache silently.
- Existing tasks unaffected.
- The watcher whitelist for column folders (commit `6eac7f6`) stays. We add a sibling: `tasks/projects/<slug>.md` direct children also pass, but to a different handler.
- The `Plan 5b` decision to ignore project edits from triggering LLM cycles is preserved — `process_project_card` never calls the orchestrator/LLM, only does diff + file mutation.
