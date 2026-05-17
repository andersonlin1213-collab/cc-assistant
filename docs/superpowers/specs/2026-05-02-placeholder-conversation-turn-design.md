# Placeholder-Driven Conversation Turn — Design Spec

**Status:** Approved 2026-05-02.
**Goal:** Eliminate the "manually type a `### [Human] timestamp` header to start a new turn" friction. Daemon leaves a visible placeholder line at the end of the file after each cycle; user just covers it with their reply text and saves.

## Why

Current state: a multi-turn conversation requires the user to manually type:
```markdown
### [Human] 2026-05-02 07:50
我的回复
```
before saving. The header format is a parser invariant — without it, the user's text gets absorbed into the previous `[AI]` entry's content, and the next cycle re-runs against an unchanged conversation history (observed in `tasks/doing/试试看.md` 7:32 ↔ 7:37).

The fix is to flip the contract: instead of asking the user to author headers, the daemon **scaffolds** a placeholder turn after each AI reply. The user only edits the placeholder content. Same parser, same writer, no heuristics — just a deterministic "filled vs unfilled" check.

Bundled with this work: rename the `[Human]` role label to `[我]` (parser keeps backward compat for existing files).

## Non-Goals

- **Auto-detect untagged trailing text** as a Human turn — explicitly rejected as too heuristic. The placeholder-and-overwrite UX gives zero ambiguity.
- **Auto-migrate old `[Human]` headers** to `[我]` — old files keep working unchanged. Find-and-replace is a one-shot manual action if the user wants visual consistency.
- **Multi-paragraph placeholder** — single line is enough. Users who need multi-line replies just write multiple lines after the header; the parser already handles multi-line content per role.
- **Placeholder customization (different langs / styles)** — fixed string for now. Easy follow-up if needed.

## The Placeholder

Constant string, single line, italic + parens for visual distinction:

```markdown
### [我] 2026-05-02 07:50
*(在这里写下一条，保存即触发)*
```

**Header timestamp** = the moment the daemon scaffolded it. Visual signal only; not consumed by any logic.

**Detection logic** (parser-side): the last conversation entry is "pending" iff:
- Its role is `ConversationRole.HUMAN`, AND
- Its content stripped of leading/trailing whitespace either:
  - equals exactly `*(在这里写下一条，保存即触发)*`, or
  - is empty (user wiped the placeholder but hasn't typed yet)

A "pending" trailing entry is parsed as before but the orchestrator skips the LLM cycle.

## Architecture

Four layers, each minimal:

### 1. Models (`src/models.py`)

`ConversationRole.HUMAN.value` changes from `"Human"` to `"我"`. The Python enum member name stays `HUMAN` — only the serialized string changes.

### 2. Parser (`src/board/parser.py`)

Two changes:

- The `_CONVERSATION_HEADER` regex's role group accepts `Human|我|AI` (was `Human|AI`).
- `ConversationRole("Human")` and `ConversationRole("我")` both resolve to `HUMAN`. Implemented via `ConversationRole._missing_(cls, value)` — when the enum is constructed with a value not matching any member's primary `.value`, `_missing_` returns the right member. Maps `"Human"` → `ConversationRole.HUMAN`. Standard Python idiom, no caller-side branching needed.

New helper exposed from parser module:

```python
PLACEHOLDER_TEXT = "*(在这里写下一条，保存即触发)*"

def is_pending_placeholder_turn(task: Task) -> bool:
    """True iff the last conversation entry is a pending [我] turn:
    role=HUMAN AND content is empty or equals PLACEHOLDER_TEXT (stripped).

    Orchestrator uses this to skip cycles when the user hasn't actually
    typed a reply (file mtime changed but content didn't).
    """
```

### 3. Writer (`src/board/writer.py`)

- Existing `_format_conversation_entry` already does `f"### [{entry.role.value}] {ts}"`. No change needed — output flips automatically because the enum value changed.
- New helper:
  ```python
  def append_placeholder(path: Path) -> None:
      """Append a `### [我] now` header followed by the placeholder body
      to the file. Idempotent: if the file already ends with a pending
      placeholder turn, no-op.
      """
  ```

### 4. Orchestrator (`src/agent/orchestrator.py`)

Three behavioral changes inside `run_cycle`:

a. **Skip pending placeholder.** After parsing the task, check `is_pending_placeholder_turn(task)`. If True → log `cycle_skipped` (reason `pending_placeholder`) and return. This guards against echo cycles from mtime-only saves.

b. **Append placeholder after AI reply.** After the existing `append_conversation(...)` writes the new `[AI]` entry, call `append_placeholder(path_after_move)`. Wrapped in `self.suppress_self()` to avoid re-triggering the watcher.

c. **Replay back-fill.** In `replay_pending_intents`, after the parse step, if the task is in DOING and `is_pending_placeholder_turn` is False (meaning no placeholder ever existed) AND the last entry's role is `AI`, append a placeholder. Skip the LLM cycle for this file (the user hasn't written anything new). This is the one-time migration for the four files currently in `tasks/doing/`.

The replay back-fill rule is intentionally narrow:
- Only DOING column (where multi-turn conversations happen).
- Only when last entry is AI (i.e., AI just answered, user hasn't replied yet).
- If last entry is HUMAN with non-placeholder content → user has actually replied → run cycle normally.

## Data Flow

User has the file open in Obsidian:

```markdown
## 对话
### [AI] 2026-05-02 07:32
试用成功 ...

### [我] 2026-05-02 07:32
*(在这里写下一条，保存即触发)*
```

User scrolls to bottom, selects the italic line, types `帮我查小米港股一个月走势`, saves:

```markdown
### [我] 2026-05-02 07:32
帮我查小米港股一个月走势
```

1. Watcher fires → `Orchestrator.run_cycle(path)`.
2. Parse → last entry is HUMAN with non-placeholder content → not pending → proceed.
3. Build context, call LLM, get reply.
4. `append_conversation(path, ai_entry)` — adds `### [AI] 07:40\n回复...`.
5. `append_placeholder(path)` (in `suppress_self`) — adds `### [我] 07:40\n*(在这里写下一条，保存即触发)*`.
6. Watcher sees the writes but is suppressed → no re-cycle.

Final file:
```markdown
## 对话
### [AI] 2026-05-02 07:32
试用成功 ...

### [我] 2026-05-02 07:32
帮我查小米港股一个月走势

### [AI] 2026-05-02 07:40
小米港股一个月走势 ...

### [我] 2026-05-02 07:40
*(在这里写下一条，保存即触发)*
```

User scrolls to bottom again, repeats.

## Edge Cases

- **User saves file with placeholder unchanged** (e.g., Obsidian Sync touch only): `is_pending_placeholder_turn` returns True → skip cycle. No LLM call, no infinite loop.
- **User wipes placeholder body but doesn't type**: empty content → still pending → skip.
- **User adds text above the placeholder** (in the middle of the file): the trailing `[我]` entry is still the placeholder → skip. We don't honor mid-file edits as new turns. (Documented behavior; matches today's parser.)
- **User manually adds a `### [我] timestamp` of their own**: works, becomes the new last entry. Backward-compat path is unchanged.
- **File never had a `## 对话` heading**: nothing to detect. `append_placeholder` and `append_conversation` are responsible for inserting `## 对话` if missing — already handled by `append_conversation` today; placeholder follows the same path.

## Compatibility

- Existing `tasks/doing/*.md` files use `[Human]` headers. Parser accepts both. They get a placeholder back-filled by replay on next daemon start.
- Existing tests that assert `### [Human] ...` in writer output need updating to `### [我] ...`. Specifically: any test in `tests/test_writer.py` or `tests/test_orchestrator.py` that round-trips through `_format_conversation_entry` with role HUMAN.
- Tests asserting `parse_task_string` accepts `### [Human]` keep passing (parser still accepts it).

## Testing

Unit tests:

| File | Test | Assertion |
|------|------|-----------|
| `test_parser.py` | parse_accepts_我_header | `### [我] 时间` parses as `ConversationRole.HUMAN` |
| `test_parser.py` | parse_still_accepts_Human_header | back-compat with old files |
| `test_parser.py` | parse_mixed_human_and_我_in_one_file | both forms in same file work, order preserved |
| `test_parser.py` | is_pending_placeholder_returns_true_for_placeholder_text | last `[我]` content matches sentinel |
| `test_parser.py` | is_pending_placeholder_returns_true_for_empty_content | last `[我]` content is whitespace-only |
| `test_parser.py` | is_pending_placeholder_returns_false_for_real_text | normal user reply |
| `test_parser.py` | is_pending_placeholder_returns_false_when_last_is_ai | last entry is AI not 我 |
| `test_writer.py` | append_conversation_emits_我_for_human_role | new conversations write `### [我] ...` |
| `test_writer.py` | append_placeholder_appends_block | helper writes the expected two-line scaffold at file end |
| `test_writer.py` | append_placeholder_is_idempotent | calling twice doesn't stack two placeholders |
| `test_orchestrator.py` | run_cycle_appends_placeholder_after_reply | end-to-end: file ends with placeholder after one cycle |
| `test_orchestrator.py` | run_cycle_skips_when_last_entry_is_placeholder | mtime-only save → no LLM call |
| `test_orchestrator.py` | replay_backfills_placeholder_for_doing_with_ai_last | one-time migration: pre-existing doing/ file gets placeholder |

13 new tests (one more than originally scoped — added the `last_is_ai` negative case for `is_pending_placeholder`).

## Files Changed

- `src/models.py` — `ConversationRole.HUMAN.value = "我"`; add `_missing_` for back-compat with `"Human"`.
- `src/board/parser.py` — regex update; export `PLACEHOLDER_TEXT` constant; add `is_pending_placeholder_turn(task)` helper.
- `src/board/writer.py` — add `append_placeholder(path)` helper.
- `src/agent/orchestrator.py` — skip cycle on pending placeholder; append placeholder after AI reply; replay back-fill rule.
- `tests/test_parser.py`, `tests/test_writer.py`, `tests/test_orchestrator.py` — 13 new tests; update any existing tests that hardcode `[Human]` in writer output.
- `tasks/README.md` — add a "怎么继续对话" section documenting the placeholder-overwrite UX.
