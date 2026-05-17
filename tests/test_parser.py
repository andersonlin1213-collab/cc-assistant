from datetime import datetime
from pathlib import Path

import pytest

from src.board.parser import parse_task_file, parse_task_string
from src.models import Priority, ConversationRole, SubtaskStatus


SAMPLE_TASK = """\
---
id: "025"
title: 个人 portfolio 网站
project: portfolio-website
parent: null
priority: P1
tags: [frontend, design]
created: 2026-04-26 14:00
updated: 2026-04-26 15:31
auto_approve: true
depends_on: []
instructions: |
  请优先使用 Tailwind CSS。
  设计语言保持极简。
subtasks:
  - id: "025-1"
    title: 设计风格选型
    status: blocked
    blocking_reason: 需要用户从方案 A/B/C 中选择
  - id: "025-2"
    title: 实现首页布局
    status: doing
---

## 任务描述
做一个个人作品集网站，三端布局同步完成。

## 对话

### [Human] 2026-04-26 14:00
帮我做一个 portfolio 网站。

### [AI] 2026-04-26 14:02
准备了三种方案：A. 极简黑白；B. 渐变彩色；C. 复古印刷风。请选一个。

### [Human] 2026-04-26 15:30
选 A。
"""


def test_parse_frontmatter_basic():
    task = parse_task_string(SAMPLE_TASK)
    assert task.id == "025"
    assert task.title == "个人 portfolio 网站"
    assert task.priority == Priority.P1
    assert task.tags == ["frontend", "design"]
    assert task.auto_approve is True


def test_parse_new_fields():
    """project, parent, instructions all parsed."""
    task = parse_task_string(SAMPLE_TASK)
    assert task.project == "portfolio-website"
    assert task.parent is None
    assert "Tailwind CSS" in task.instructions
    assert "设计语言保持极简" in task.instructions


def test_parse_subtasks_with_blocking_reason():
    task = parse_task_string(SAMPLE_TASK)
    assert len(task.subtasks) == 2
    assert task.subtasks[0].id == "025-1"
    assert task.subtasks[0].status == SubtaskStatus.BLOCKED
    assert task.subtasks[0].blocking_reason == "需要用户从方案 A/B/C 中选择"
    assert task.subtasks[1].status == SubtaskStatus.DOING
    assert task.subtasks[1].blocking_reason is None


def test_parse_description():
    task = parse_task_string(SAMPLE_TASK)
    assert "三端布局同步完成" in task.description


def test_parse_conversation():
    task = parse_task_string(SAMPLE_TASK)
    assert len(task.conversation) == 3
    assert task.conversation[0].role == ConversationRole.HUMAN
    assert "portfolio 网站" in task.conversation[0].content
    assert task.conversation[1].role == ConversationRole.AI
    assert "三种方案" in task.conversation[1].content


def test_parse_conversation_timestamps():
    task = parse_task_string(SAMPLE_TASK)
    assert task.conversation[0].timestamp == datetime(2026, 4, 26, 14, 0)
    assert task.conversation[1].timestamp == datetime(2026, 4, 26, 14, 2)
    assert task.conversation[2].timestamp == datetime(2026, 4, 26, 15, 30)


def test_parse_file(tmp_path):
    f = tmp_path / "025-portfolio.md"
    f.write_text(SAMPLE_TASK, encoding="utf-8")
    task = parse_task_file(f)
    assert task.id == "025"
    assert task.source_path == str(f)


def test_parse_minimal_task():
    """Task with no project, no parent, no instructions, no subtasks should still parse."""
    md = """\
---
id: "002"
title: Simple task
priority: P2
tags: []
created: 2026-04-26 10:00
updated: 2026-04-26 10:00
auto_approve: true
depends_on: []
subtasks: []
---

## 任务描述
Do something.

## 对话
"""
    task = parse_task_string(md)
    assert task.id == "002"
    assert task.project == ""
    assert task.parent is None
    assert task.instructions == ""
    assert len(task.conversation) == 0


def test_parse_parent_id():
    """parent field can be a string id."""
    md = """\
---
id: "025-1-1"
title: Child task
project: portfolio-website
parent: "025-1"
priority: P1
tags: []
created: 2026-04-26 10:00
updated: 2026-04-26 10:00
auto_approve: true
depends_on: []
subtasks: []
---

## 任务描述
Subtask details.

## 对话
"""
    task = parse_task_string(md)
    assert task.parent == "025-1"


def test_parse_conversation_stops_at_next_h2():
    """A `## 执行日志` (or any) H2 after the conversation must not bleed into the last entry."""
    md = """\
---
id: "001"
title: Test
priority: P1
tags: []
created: 2026-04-26 14:00
updated: 2026-04-26 14:00
auto_approve: true
depends_on: []
subtasks: []
---

## 任务描述
Test.

## 对话

### [Human] 2026-04-26 14:00
First message.

### [AI] 2026-04-26 14:01
AI reply.

## 执行日志
> 详细日志见 logs/001.jsonl
"""
    task = parse_task_string(md)
    assert len(task.conversation) == 2
    assert task.conversation[1].content == "AI reply."
    assert "执行日志" not in task.conversation[1].content


def test_parser_reads_new_fields():
    from src.models import Who, TaskType

    fixtures = Path(__file__).parent / "fixtures"
    task = parse_task_file(fixtures / "task_with_new_fields.md")
    assert task.who == Who.HUMAN
    assert task.when == "本周日"
    assert task.type == TaskType.COMPLEX
    assert task.intent is None
    assert task.measure.strip().startswith("1) 第一条")
    assert task.why == "因为"
    assert task.source_files == ["src/a.py", "docs/b.md"]
    assert task.status_reason == "等用户"


def test_parser_falls_back_to_defaults_when_new_fields_missing():
    """Old task files without new fields still parse with defaults."""
    from src.models import Who

    text = """\
---
id: "100"
title: 旧任务
project: ""
parent: null
priority: P1
tags: []
created: 2026-04-26 10:00
updated: 2026-04-26 10:00
auto_approve: true
depends_on: []
instructions: ""
subtasks: []
---

## 任务描述
old

## 对话
"""
    task = parse_task_string(text)
    assert task.who == Who.CLAUDE
    assert task.when is None
    assert task.type is None
    assert task.intent is None
    assert task.measure == ""
    assert task.why == ""
    assert task.source_files == []
    assert task.status_reason is None


def test_parser_raises_task_file_malformed_when_title_missing():
    """A draft file (e.g. created on mobile without filling out frontmatter)
    must raise a typed TaskFileMalformed instead of a cryptic KeyError when
    the only required field — `title` — is absent."""
    from src.board.parser import TaskFileMalformed

    text = """\
---
priority: P1
who: claude
when: 今晚
project: cc-assistant-2
intent: null
---

just some draft notes a user typed on mobile
"""
    with pytest.raises(TaskFileMalformed) as exc_info:
        parse_task_string(text)
    assert "title" in str(exc_info.value)


def test_parser_synthesizes_defaults_when_created_empty():
    """Empty `created`/`updated` (the case the default template hits) no longer
    raises — the parser synthesizes the epoch as a sentinel, leaving enrichment
    to overwrite it on first daemon touch."""
    text = """\
---
id: "999"
title: t
created: ""
updated: ""
---
"""
    task = parse_task_string(text)
    assert task.id == "999"
    assert task.title == "t"
    assert task.created == datetime.fromtimestamp(0)
    assert task.updated == datetime.fromtimestamp(0)


def test_parser_raises_task_file_malformed_when_no_frontmatter():
    """A file with no frontmatter at all is also malformed (not a task)."""
    from src.board.parser import TaskFileMalformed

    text = "just a markdown note, no frontmatter\n"
    with pytest.raises(TaskFileMalformed):
        parse_task_string(text)


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


def test_parse_tolerates_null_priority():
    """Real-world: a task file with `priority: null` (e.g. mobile Obsidian
    quick-create defaults) must parse to default P1, not raise.
    """
    from src.models import Priority
    text = (
        "---\n"
        'id: "001"\n'
        "title: t\n"
        "priority: null\n"
        "created: 2026-05-02 10:00\n"
        "updated: 2026-05-02 10:00\n"
        "---\n"
        "body\n"
    )
    task = parse_task_string(text)
    assert task.priority is Priority.P1


def test_parse_body_does_not_truncate_at_h2_inside_ai_reply():
    """Real-world bug (003-零售顾问专家.md, 2026-05-02): an AI reply
    contained a `## 🔒 安全先看` heading. The old _parse_body split on any
    `^## ` and discarded everything after — including all subsequent
    `### [我]` / `### [AI]` entries. Parser then thought the last entry
    was the [AI] containing the H2, and replay kept appending placeholder
    backfills indefinitely.

    Parser must keep parsing until end of file; H2 sub-headings inside an
    AI reply belong to that entry's content, NOT a section terminator.
    """
    text = (
        "---\n"
        'id: "003"\n'
        "title: t\n"
        "created: 2026-05-02 10:00\n"
        "updated: 2026-05-02 10:00\n"
        "---\n"
        "## 对话\n"
        "### [AI] 2026-05-02 11:08\n"
        "回复正文。\n"
        "\n"
        "## 🔒 安全先看\n"
        "(子标题在回复正文里)\n"
        "\n"
        "### [我] 2026-05-02 11:41\n"
        "用户的下一轮问题\n"
    )
    task = parse_task_string(text)
    assert len(task.conversation) == 2, (
        f"Expected 2 entries (AI + 我), parser saw {len(task.conversation)}. "
        f"Last entry: {task.conversation[-1].role.value if task.conversation else None}"
    )
    from src.models import ConversationRole
    assert task.conversation[0].role is ConversationRole.AI
    assert task.conversation[1].role is ConversationRole.HUMAN
    assert task.conversation[1].content == "用户的下一轮问题"
    # The H2 sub-heading is part of the AI entry's content
    assert "## 🔒 安全先看" in task.conversation[0].content


def test_is_pending_placeholder_returns_false_when_user_appends_below_placeholder():
    """Real-world failure mode (observed on tasks/doing/003-零售顾问专家.md
    2026-05-02): user types real content BELOW the italicised placeholder
    line instead of overwriting it. The entry's content contains BOTH the
    placeholder string AND extra real text. We must NOT treat this as
    pending — the user clearly responded, just with sloppy formatting.
    """
    from src.board.parser import PLACEHOLDER_TEXT, is_pending_placeholder_turn
    from src.models import ConversationEntry, ConversationRole, Task
    from datetime import datetime
    task = Task(
        id="003",
        title="t",
        created=datetime(2026, 5, 2),
        updated=datetime(2026, 5, 2),
        conversation=[
            ConversationEntry(
                role=ConversationRole.HUMAN,
                timestamp=datetime(2026, 5, 2, 21, 42),
                content=f"{PLACEHOLDER_TEXT}\n\nA\n\n另外我想知道你保存到本地的那一个资料夹",
            ),
        ],
    )
    assert is_pending_placeholder_turn(task) is False


def test_parse_conversation_header_tolerates_date_only_and_suffix():
    """Real-world failure mode observed on 002-跨境电商流程化.md 2026-05-03:
    user/AI handwrote entry headers with the time-of-day missing or a free-
    form suffix tacked on. Examples that the strict regex used to drop:

        ### [我] 2026-05-03                          ← date-only
        ### [AI] 2026-05-02 10:50 — 整合稿           ← suffix after HH:MM
        ### [AI] 2026-05-03 — 跳过本轮               ← date-only + suffix

    When the parser dropped these as body text, downstream
    `is_pending_placeholder_turn` reported True (the previous real entry
    was a placeholder), and orchestrator skipped the task forever. Parser
    must accept all three variants; date-only headers fall back to 00:00.
    """
    text = (
        "---\n"
        'id: "001"\n'
        "title: t\n"
        "created: 2026-05-02 10:00\n"
        "updated: 2026-05-03 13:14\n"
        "---\n"
        "\n"
        "## 任务描述\n"
        "正文。\n"
        "\n"
        "## 对话\n"
        "### [AI] 2026-05-02 10:50 — 整合稿（替代之前 20+ 轮重复方案）\n"
        "整合内容。\n"
        "\n"
        "### [我] 2026-05-02 23:37\n"
        "*(在这里写下一条，保存即触发)*\n"
        "\n"
        "### [AI] 2026-05-03 — 跳过本轮\n"
        "本轮零追加。\n"
        "\n"
        "### [我] 2026-05-03\n"
        "现在跑到哪里了？\n"
    )
    from src.board.parser import is_pending_placeholder_turn
    task = parse_task_string(text)
    assert len(task.conversation) == 4
    assert task.conversation[0].role is ConversationRole.AI
    assert task.conversation[0].timestamp == datetime(2026, 5, 2, 10, 50)
    assert task.conversation[0].content.startswith("整合内容")
    assert task.conversation[2].role is ConversationRole.AI
    assert task.conversation[2].timestamp == datetime(2026, 5, 3, 0, 0)
    assert task.conversation[2].content == "本轮零追加。"
    assert task.conversation[3].role is ConversationRole.HUMAN
    assert task.conversation[3].timestamp == datetime(2026, 5, 3, 0, 0)
    assert task.conversation[3].content == "现在跑到哪里了？"
    # End-to-end: the user's last entry is real content, so the cycle
    # must not be skipped as pending_placeholder.
    assert is_pending_placeholder_turn(task) is False


def test_parse_conversation_when_对话_header_missing():
    """Real-world failure mode (observed on tasks/doing/001-财务数据分析.md
    2026-05-03): file ends up with `### [AI]/[我]` entries directly under
    `## 任务描述` with no `## 对话` heading between them. Without the fallback,
    parser returns empty conversation, `is_pending_placeholder_turn` returns
    False, and the orchestrator polls the task forever (20+ idle rounds
    observed). Parser must split on the first conversation header and
    populate task.conversation accordingly.
    """
    text = (
        "---\n"
        'id: "001"\n'
        "title: t\n"
        "created: 2026-05-02 12:00\n"
        "updated: 2026-05-02 12:00\n"
        "---\n"
        "\n"
        "## 任务描述\n"
        "原始任务正文。\n"
        "\n"
        "### [AI] 2026-05-02 12:00\n"
        "AI 第一轮回复。\n"
        "\n"
        "### [我] 2026-05-02 12:30\n"
        "*(在这里写下一条，保存即触发)*\n"
    )
    task = parse_task_string(text)
    assert task.description == "原始任务正文。"
    assert len(task.conversation) == 2
    assert task.conversation[0].role is ConversationRole.AI
    assert task.conversation[0].content == "AI 第一轮回复。"
    assert task.conversation[1].role is ConversationRole.HUMAN


def test_is_pending_placeholder_when_对话_header_missing():
    """End-to-end: parse a file lacking `## 对话` but ending with a placeholder
    `[我]` block must still let `is_pending_placeholder_turn` return True so
    the orchestrator skips the cycle. This is the exact loop that burned
    20+ idle rounds on 001-财务数据分析.md.
    """
    from src.board.parser import is_pending_placeholder_turn
    text = (
        "---\n"
        'id: "001"\n'
        "title: t\n"
        "created: 2026-05-02 12:00\n"
        "updated: 2026-05-02 12:00\n"
        "---\n"
        "\n"
        "## 任务描述\n"
        "正文。\n"
        "\n"
        "### [AI] 2026-05-03 07:25\n"
        "第 20 轮空转，无新指令。本轮不动。\n"
        "\n"
        "### [我] 2026-05-03 07:25\n"
        "*(在这里写下一条，保存即触发)*\n"
    )
    task = parse_task_string(text)
    assert is_pending_placeholder_turn(task) is True


def test_parse_unknown_who_value_raises_task_file_malformed():
    """Real-world failure 5/6: ahf-* tasks had `who: ai` (typo for `claude`),
    which raised bare `ValueError` from `Who('ai')`, bypassed run_cycle's
    `except TaskFileMalformed`, and only landed in watcher_callback_failed
    logs — invisible to the user. Parser must re-wrap so the orchestrator's
    `[系统]` marker surfaces the bad value in Obsidian."""
    text = (
        "---\n"
        'id: "001"\n'
        "title: t\n"
        "who: ai\n"
        "created: 2026-05-06 10:00\n"
        "updated: 2026-05-06 10:00\n"
        "---\n\n"
        "## 任务描述\n正文。\n"
    )
    with pytest.raises(
        __import__("src.board.parser", fromlist=["TaskFileMalformed"]).TaskFileMalformed,
        match="enum",
    ):
        parse_task_string(text)


def test_parse_unknown_priority_value_raises_task_file_malformed():
    """Same family: `priority: P5` (typo) used to raise ValueError from
    `Priority('P5')`. Must surface as TaskFileMalformed."""
    text = (
        "---\n"
        'id: "001"\n'
        "title: t\n"
        "priority: P5\n"
        "created: 2026-05-06 10:00\n"
        "updated: 2026-05-06 10:00\n"
        "---\n\n"
        "## 任务描述\n正文。\n"
    )
    with pytest.raises(
        __import__("src.board.parser", fromlist=["TaskFileMalformed"]).TaskFileMalformed,
    ):
        parse_task_string(text)


def test_parse_system_role_header():
    """`### [系统] <ts>` parses as a SYSTEM conversation entry. Used by
    the orchestrator to surface non-LLM failures (provider_unavailable,
    etc.) directly in the file so the user sees them in Obsidian."""
    text = (
        "---\n"
        'id: "001"\n'
        "title: t\n"
        "created: 2026-05-06 10:00\n"
        "updated: 2026-05-06 10:00\n"
        "---\n\n"
        "## 任务描述\n正文。\n\n"
        "## 对话\n"
        "### [系统] 2026-05-06 10:30\n"
        "无法跑这一轮:provider 不可用。\n"
    )
    task = parse_task_string(text)
    assert len(task.conversation) == 1
    assert task.conversation[0].role is ConversationRole.SYSTEM
    assert "无法跑这一轮" in task.conversation[0].content


def test_is_pending_placeholder_ignores_trailing_system_entry():
    """A trailing [系统] entry (without a [我] placeholder following) is
    not pending — `is_pending_placeholder_turn` only returns True for
    HUMAN placeholders. This means a malformed sequence (system entry
    not followed by placeholder) won't suppress cycles forever."""
    from src.board.parser import is_pending_placeholder_turn
    text = (
        "---\n"
        'id: "001"\n'
        "title: t\n"
        "created: 2026-05-06 10:00\n"
        "updated: 2026-05-06 10:00\n"
        "---\n\n"
        "## 任务描述\n正文。\n\n"
        "## 对话\n"
        "### [我] 2026-05-06 10:30\n"
        "用户输入。\n\n"
        "### [系统] 2026-05-06 10:31\n"
        "provider 不可用。\n"
    )
    task = parse_task_string(text)
    assert is_pending_placeholder_turn(task) is False


def test_parse_provider_field_explicit():
    """The `provider:` frontmatter is what LLMRouter consults to override
    config default + tag escalation. Explicit value must round-trip."""
    text = (
        "---\n"
        'id: "001"\n'
        "title: t\n"
        "provider: claude\n"
        "created: 2026-05-06 10:00\n"
        "updated: 2026-05-06 10:00\n"
        "---\n\n"
        "## 任务描述\n正文。\n"
    )
    task = parse_task_string(text)
    assert task.provider == "claude"


def test_parse_provider_field_absent():
    """Missing `provider:` parses to None — router falls back to config
    default. This is the common case (most tasks don't pin a provider)."""
    text = (
        "---\n"
        'id: "001"\n'
        "title: t\n"
        "created: 2026-05-06 10:00\n"
        "updated: 2026-05-06 10:00\n"
        "---\n\n"
        "## 任务描述\n正文。\n"
    )
    task = parse_task_string(text)
    assert task.provider is None


def test_parse_provider_field_yaml_null_and_empty():
    """`provider: null` and `provider: ""` both reduce to None — same
    sentinel handling as `parent`/`type`/`intent` in the parser. Mobile
    Obsidian sometimes inserts `null` literals from template defaults."""
    for raw_value in ("null", '""'):
        text = (
            "---\n"
            'id: "001"\n'
            "title: t\n"
            f"provider: {raw_value}\n"
            "created: 2026-05-06 10:00\n"
            "updated: 2026-05-06 10:00\n"
            "---\n\n"
            "## 任务描述\n正文。\n"
        )
        task = parse_task_string(text)
        assert task.provider is None, f"raw_value={raw_value!r} produced {task.provider!r}"


def test_parse_provider_field_strips_whitespace():
    """User typed `provider: claude_cli  ` with trailing spaces — strip
    so router's case-insensitive comparison works."""
    text = (
        "---\n"
        'id: "001"\n'
        "title: t\n"
        'provider: "  claude_cli  "\n'
        "created: 2026-05-06 10:00\n"
        "updated: 2026-05-06 10:00\n"
        "---\n\n"
        "## 任务描述\n正文。\n"
    )
    task = parse_task_string(text)
    assert task.provider == "claude_cli"


def test_parse_canonical_file_emits_no_warnings():
    """Forgive-then-warn must be silent on the happy path. Any parser_warning
    on a canonical file would be log noise that desensitizes the user to real
    edge cases."""
    task = parse_task_string(SAMPLE_TASK)
    assert task.parse_warnings == []


def test_parse_lenient_header_recovers_entry_and_warns():
    """Variant the strict regex misses (ISO `T` separator instead of space) is
    recovered by the lenient fallback so the conversation isn't silently
    dropped, AND a parser_warning surfaces so we can spot new variants in
    logs without deducing them from behavior. This is the architectural
    shift away from 'patch one regex per silent-fail bug'."""
    text = (
        "---\n"
        'id: "001"\n'
        "title: t\n"
        "created: 2026-05-05 10:00\n"
        "updated: 2026-05-05 10:00\n"
        "---\n"
        "\n"
        "## 任务描述\n"
        "正文。\n"
        "\n"
        "## 对话\n"
        "### [我] 2026-05-05T10:30:00\n"
        "ISO 8601 带 T。\n"
    )
    task = parse_task_string(text)
    assert len(task.conversation) == 1
    assert task.conversation[0].role is ConversationRole.HUMAN
    assert task.conversation[0].timestamp == datetime(2026, 5, 5, 10, 30, 0)
    assert task.conversation[0].content == "ISO 8601 带 T。"
    assert any(
        "conversation_header_lenient" in w for w in task.parse_warnings
    ), task.parse_warnings


def test_parse_unrecognized_role_drops_with_warning():
    """A `### [Foo]` block (role not in Human|我|AI) cannot be recovered, but
    must NOT silently disappear: emit a `conversation_header_dropped` warning
    so the user sees it in logs instead of debugging by deduction."""
    text = (
        "---\n"
        'id: "001"\n'
        "title: t\n"
        "created: 2026-05-05 10:00\n"
        "updated: 2026-05-05 10:00\n"
        "---\n"
        "\n"
        "## 任务描述\n"
        "正文。\n"
        "\n"
        "## 对话\n"
        "### [我] 2026-05-05 10:30\n"
        "正常一条。\n"
        "\n"
        "### [Robot] 2026-05-05 10:31\n"
        "未知角色，应被丢弃。\n"
    )
    task = parse_task_string(text)
    assert len(task.conversation) == 1
    assert task.conversation[0].role is ConversationRole.HUMAN
    assert any(
        "conversation_header_dropped" in w and "Robot" in w
        for w in task.parse_warnings
    ), task.parse_warnings


def test_parse_对话_header_missing_emits_warning():
    """The existing `## 对话` fallback already recovers the conversation; it
    just needs to surface the anomaly so the user can fix the source file
    (or template) instead of silently relying on the fallback forever."""
    text = (
        "---\n"
        'id: "001"\n'
        "title: t\n"
        "created: 2026-05-02 12:00\n"
        "updated: 2026-05-02 12:00\n"
        "---\n"
        "\n"
        "## 任务描述\n"
        "正文。\n"
        "\n"
        "### [AI] 2026-05-02 12:00\n"
        "AI 第一轮回复。\n"
    )
    task = parse_task_string(text)
    assert len(task.conversation) == 1
    assert any(
        "对话_header_missing" in w for w in task.parse_warnings
    ), task.parse_warnings


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
