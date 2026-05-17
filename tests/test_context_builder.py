from datetime import datetime

from src.agent.context import ContextBuilder
from src.models import (
    ConversationEntry,
    ConversationRole,
    Priority,
    Subtask,
    SubtaskStatus,
    Task,
)


def _make_task(**overrides) -> Task:
    defaults = dict(
        id="025",
        title="部署后端",
        project="cc-assistant",
        parent=None,
        priority=Priority.P1,
        tags=["devops"],
        created=datetime(2026, 4, 26, 14, 0),
        updated=datetime(2026, 4, 26, 14, 0),
        auto_approve=True,
        depends_on=[],
        instructions="",
        subtasks=[],
        description="把后端部署到生产。",
        conversation=[],
    )
    defaults.update(overrides)
    return Task(**defaults)


def test_build_returns_system_and_user_messages():
    builder = ContextBuilder()
    messages = builder.build(rules="# Rules\nBe careful.", task=_make_task())

    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[1].role == "user"


def test_system_message_includes_rules():
    builder = ContextBuilder()
    messages = builder.build(rules="# Custom Rules\n- Always commit.", task=_make_task())

    sys_text = messages[0].content
    assert isinstance(sys_text, str)
    assert "Custom Rules" in sys_text
    assert "Always commit." in sys_text


def test_system_message_explains_control_tools():
    """The system prompt must instruct the LLM about mark_complete and mark_blocked."""
    builder = ContextBuilder()
    messages = builder.build(rules="", task=_make_task())

    sys_text = messages[0].content
    assert "mark_complete" in sys_text
    assert "mark_blocked" in sys_text


def test_user_message_includes_task_metadata():
    builder = ContextBuilder()
    task = _make_task(
        id="025",
        title="部署后端",
        project="cc-assistant",
        priority=Priority.P0,
        tags=["devops", "urgent"],
        description="把后端部署到生产。",
    )
    messages = builder.build(rules="", task=task)

    user_text = messages[1].content
    assert isinstance(user_text, str)
    assert "025" in user_text
    assert "部署后端" in user_text
    assert "cc-assistant" in user_text
    assert "P0" in user_text
    assert "devops" in user_text
    assert "把后端部署到生产" in user_text


def test_user_message_includes_subtasks():
    builder = ContextBuilder()
    task = _make_task(
        subtasks=[
            Subtask(id="025-1", title="备份数据库", status=SubtaskStatus.DONE),
            Subtask(
                id="025-2",
                title="拉取代码",
                status=SubtaskStatus.BLOCKED,
                blocking_reason="需要确认分支",
            ),
        ]
    )
    messages = builder.build(rules="", task=task)

    user_text = messages[1].content
    assert "025-1" in user_text
    assert "备份数据库" in user_text
    assert "done" in user_text
    assert "025-2" in user_text
    assert "拉取代码" in user_text
    assert "blocked" in user_text
    assert "需要确认分支" in user_text


def test_user_message_includes_conversation_history():
    builder = ContextBuilder()
    task = _make_task(
        conversation=[
            ConversationEntry(
                role=ConversationRole.HUMAN,
                timestamp=datetime(2026, 4, 26, 14, 0),
                content="先备份数据库。",
            ),
            ConversationEntry(
                role=ConversationRole.AI,
                timestamp=datetime(2026, 4, 26, 14, 1),
                content="收到。",
            ),
        ]
    )
    messages = builder.build(rules="", task=task)

    user_text = messages[1].content
    assert "先备份数据库" in user_text
    assert "收到" in user_text
    # Roles should be visible
    assert "我" in user_text
    assert "AI" in user_text or "ai" in user_text.lower()


def test_user_message_includes_task_instructions_when_present():
    """The Task.instructions field is task-level guidance overriding rules.md."""
    builder = ContextBuilder()
    task = _make_task(instructions="使用 Tailwind CSS。设计语言保持极简。")
    messages = builder.build(rules="", task=task)

    user_text = messages[1].content
    assert "Tailwind" in user_text
    assert "极简" in user_text


def test_context_includes_why_section():
    builder = ContextBuilder()
    task = _make_task(why="为了秋招用")
    messages = builder.build(rules="", task=task)
    user_text = messages[1].content
    assert "## Motivation (why)" in user_text
    assert "为了秋招用" in user_text


def test_context_includes_measure_section():
    builder = ContextBuilder()
    task = _make_task(measure="1) 部署成功\n2) lighthouse >= 90")
    messages = builder.build(rules="", task=task)
    user_text = messages[1].content
    assert "## Success Criteria (measure)" in user_text
    assert "1) 部署成功" in user_text


def test_context_includes_source_files_list():
    builder = ContextBuilder()
    task = _make_task(source_files=["src/a.py", "docs/b.md"])
    messages = builder.build(rules="", task=task)
    user_text = messages[1].content
    assert "## Source Files" in user_text
    assert "src/a.py" in user_text
    assert "docs/b.md" in user_text


def test_context_omits_empty_new_sections():
    builder = ContextBuilder()
    task = _make_task()
    messages = builder.build(rules="", task=task)
    user_text = messages[1].content
    assert "## Motivation" not in user_text
    assert "## Success Criteria" not in user_text
    assert "## Source Files" not in user_text
