# Todo Folder Implies Task — Design Spec

**Status:** Approved 2026-05-02.
**Goal:** Files dropped into `tasks/todo/` or `tasks/backlog/` should run as tasks even with no frontmatter at all. The daemon treats the file's location (intentional `todo/` placement) as the "this is a task" signal, and uses the filename as the title.

## Why

Mobile Obsidian's default new-note location is the vault root, and many users navigate folders awkwardly on phone. Even after fixing the location, asking the user to type `---\ntitle: ...\n---` on a phone keyboard is enough friction that the workflow stalls (observed twice already in this project: `tasks/旅游规划.md`, `tasks/测试.md` etc. — both ended up at vault root with no frontmatter).

The 2026-05-01 minimal-task feature already accepts files with `title:`-only frontmatter. This spec extends that one more step: in `todo/` and `backlog/`, even `title:` becomes optional. Filename becomes the title.

This is safe because `todo/` and `backlog/` are explicit user intent — placing a file there means "I want this run". Other columns (`doing/` `blocked/` `review/` `done/`) keep their strict requirements: a file appearing there with no frontmatter is more likely a bug or stray sync artifact than an intent.

## Non-Goals

- **Vault root relaxation** — root files stay ignored (already filtered by watcher in `6eac7f6`). Mobile users should configure Obsidian's "new file location" to `tasks/todo`, OR the daemon's relaxation only kicks in once the file lands in `todo/` (manual move on phone is fine).
- **Filename normalization** — title = filename stem as-is. No slug-cleanup, no case change, no character substitution. `财务分析-Q2.md` → title `财务分析-Q2`.
- **`done/` / `review/` / `blocked/` / `doing/` relaxation** — only `todo/` and `backlog/`.
- **Auto-renaming files** — daemon never modifies the filename; it only writes frontmatter into the file body.

## Architecture

One layer change, in `src/board/parser.py`:

The existing `enrich_minimal_task(path, tasks_dir) -> bool` helper already detects files needing enrichment based on missing `id` / `created` / `updated`. We extend its detection logic: a file is also enrichable if it lives in `todo/` or `backlog/` and is missing `title` (or `title` is empty). In that case, daemon synthesizes title from `path.stem`.

The parser's `_REQUIRED_FRONTMATTER_FIELDS = ("title",)` stays as-is — `title` remains the only required field. What changes is how the orchestrator's pre-parse enrichment step prepares the file: for `todo/`/`backlog/` files, enrichment will fill in title before parse runs, so by the time parse executes, the file always has all the required fields.

Concretely:

1. **`enrich_minimal_task` adds a "title from filename" rule.**
   - If file is in `todo/` or `backlog/`, AND frontmatter `title` is missing or empty → set `title = path.stem`.
   - This rule runs alongside the existing id/created/updated enrichment in the same write-back pass.

2. **No watcher change.** Watcher already passes `todo/` files through (Task 6eac7f6 whitelist).

3. **No orchestrator change.** Orchestrator already calls `enrich_minimal_task` at top of `run_cycle` and inside `replay_pending_intents`; both pick up the new rule for free.

4. **No parser-strict-gate change.** Parser still requires `title`. Enrichment ensures it's there before parse runs in todo/ / backlog/ flow.

## Behavior Examples

### Case A: phone-created bare file in todo/

User saves `tasks/todo/查询小米股价.md` with content:
```
帮我查最近一个月的港股小米走势
```
(zero frontmatter)

1. Watcher fires → `Orchestrator.run_cycle(path)`.
2. `enrich_minimal_task(path, tasks_dir)` — detects no frontmatter, file in todo/ → synthesizes title from filename, plus id/created/updated. Writes back:
   ```
   ---
   title: 查询小米股价
   id: "020"
   created: 2026-05-02 19:30
   updated: 2026-05-02 19:30
   ---

   帮我查最近一个月的港股小米走势
   ```
3. Parse succeeds → cycle runs → AI reply appended → placeholder appended.

### Case B: file in todo/ with title-only frontmatter (existing minimal-task feature)

Already works. `enrich_minimal_task` only fills missing fields; title is preserved.

### Case C: file in todo/ with `title: ""` (empty)

Treated same as missing — synthesized from filename. (Mirrors the empty-id rule from minimal-task spec.)

### Case D: file in `tasks/doing/scratch.md` with no frontmatter

Stays a no-op:
- Enrichment doesn't synthesize title (only todo/ and backlog/ qualify).
- Parser still requires title, raises `TaskFileMalformed`.
- Orchestrator logs `task_malformed`, returns.

This is intentional: a file appearing bare in `doing/` is suspicious (failed move? sync glitch?) and should fail loudly, not silently get processed.

### Case E: file in vault root with no frontmatter

Watcher already filters this (`6eac7f6` whitelist). Daemon never sees it.

## Edge Cases

- **Filename with `.md` after the stem** (`查询.draft.md`) — `path.stem` returns `查询.draft`. Acceptable.
- **Empty filename stem** (just `.md` — file named exactly `.md`) — `path.stem` is `""`. Treat as missing → enrichment doesn't run for this case (we need a non-empty title). Falls through to parser → `TaskFileMalformed`. (Vanishingly unlikely in practice.)
- **Filename equals `Untitled` or `未命名`** — accepted as-is. User will see "Untitled" in the task and likely rename.
- **Concurrent `enrich_minimal_task` calls on different files in todo/** — handled by existing `_ENRICH_LOCK`. No new concurrency surface.
- **File in `todo/subfolder/foo.md`** — only direct children of `todo/` and `backlog/` qualify. Watcher's whitelist requires `path.parent.name in COLUMNS`, so a sub-subfolder is already filtered out and never reaches enrichment.

## Compatibility

- All existing tasks (with full frontmatter) — completely unaffected.
- Existing minimal-task tests (title-only files in any column) — unaffected; enrichment continues to fill id/created/updated only when title is already set.
- Tests for vault-root rejection — unaffected; vault root stays filtered by watcher.

## Testing

Unit tests in `tests/test_enrich_minimal_task.py`:

| Test | Setup | Assertion |
|------|-------|-----------|
| Enriches title from filename in todo/ | Write `tasks/todo/查询.md` with body only | After enrich: title=`查询`, id/created/updated filled |
| Enriches title from filename in backlog/ | Write `tasks/backlog/foo.md` with body only | After enrich: title=`foo` |
| Empty title in todo/ → from filename | Write `tasks/todo/bar.md` with frontmatter `title: ""` | After enrich: title=`bar` |
| No-op in doing/ for bare file | Write `tasks/doing/baz.md` with body only | After enrich: returns False, file unchanged |
| No-op in review/ for bare file | Same | False, unchanged |
| No-op in blocked/ for bare file | Same | False, unchanged |
| Existing title preserved in todo/ | Write `tasks/todo/qux.md` with frontmatter `title: 真标题` | After enrich: title=`真标题` (NOT `qux`) |
| Filename `.md` only — edge case | Write `tasks/todo/.md` with body only | enrich returns False (empty stem); file unchanged |

8 new unit tests. Existing 9 tests for `enrich_minimal_task` remain unchanged.

Integration test (optional, can ride existing orchestrator coverage):

| Test | Setup | Assertion |
|------|-------|-----------|
| End-to-end: bare file in todo/ runs cycle | Write `tasks/todo/集成测试.md` with body only, run cycle | LLM called once; file gains title=`集成测试` + id; AI reply + placeholder appended |

## Files Changed

- `src/board/parser.py` — extend `enrich_minimal_task` to recognize the "title-from-filename" rule for files under `todo/` or `backlog/`.
- `tests/test_enrich_minimal_task.py` — add 8 unit tests.
- `tests/test_orchestrator.py` — add 1 integration test.
- `tasks/README.md` — append a note to the existing "最小寫法" section that vault-root → must use `title:`, but todo/backlog can skip it entirely.
