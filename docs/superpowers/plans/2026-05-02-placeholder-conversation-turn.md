# Placeholder-Driven Conversation Turn Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the "manually type `### [Human] timestamp` to start a new turn" friction. Daemon scaffolds a placeholder line at the end of every cycle; user covers it with their reply and saves.

**Architecture:** Four small layers — rename `ConversationRole.HUMAN.value` to `"我"` with `_missing_` back-compat for `"Human"`; parser exports `PLACEHOLDER_TEXT` + `is_pending_placeholder_turn(task)`; writer adds `append_placeholder(path)`; orchestrator (a) skips cycle when last entry is pending, (b) appends placeholder after AI reply, (c) one-time replay back-fill for pre-existing doing/ files.

**Tech Stack:** Python 3.13, Pydantic v2, `python-frontmatter`, pytest, `re`.

**Spec:** `docs/superpowers/specs/2026-05-02-placeholder-conversation-turn-design.md`

---

## File Plan

**Modified files:**
- `src/models.py` — `ConversationRole.HUMAN.value = "我"`; add `_missing_` classmethod for `"Human"` back-compat.
- `src/board/parser.py` — regex accepts `Human|我|AI`; module-level `PLACEHOLDER_TEXT`; new `is_pending_placeholder_turn(task)` helper.
- `src/board/writer.py` — new `append_placeholder(path)` helper. `_format_conversation_entry` is unchanged (already uses `entry.role.value`).
- `src/agent/orchestrator.py` — skip cycle on pending placeholder; append placeholder after AI reply; replay back-fill rule.
- `tests/test_parser.py` — 7 new tests (3 role parsing, 4 `is_pending_placeholder_turn`).
- `tests/test_writer.py` — 3 new tests (1 emits `[我]`, 2 placeholder helper).
- `tests/test_orchestrator.py` — 3 new tests (skip on pending, append after reply, replay back-fill).
- `tasks/README.md` — add "怎么继续對話" section.

**New tests file:** none — all extend existing test files.

---

## Task 1: ConversationRole renames HUMAN to "我" with back-compat

**Files:**
- Modify: `src/models.py:61-63`
- Test: `tests/test_models.py`

- [ ] **Step 1.1: Write the failing tests**

Append to `tests/test_models.py`:

```python
def test_conversation_role_human_value_is_chinese():
    """The serialized value of HUMAN is now '我', not 'Human'."""
    from src.models import ConversationRole
    assert ConversationRole.HUMAN.value == "我"


def test_conversation_role_accepts_legacy_human_string():
    """Old files write '### [Human] ...' — parser will pass that string
    to ConversationRole(...). It must resolve to HUMAN, not raise."""
    from src.models import ConversationRole
    role = ConversationRole("Human")
    assert role is ConversationRole.HUMAN


def test_conversation_role_accepts_chinese_string():
    """New files write '### [我] ...' — parser passes '我'."""
    from src.models import ConversationRole
    role = ConversationRole("我")
    assert role is ConversationRole.HUMAN


def test_conversation_role_ai_unchanged():
    from src.models import ConversationRole
    assert ConversationRole.AI.value == "AI"
    assert ConversationRole("AI") is ConversationRole.AI
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_models.py::test_conversation_role_human_value_is_chinese tests/test_models.py::test_conversation_role_accepts_legacy_human_string tests/test_models.py::test_conversation_role_accepts_chinese_string -v`
Expected: 3 FAIL — first two with assertion `'Human' == '我'`, third with `ValueError: '我' is not a valid ConversationRole`.

- [ ] **Step 1.3: Update the enum**

In `src/models.py`, replace:

```python
class ConversationRole(str, Enum):
    HUMAN = "Human"
    AI = "AI"
```

with:

```python
class ConversationRole(str, Enum):
    HUMAN = "我"
    AI = "AI"

    @classmethod
    def _missing_(cls, value):
        # Back-compat: legacy files use "Human" for the human role.
        # When parser builds a ConversationRole from that string, route it
        # to HUMAN instead of raising ValueError.
        if value == "Human":
            return cls.HUMAN
        return None
```

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_models.py -v`
Expected: PASS — all 4 new tests + existing model tests.

- [ ] **Step 1.5: Run the full suite to spot regressions**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest 2>&1 | tail -3`
Expected: many existing tests in `test_writer.py` / `test_orchestrator.py` may now fail if they hardcode `### [Human] ...` in expected output. Note any failures and address them in Tasks 3 and 5.

- [ ] **Step 1.6: Commit**

```bash
git add src/models.py tests/test_models.py
git commit -m "feat(models): rename ConversationRole.HUMAN to '我' with back-compat"
```

---

## Task 2: Parser regex + placeholder helper

**Files:**
- Modify: `src/board/parser.py:22-24`, append at module level
- Test: `tests/test_parser.py`

- [ ] **Step 2.1: Write the failing tests**

Append to `tests/test_parser.py`:

```python
def test_parser_accepts_我_header():
    """### [我] timestamp parses as a HUMAN conversation entry."""
    from src.models import ConversationRole
    text = (
        "---\n"
        'id: "001"\n'
        "title: t\n"
        "created: 2026-05-02 07:00\n"
        "updated: 2026-05-02 07:00\n"
        "---\n"
        "## 对话\n"
        "### [我] 2026-05-02 07:35\n"
        "你好\n"
    )
    task = parse_task_string(text)
    assert len(task.conversation) == 1
    assert task.conversation[0].role is ConversationRole.HUMAN
    assert task.conversation[0].content == "你好"


def test_parser_accepts_legacy_Human_header():
    """### [Human] timestamp continues to parse as HUMAN (back-compat)."""
    from src.models import ConversationRole
    text = (
        "---\n"
        'id: "001"\n'
        "title: t\n"
        "created: 2026-05-02 07:00\n"
        "updated: 2026-05-02 07:00\n"
        "---\n"
        "## 对话\n"
        "### [Human] 2026-04-26 14:00\n"
        "old reply\n"
    )
    task = parse_task_string(text)
    assert task.conversation[0].role is ConversationRole.HUMAN
    assert task.conversation[0].content == "old reply"


def test_parser_mixed_human_and_我_in_one_file():
    """Order is preserved when a file mixes both header forms."""
    from src.models import ConversationRole
    text = (
        "---\n"
        'id: "001"\n'
        "title: t\n"
        "created: 2026-05-02 07:00\n"
        "updated: 2026-05-02 07:00\n"
        "---\n"
        "## 对话\n"
        "### [Human] 2026-04-26 14:00\n"
        "old\n"
        "### [AI] 2026-04-26 14:05\n"
        "reply\n"
        "### [我] 2026-05-02 07:35\n"
        "new\n"
    )
    task = parse_task_string(text)
    assert len(task.conversation) == 3
    assert task.conversation[0].role is ConversationRole.HUMAN
    assert task.conversation[0].content == "old"
    assert task.conversation[1].role is ConversationRole.AI
    assert task.conversation[2].role is ConversationRole.HUMAN
    assert task.conversation[2].content == "new"


def test_is_pending_placeholder_returns_true_for_placeholder_text():
    from src.board.parser import PLACEHOLDER_TEXT, is_pending_placeholder_turn
    from src.models import ConversationEntry, ConversationRole, Task
    from datetime import datetime
    task = Task(
        id="001",
        title="t",
        created=datetime(2026, 5, 2),
        updated=datetime(2026, 5, 2),
        conversation=[
            ConversationEntry(
                role=ConversationRole.AI,
                timestamp=datetime(2026, 5, 2, 7, 32),
                content="试用成功",
            ),
            ConversationEntry(
                role=ConversationRole.HUMAN,
                timestamp=datetime(2026, 5, 2, 7, 35),
                content=PLACEHOLDER_TEXT,
            ),
        ],
    )
    assert is_pending_placeholder_turn(task) is True


def test_is_pending_placeholder_returns_true_for_empty_content():
    from src.board.parser import is_pending_placeholder_turn
    from src.models import ConversationEntry, ConversationRole, Task
    from datetime import datetime
    task = Task(
        id="001",
        title="t",
        created=datetime(2026, 5, 2),
        updated=datetime(2026, 5, 2),
        conversation=[
            ConversationEntry(
                role=ConversationRole.HUMAN,
                timestamp=datetime(2026, 5, 2, 7, 35),
                content="   \n  \n",
            ),
        ],
    )
    assert is_pending_placeholder_turn(task) is True


def test_is_pending_placeholder_returns_false_for_real_text():
    from src.board.parser import is_pending_placeholder_turn
    from src.models import ConversationEntry, ConversationRole, Task
    from datetime import datetime
    task = Task(
        id="001",
        title="t",
        created=datetime(2026, 5, 2),
        updated=datetime(2026, 5, 2),
        conversation=[
            ConversationEntry(
                role=ConversationRole.HUMAN,
                timestamp=datetime(2026, 5, 2, 7, 35),
                content="帮我查股价",
            ),
        ],
    )
    assert is_pending_placeholder_turn(task) is False


def test_is_pending_placeholder_returns_false_when_last_is_ai():
    from src.board.parser import is_pending_placeholder_turn
    from src.models import ConversationEntry, ConversationRole, Task
    from datetime import datetime
    task = Task(
        id="001",
        title="t",
        created=datetime(2026, 5, 2),
        updated=datetime(2026, 5, 2),
        conversation=[
            ConversationEntry(
                role=ConversationRole.AI,
                timestamp=datetime(2026, 5, 2, 7, 32),
                content="reply",
            ),
        ],
    )
    assert is_pending_placeholder_turn(task) is False
```

- [ ] **Step 2.2: Run tests to verify they fail**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_parser.py -v -k "我 or Human or pending_placeholder"`
Expected: 7 FAIL — `[我]` regex doesn't match (3 tests), and `is_pending_placeholder_turn` / `PLACEHOLDER_TEXT` don't exist (4 tests).

- [ ] **Step 2.3: Update parser**

In `src/board/parser.py`, change line 22-24 from:

```python
# Matches: ### [Human] 2026-04-26 14:00  or  ### [AI] 2026-04-26 14:02
_CONVERSATION_HEADER = re.compile(
    r"^###\s+\[(?P<role>Human|AI)\]\s+(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*$"
)
```

to:

```python
# Matches: ### [我] 2026-05-02 07:35  or  ### [Human] 2026-04-26 14:00 (legacy)
# or  ### [AI] 2026-04-26 14:02
_CONVERSATION_HEADER = re.compile(
    r"^###\s+\[(?P<role>Human|我|AI)\]\s+(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*$"
)
```

Then append at the end of `src/board/parser.py` (after `_parse_datetime`):

```python
PLACEHOLDER_TEXT = "*(在这里写下一条，保存即触发)*"


def is_pending_placeholder_turn(task: "Task") -> bool:
    """True iff the last conversation entry is a pending [我] placeholder.

    Pending = the user has NOT typed a real reply. Specifically:
      - last entry's role is HUMAN, AND
      - last entry's content stripped of whitespace is empty OR equals
        the PLACEHOLDER_TEXT sentinel.

    Orchestrator uses this to skip cycles when a save event arrived but
    the conversation hasn't actually advanced.
    """
    from src.models import ConversationRole  # local import avoids circular
    if not task.conversation:
        return False
    last = task.conversation[-1]
    if last.role is not ConversationRole.HUMAN:
        return False
    stripped = last.content.strip()
    return stripped == "" or stripped == PLACEHOLDER_TEXT
```

- [ ] **Step 2.4: Run tests to verify they pass**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_parser.py -v`
Expected: PASS — all parser tests including the 7 new ones.

- [ ] **Step 2.5: Commit**

```bash
git add src/board/parser.py tests/test_parser.py
git commit -m "feat(parser): accept [我] header + add is_pending_placeholder_turn helper"
```

---

## Task 3: Writer emits `[我]` and gains `append_placeholder`

**Files:**
- Modify: `src/board/writer.py` (add helper at end)
- Test: `tests/test_writer.py`

- [ ] **Step 3.1: Update existing writer tests broken by the rename**

`tests/test_writer.py` likely contains assertions like `assert "### [Human]" in output`. Run:

```bash
cd <your-user>/projects/cc-assitant && python -m pytest tests/test_writer.py -v 2>&1 | tail -20
```

For each failure that asserts `"### [Human]"` in output where the role is HUMAN, change the expected string to `"### [我]"`. Don't weaken the assertion — just update the literal.

Same for `tests/test_orchestrator.py` if it does the same. Defer orchestrator updates to Task 5; for now, focus on writer.

Re-run `python -m pytest tests/test_writer.py -v`. Expected: pre-existing tests pass with the updated literal.

- [ ] **Step 3.2: Write the failing tests for new behavior**

Append to `tests/test_writer.py`:

```python
def test_append_conversation_emits_我_for_human_role(tmp_path):
    """Writer outputs `### [我] ...` when role is HUMAN."""
    from datetime import datetime
    from src.board.writer import append_conversation
    from src.models import ConversationEntry, ConversationRole

    p = tmp_path / "task.md"
    p.write_text("---\nid: \"1\"\ntitle: t\n---\n## 对话\n", encoding="utf-8")

    entry = ConversationEntry(
        role=ConversationRole.HUMAN,
        timestamp=datetime(2026, 5, 2, 7, 35),
        content="hi",
    )
    append_conversation(p, entry)

    text = p.read_text(encoding="utf-8")
    assert "### [我] 2026-05-02 07:35" in text
    assert "### [Human]" not in text


def test_append_placeholder_appends_block(tmp_path):
    """append_placeholder writes `### [我] now` + the placeholder body."""
    from src.board.parser import PLACEHOLDER_TEXT
    from src.board.writer import append_placeholder

    p = tmp_path / "task.md"
    p.write_text(
        "---\nid: \"1\"\ntitle: t\n---\n## 对话\n### [AI] 2026-05-02 07:32\nreply\n",
        encoding="utf-8",
    )

    append_placeholder(p)

    text = p.read_text(encoding="utf-8")
    assert PLACEHOLDER_TEXT in text
    # Must come after the AI reply
    assert text.index("### [AI]") < text.index(PLACEHOLDER_TEXT)
    # Must include a [我] header right before the placeholder body
    after_ai = text[text.index("### [AI]"):]
    assert "### [我] " in after_ai


def test_append_placeholder_is_idempotent(tmp_path):
    """Calling append_placeholder twice does NOT stack two placeholder turns."""
    from src.board.parser import PLACEHOLDER_TEXT
    from src.board.writer import append_placeholder

    p = tmp_path / "task.md"
    p.write_text(
        "---\nid: \"1\"\ntitle: t\n---\n## 对话\n### [AI] 2026-05-02 07:32\nreply\n",
        encoding="utf-8",
    )

    append_placeholder(p)
    text_after_first = p.read_text(encoding="utf-8")
    append_placeholder(p)
    text_after_second = p.read_text(encoding="utf-8")

    assert text_after_first == text_after_second
    # Exactly one occurrence of the placeholder body
    assert text_after_second.count(PLACEHOLDER_TEXT) == 1
```

- [ ] **Step 3.3: Run tests to verify they fail**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_writer.py -v -k "append_placeholder or emits_我"`
Expected: FAIL — `append_placeholder` does not exist.

- [ ] **Step 3.4: Implement `append_placeholder`**

Append to `src/board/writer.py`:

```python
def append_placeholder(path: Path) -> None:
    """Append a pending [我] placeholder turn at the end of the task file.

    Idempotent: if the file already ends with a pending placeholder
    turn (per parser's is_pending_placeholder_turn), this is a no-op.
    Otherwise appends:

        ### [我] <now>
        *(在这里写下一条，保存即触发)*

    The header timestamp is set to datetime.now(); it's a visual marker
    only and not consumed by any logic.
    """
    from src.board.parser import PLACEHOLDER_TEXT, is_pending_placeholder_turn, parse_task_file

    try:
        task = parse_task_file(path)
    except Exception:  # pylint: disable=broad-except
        # Malformed file — treat as needing a placeholder; the user can
        # still benefit from the scaffold even if frontmatter has issues.
        task = None

    if task is not None and is_pending_placeholder_turn(task):
        return

    text = path.read_text(encoding="utf-8")
    header = f"### [我] {_format_dt(datetime.now())}"
    block = f"{header}\n{PLACEHOLDER_TEXT}\n"
    new_text = text.rstrip() + "\n\n" + block
    path.write_text(new_text, encoding="utf-8")
```

If `datetime` and `Path` are not already imported at the top of `writer.py`, add them. (They already are — `_format_dt` and `append_conversation` use them.)

- [ ] **Step 3.5: Run tests to verify they pass**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_writer.py -v`
Expected: PASS.

- [ ] **Step 3.6: Commit**

```bash
git add src/board/writer.py tests/test_writer.py
git commit -m "feat(writer): emit [我] header + add append_placeholder helper"
```

---

## Task 4: Orchestrator skips cycle when last entry is pending placeholder

**Files:**
- Modify: `src/agent/orchestrator.py:77` (`run_cycle`)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 4.1: Write the failing test**

Append to `tests/test_orchestrator.py`:

```python
def test_run_cycle_skips_when_last_entry_is_pending_placeholder(tmp_path):
    """A title-only file ending with a pending placeholder must NOT trigger
    an LLM cycle. Used when watcher fires on an mtime-only save (e.g.,
    Obsidian Sync touch) where the conversation hasn't advanced.
    """
    import asyncio

    tasks = _kanban(tmp_path)
    target = tasks / "doing" / "010-test.md"
    target.write_text(
        "---\n"
        'id: "010"\n'
        "title: t\n"
        "created: 2026-05-02 07:00\n"
        "updated: 2026-05-02 07:00\n"
        "---\n"
        "## 对话\n"
        "### [AI] 2026-05-02 07:32\n"
        "reply\n"
        "\n"
        "### [我] 2026-05-02 07:32\n"
        "*(在这里写下一条，保存即触发)*\n",
        encoding="utf-8",
    )

    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "rules.md").write_text("# rules\n", encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()

    llm = _llm_with_responses(_final_text("should-not-be-called"))
    orch = Orchestrator(
        tasks_dir=tasks,
        skills_dir=skills,
        logs_dir=logs,
        llm=llm,
        tools=[],
        suppress_self=_noop_suppress,
    )
    asyncio.run(orch.run_cycle(target))

    # LLM was NOT called because the task is pending the user's input.
    assert llm.chat.await_count == 0
    # File still in doing/ untouched.
    assert target.exists()
```

- [ ] **Step 4.2: Run test to verify it fails**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_orchestrator.py::test_run_cycle_skips_when_last_entry_is_pending_placeholder -v`
Expected: FAIL — `llm.chat.await_count` is 1 (orchestrator called LLM despite pending placeholder).

- [ ] **Step 4.3: Wire skip-on-pending into run_cycle**

In `src/agent/orchestrator.py`, update the import on line 21 from:

```python
from src.board.parser import TaskFileMalformed, enrich_minimal_task, parse_task_file
```

to:

```python
from src.board.parser import (
    TaskFileMalformed,
    enrich_minimal_task,
    is_pending_placeholder_turn,
    parse_task_file,
)
```

In `run_cycle` (line 77 area), AFTER the existing `task = parse_task_file(path)` succeeds and BEFORE the intent-handling block (the line `if task.intent is not None:` ~line 110), insert:

```python
            # Skip cycle when the last conversation entry is a pending
            # placeholder (user hasn't typed a real reply yet). This avoids
            # echo cycles from mtime-only saves and from daemon's own
            # placeholder writes that escape the suppress_self window.
            if is_pending_placeholder_turn(task):
                self.logger.log(LogEntry(
                    task_id=task.id, action="cycle_skipped",
                    detail="reason=pending_placeholder",
                ))
                return
```

- [ ] **Step 4.4: Run test to verify it passes**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_orchestrator.py::test_run_cycle_skips_when_last_entry_is_pending_placeholder -v`
Expected: PASS.

- [ ] **Step 4.5: Commit**

```bash
git add src/agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): skip cycle when last entry is pending placeholder"
```

---

## Task 5: Orchestrator appends placeholder after each AI reply

**Files:**
- Modify: `src/agent/orchestrator.py:185-191` (the `with self.suppress_self()` block)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 5.1: Update existing tests broken by the rename**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_orchestrator.py -v 2>&1 | grep FAIL | head -10`

For each failure that asserts `"### [Human]"` in expected output, change to `"### [我]"` — do NOT weaken assertions. Re-run until non-new tests pass.

- [ ] **Step 5.2: Write the failing test for new behavior**

Append to `tests/test_orchestrator.py`:

```python
def test_run_cycle_appends_placeholder_after_ai_reply(tmp_path):
    """End-to-end: after a normal cycle, file ends with a fresh placeholder."""
    import asyncio
    from src.board.parser import PLACEHOLDER_TEXT

    tasks = _kanban(tmp_path)
    target = tasks / "todo" / "新需求.md"
    target.write_text(
        "---\n"
        'id: "020"\n'
        "title: t\n"
        "created: 2026-05-02 07:00\n"
        "updated: 2026-05-02 07:00\n"
        "---\n## 任务描述\n问问题\n",
        encoding="utf-8",
    )

    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "rules.md").write_text("# rules\n", encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()

    llm = _llm_with_responses(_final_text("回答"))
    orch = Orchestrator(
        tasks_dir=tasks,
        skills_dir=skills,
        logs_dir=logs,
        llm=llm,
        tools=[],
        suppress_self=_noop_suppress,
    )
    asyncio.run(orch.run_cycle(target))

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
    # File ends with a placeholder block
    assert PLACEHOLDER_TEXT in text
    # Placeholder is AFTER the AI reply
    assert text.index("回答") < text.index(PLACEHOLDER_TEXT)
    # LLM was called exactly once
    assert llm.chat.await_count == 1
```

- [ ] **Step 5.3: Run test to verify it fails**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_orchestrator.py::test_run_cycle_appends_placeholder_after_ai_reply -v`
Expected: FAIL — placeholder is not appended.

- [ ] **Step 5.4: Wire append_placeholder into run_cycle**

In `src/agent/orchestrator.py`, update the writer import on line 22 from:

```python
from src.board.writer import append_conversation, write_task_file
```

to:

```python
from src.board.writer import append_conversation, append_placeholder, write_task_file
```

In `run_cycle` (line ~185), find the existing `with self.suppress_self():` block:

```python
            with self.suppress_self():
                self._append_ai_reply(path, final_text)
                if next_status != current_status:
                    new_path = self.manager.move_task(path, next_status)
```

Change it to:

```python
            with self.suppress_self():
                self._append_ai_reply(path, final_text)
                if next_status != current_status:
                    new_path = self.manager.move_task(path, next_status)
                # Scaffold the next [我] turn so the user can just overwrite
                # the placeholder line and save. Idempotent — safe even if
                # downstream code calls it again.
                append_placeholder(new_path)
```

- [ ] **Step 5.5: Run test to verify it passes**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_orchestrator.py::test_run_cycle_appends_placeholder_after_ai_reply -v`
Expected: PASS.

- [ ] **Step 5.6: Run the full suite**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest 2>&1 | tail -3`
Expected: PASS overall (modulo the pre-existing `test_config_loads_defaults` and any 3 cli daemon flakes).

- [ ] **Step 5.7: Commit**

```bash
git add src/agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): append placeholder after each AI reply"
```

---

## Task 6: Replay back-fills placeholder for pre-existing doing/ files

**Files:**
- Modify: `src/agent/orchestrator.py:206` (`replay_pending_intents`)
- Test: `tests/test_orchestrator.py`

**Why:** Tasks already in `tasks/doing/` from before this feature shipped (e.g., `001-财务数据分析.md`) end with an `[AI]` reply but no placeholder. On daemon startup, the replay loop adds a placeholder to those files (without running a cycle), so the next time the user opens them the UX is consistent.

**Scope rule (narrow):** Only DOING column. Only when last entry is `AI`. Only if no placeholder is already there.

- [ ] **Step 6.1: Write the failing test**

Append to `tests/test_orchestrator.py`:

```python
def test_replay_backfills_placeholder_for_pre_existing_doing_file(tmp_path):
    """A doing/ file ending with [AI] (no placeholder) gets one appended on
    daemon startup replay. The file does NOT trigger a cycle."""
    import asyncio
    from src.board.parser import PLACEHOLDER_TEXT

    tasks = _kanban(tmp_path)
    target = tasks / "doing" / "030-old.md"
    target.write_text(
        "---\n"
        'id: "030"\n'
        "title: t\n"
        "created: 2026-05-01 14:00\n"
        "updated: 2026-05-01 14:05\n"
        "---\n"
        "## 对话\n"
        "### [我] 2026-05-01 14:00\n"
        "old question\n"
        "### [AI] 2026-05-01 14:05\n"
        "old reply (no placeholder yet)\n",
        encoding="utf-8",
    )

    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "rules.md").write_text("# rules\n", encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()

    llm = _llm_with_responses(_final_text("should-not-be-called"))
    orch = Orchestrator(
        tasks_dir=tasks,
        skills_dir=skills,
        logs_dir=logs,
        llm=llm,
        tools=[],
        suppress_self=_noop_suppress,
    )
    asyncio.run(orch.replay_pending_intents())

    # Placeholder appended; LLM not called.
    text = target.read_text(encoding="utf-8")
    assert PLACEHOLDER_TEXT in text
    assert llm.chat.await_count == 0
```

- [ ] **Step 6.2: Run test to verify it fails**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_orchestrator.py::test_replay_backfills_placeholder_for_pre_existing_doing_file -v`
Expected: FAIL — placeholder absent.

- [ ] **Step 6.3: Wire replay back-fill**

In `src/agent/orchestrator.py`, in `replay_pending_intents` (line 206 area), find the inner loop that already calls enrich + parse + checks intent. After parsing the task and BEFORE the `if task.intent is None: continue` check, insert:

```python
                # One-time back-fill: pre-existing doing/ files that ended
                # with an [AI] reply (no placeholder yet) get a placeholder
                # appended so the rest-of-system invariant — every doing/
                # file ends with a pending [我] turn — holds. Skip cycle:
                # the user hasn't actually replied.
                from src.models import ConversationRole, TaskStatus
                if (
                    status == TaskStatus.DOING
                    and task.intent is None
                    and task.conversation
                    and task.conversation[-1].role is ConversationRole.AI
                ):
                    with self.suppress_self():
                        try:
                            append_placeholder(path)
                        except OSError as e:
                            self.logger.log_system(
                                action="replay_placeholder_failed",
                                detail=f"path={path} err={e}",
                                status="error",
                            )
                    self.logger.log_system(
                        action="replay_placeholder_backfill",
                        detail=f"path={path}",
                    )
                    continue
```

(The `from src.models import ConversationRole, TaskStatus` line is added in-block to avoid touching the file-level import unless necessary — `TaskStatus` is already imported there, so it's safe to remove the local import once moved up. For minimal diff, the local import is fine.)

If `append_placeholder` is not yet in this file's imports, add it to the writer import line.

- [ ] **Step 6.4: Run test to verify it passes**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest tests/test_orchestrator.py::test_replay_backfills_placeholder_for_pre_existing_doing_file -v`
Expected: PASS.

- [ ] **Step 6.5: Run the full suite**

Run: `cd <your-user>/projects/cc-assitant && python -m pytest 2>&1 | tail -3`
Expected: PASS overall.

- [ ] **Step 6.6: Commit**

```bash
git add src/agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): replay back-fills placeholder for pre-existing doing/ files"
```

---

## Task 7: Document the placeholder-overwrite UX

**Files:**
- Modify: `tasks/README.md`

- [ ] **Step 7.1: Append docs**

Append to `tasks/README.md`:

```markdown

## 怎么继续對話

從 2026-05-02 起,daemon 跑完一輪 [AI] 回覆後會在文件最末尾留一條:

\`\`\`
### [我] 時間
*(在这里写下一条，保存即触发)*
\`\`\`

要繼續對話,**選中那一行斜體的占位文字、覆寫成你的真問題、保存**。daemon 會跑下一輪、追加 [AI] 回覆、然後再寫一條新占位。

什麼動作會被識別為新一輪:

| 動作 | daemon 反應 |
|---|---|
| 覆寫占位文字 → 真內容 → 存 | ✅ 跑 LLM |
| 占位文字原樣保存(只是 mtime 變了) | ⏸ 跳過 |
| 占位文字刪空 → 啥也沒寫 → 存 | ⏸ 跳過(防呆) |
| 在中間插入文字 | 維持原來行為(可能被 parser 吞;不推薦) |

舊文件用 `### [Human] ...` 標頭的依然能解析。新寫入都用 `### [我] ...`。
```

- [ ] **Step 7.2: Commit**

```bash
git add tasks/README.md
git commit -m "docs(tasks): document placeholder-overwrite reply UX"
```

---

## Self-review notes

**Spec coverage check** (against `2026-05-02-placeholder-conversation-turn-design.md`):

- ConversationRole rename + back-compat → Task 1.
- Parser regex update + `PLACEHOLDER_TEXT` + `is_pending_placeholder_turn` → Task 2.
- Writer `append_placeholder` (idempotent) → Task 3.
- Orchestrator skip on pending placeholder → Task 4.
- Orchestrator append placeholder after AI reply → Task 5.
- Orchestrator replay back-fill → Task 6.
- README docs → Task 7.

13 tests promised in spec, plan has: 4 in test_models.py (Task 1 added one extra for AI symmetry), 7 in test_parser.py (Task 2), 3 in test_writer.py (Task 3), 3 in test_orchestrator.py (Tasks 4-6) = **17 new tests total** (4 model + 7 parser + 3 writer + 3 orchestrator). The extra ones (model AI test, the `last_is_ai` parser test which was already in spec) cover edge cases — strictly more, never less.

**Placeholder scan:** none. Each step has concrete code or commands. The only deferred decision is in Task 6 step 6.3 ("local import for minimal diff") — that's a style note, not a placeholder.

**Type consistency:** `ConversationRole.HUMAN.value == "我"` used identically across model/parser/writer. `PLACEHOLDER_TEXT` constant defined in parser, imported by writer + orchestrator. `is_pending_placeholder_turn(task: Task) -> bool` signature consistent. `append_placeholder(path: Path) -> None` consistent.

**Backward compatibility:** every change preserves existing file parseability (Task 1 `_missing_`, Task 2 regex `Human|我|AI`). Existing-test updates (Tasks 3.1, 5.1) are limited to changing literal `"### [Human]"` to `"### [我]"` in writer-output assertions — no test gets weakened.
