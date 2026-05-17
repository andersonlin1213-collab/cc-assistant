# Auto-Enrich Minimal Tasks — Design Spec

**Status:** Approved 2026-05-01.
**Goal:** Let users create a task by saving a markdown file in `tasks/todo/` with only `title:` in frontmatter (and a body). The daemon auto-fills the other required fields on first parse and writes the enriched frontmatter back to disk.

## Why

Current state: parser requires `id`, `title`, `created`, `updated`. Anything missing → `TaskFileMalformed` → daemon silently skips. Users in practice drop body-only or single-field markdown into `tasks/todo/` (like `tasks/财务数据分析.md` did) and nothing happens. The friction is high enough that the user routes around it (writing files at vault root) and the daemon never sees them.

Fixing this is one of two UX changes the user asked for. The other (project-card checkbox triggering tasks) is a separate spec; this one is foundational because the auto-spawned tasks from that future feature will use the same minimal-frontmatter shape.

## Non-Goals

- **Body-only files** (no frontmatter at all) — still rejected. We need at least `title:` so the parser can distinguish "user is drafting" from "user wants the daemon to run this". Future work could synthesize title from filename, but is out of scope here.
- **H1-as-title** (`# title` in body counts as title) — out of scope.
- **Auto-renaming files** to match generated id — explicitly NOT done. The user keeps their human-readable filename; only frontmatter is touched.
- **Cross-process id allocation** — daemon is single-process; a `threading.Lock` is enough.
- **Project inference** — `project` field defaults to `""` (orphan task), same as today. Spawning from project cards is a separate feature.

## Architecture

Two changes, both inside `src/board/`:

1. **`parser.py` — relax required-fields gate.** `_REQUIRED_FRONTMATTER_FIELDS` becomes `("title",)`. The other three (`id`, `created`, `updated`) move from "required" to "auto-fillable when missing".
2. **`parser.py` — new helper `enrich_minimal_task(path: Path) -> bool`.** Idempotent: detects a title-only minimal task, computes the missing fields, writes the enriched frontmatter back. Returns `True` if it wrote, `False` if no-op.

The orchestrator calls `enrich_minimal_task(path)` before each `parse_task_file(path)`. Two call sites:
- `Orchestrator.run_cycle(path)` (orchestrator.py:77) — top of the function, before the existing parse.
- `Orchestrator.replay_pending_intents()` (orchestrator.py:206) — applied to each candidate file the replay scan considers.

The write-back is wrapped in `watcher.suppress_self()` so daemon's own write doesn't re-trigger the cycle.

## Component: `enrich_minimal_task(path)`

```python
def enrich_minimal_task(path: Path) -> bool:
    """Auto-fill id/created/updated for a title-only task file.

    Idempotent. Reads frontmatter; if `title` is present and any of
    {id, created, updated} are missing or empty, computes values and
    writes the file back. Returns True iff the file was written.

    The id is the next available numeric slot across the entire vault
    (max numeric id of all parseable tasks + 1), zero-padded to three
    digits as a quoted string ("007"). Non-numeric ids in the corpus
    (e.g. "demo-001") are ignored when computing max.
    """
```

**id allocation algorithm:**
1. Scan `tasks_dir.glob("*/*.md")` (column folders) and `tasks_dir.glob("done/*/*.md")` (monthly subfolders).
2. For each file, read frontmatter cheaply via `frontmatter.loads(text)` — no full Task validation.
3. Collect `meta.get("id")` values; keep only those matching `^\d+$`; map to int.
4. New id = `max(ids) + 1` if any, else `1`. Format as `f"{n:03d}"`.

**created/updated values:**
- `created` = file `mtime` formatted as `"YYYY-MM-DD HH:MM"` (matches existing format).
- `updated` = `datetime.now()` formatted the same way.

**Concurrency:** module-level `threading.Lock` wraps "scan-then-write". Daemon is single-process; this is sufficient.

**Edge cases:**
- File has no frontmatter at all → no-op (returns False). Subsequent `parse_task_file` will raise `TaskFileMalformed` as today.
- File has frontmatter but no `title` → no-op. Same fallback.
- File already has `id`, `created`, `updated` → no-op (idempotent). Subsequent parse succeeds normally.
- Frontmatter has `id: ""` (empty string) → treated as missing, gets filled in.

## Data Flow

User saves `tasks/todo/财务数据分析.md`:
```
---
title: 财务数据分析
---
我想看陕西门店去年净利润...
```

1. Watcher fires `on_change(path)`.
2. Orchestrator's `run_cycle(path)` enters; first action:
   ```python
   with self._watcher.suppress_self():
       enrich_minimal_task(path)
   ```
3. `enrich_minimal_task` scans existing tasks, finds max id `004`, decides next id `005`. Writes back:
   ```
   ---
   title: 财务数据分析
   id: "005"
   created: 2026-05-01 10:00
   updated: 2026-05-01 10:00
   ---
   我想看陕西门店去年净利润...
   ```
4. Watcher sees the modification but is suppressed → no second cycle.
5. `parse_task_file(path)` now succeeds normally; orchestrator runs its standard cycle (LLM call, response writeback, optional column move).

## Error Handling

- Filesystem write errors during enrichment → propagate as `OSError`. Caller (orchestrator) catches at the cycle boundary as it already does for parse errors.
- Race against external write (user editing in Obsidian while daemon enriches): the write-back uses standard `path.write_text(...)` which is atomic-on-replace on Windows / POSIX. If the user's save lands on top of ours, it just overwrites — they'll see the file flip back to title-only briefly until next daemon touch. Acceptable; no special handling.
- Vault has zero existing tasks → first id is `"001"`.

## Testing

Unit tests in `tests/test_parser.py` (or a new `tests/test_enrich_minimal_task.py`):

| Test | Setup | Assertion |
|------|-------|-----------|
| Enriches title-only file | Write `---\ntitle: x\n---\nbody` | After call: file contains id, created, updated; returns True |
| No-op on complete file | Write file with all 4 fields | mtime unchanged, returns False |
| No-op on no-frontmatter file | Write `body only` | File untouched, returns False |
| No-op on missing-title file | Write `---\nfoo: bar\n---` | File untouched, returns False |
| Treats empty id as missing | Write `---\ntitle: x\nid: ""\n---` | id gets filled, returns True |
| Next id skips existing max | Pre-create id "004", "007" | Enriched file gets id "008" |
| Next id ignores non-numeric | Pre-create id "demo-001", "002" | Enriched file gets id "003" |
| First task gets "001" | Empty vault | Enriched file gets id "001" |
| Concurrent enrichment uses lock | Two threads call enrich on different files concurrently | Both succeed, ids are sequential and distinct |

Integration test in `tests/test_orchestrator.py` (or test_runner.py):

| Test | Setup | Assertion |
|------|-------|-----------|
| Orchestrator triggers enrichment then runs cycle | title-only file in todo/ | Cycle runs once (LLM called once); file ends up with id/created/updated and the AI response |

## Files Changed

- `src/board/parser.py` — drop required fields to `("title",)`; add `enrich_minimal_task` helper.
- `src/agent/orchestrator.py` — call `enrich_minimal_task` at top of `run_cycle` (orchestrator.py:77) and inside `replay_pending_intents` (orchestrator.py:206), both wrapped in `suppress_self`.
- `tests/test_parser.py` — add unit tests for the new helper. (New file `tests/test_enrich_minimal_task.py` is acceptable if `test_parser.py` is already large.)
- `tests/test_orchestrator.py` — one integration test asserting end-to-end enrichment + cycle runs once.
- `tasks/README.md` — append a short section: "新建任务的最小写法:写 `title:` 和正文,daemon 会补 id 和时间戳。"

## Compatibility

Existing tasks (with full frontmatter) — completely unaffected. `enrich_minimal_task` returns False, parser sees all fields, runs as before.
