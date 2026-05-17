from datetime import datetime
from src.models import (
    Priority,
    TaskStatus,
    SubtaskStatus,
    Subtask,
    ConversationEntry,
    ConversationRole,
    Task,
    LogEntry,
    Who,
    TaskType,
    TaskIntent,
    Project,
    ProjectStatus,
)


def test_priority_ordering():
    """P0 < P1 < P2 (P0 is highest priority, sorts first)."""
    assert Priority.P0.sort_key < Priority.P1.sort_key
    assert Priority.P1.sort_key < Priority.P2.sort_key


def test_task_status_six_columns():
    """TaskStatus enum values match the six directory names."""
    assert TaskStatus.BACKLOG.value == "backlog"
    assert TaskStatus.TODO.value == "todo"
    assert TaskStatus.DOING.value == "doing"
    assert TaskStatus.BLOCKED.value == "blocked"
    assert TaskStatus.REVIEW.value == "review"
    assert TaskStatus.DONE.value == "done"


def test_subtask_status_includes_blocked():
    """SubtaskStatus must support BLOCKED for mid-task subtask blocks."""
    assert SubtaskStatus.TODO.value == "todo"
    assert SubtaskStatus.DOING.value == "doing"
    assert SubtaskStatus.BLOCKED.value == "blocked"
    assert SubtaskStatus.DONE.value == "done"


def test_subtask_with_blocking_reason():
    sub = Subtask(
        id="025-1",
        title="设计风格选型",
        status=SubtaskStatus.BLOCKED,
        blocking_reason="需要用户从方案 A/B/C 中选择",
    )
    assert sub.status == SubtaskStatus.BLOCKED
    assert sub.blocking_reason == "需要用户从方案 A/B/C 中选择"


def test_subtask_blocking_reason_optional():
    sub = Subtask(id="025-2", title="实现首页", status=SubtaskStatus.TODO)
    assert sub.blocking_reason is None


def test_conversation_entry():
    entry = ConversationEntry(
        role=ConversationRole.HUMAN,
        timestamp=datetime(2026, 4, 26, 14, 0),
        content="Do this task.",
    )
    assert entry.role == ConversationRole.HUMAN
    assert "Do this task" in entry.content


def test_task_with_new_fields():
    task = Task(
        id="025",
        title="个人 portfolio 网站",
        project="portfolio-website",
        parent=None,
        priority=Priority.P1,
        tags=["frontend", "design"],
        created=datetime(2026, 4, 26, 14, 0),
        updated=datetime(2026, 4, 26, 14, 0),
        auto_approve=True,
        depends_on=[],
        instructions="请优先使用 Tailwind CSS。",
        subtasks=[],
        description="做一个个人作品集网站。",
        conversation=[],
    )
    assert task.id == "025"
    assert task.project == "portfolio-website"
    assert task.parent is None
    assert task.instructions == "请优先使用 Tailwind CSS。"


def test_task_minimal_defaults():
    """project, parent, instructions all default to safe values."""
    task = Task(
        id="001",
        title="Simple",
        priority=Priority.P1,
        created=datetime(2026, 4, 26),
        updated=datetime(2026, 4, 26),
    )
    assert task.project == ""
    assert task.parent is None
    assert task.instructions == ""
    assert task.auto_approve is True
    assert task.tags == []
    assert task.subtasks == []


def test_log_entry():
    entry = LogEntry(
        task_id="025",
        action="tool_exec",
        detail="ran shell command",
        duration_ms=500,
        status="success",
    )
    assert entry.task_id == "025"
    assert entry.ts is not None


def test_task_defaults_for_new_fields():
    t = Task(
        id="999",
        title="t",
        created=datetime(2026, 4, 27, 9, 0),
        updated=datetime(2026, 4, 27, 9, 0),
    )
    assert t.who == Who.CLAUDE
    assert t.when is None
    assert t.type is None
    assert t.intent is None
    assert t.measure == ""
    assert t.why == ""
    assert t.source_files == []
    assert t.status_reason is None


def test_task_accepts_new_field_values():
    t = Task(
        id="999",
        title="t",
        created=datetime(2026, 4, 27, 9, 0),
        updated=datetime(2026, 4, 27, 9, 0),
        who=Who.HUMAN,
        when="今晚",
        type=TaskType.COMPLEX,
        intent=TaskIntent.RESUME,
        measure="1) tests pass\n2) PR merged",
        why="秋招",
        source_files=["src/a.py", "docs/b.md"],
        status_reason="等用户回应",
    )
    assert t.who == Who.HUMAN
    assert t.when == "今晚"
    assert t.type == TaskType.COMPLEX
    assert t.intent == TaskIntent.RESUME
    assert t.measure == "1) tests pass\n2) PR merged"
    assert t.why == "秋招"
    assert t.source_files == ["src/a.py", "docs/b.md"]
    assert t.status_reason == "等用户回应"


def test_project_status_values():
    assert ProjectStatus.ACTIVE.value == "active"
    assert ProjectStatus.PAUSED.value == "paused"
    assert ProjectStatus.ARCHIVED.value == "archived"


def test_project_minimal():
    p = Project(slug="evernote")
    assert p.slug == "evernote"
    assert p.status == ProjectStatus.ACTIVE
    assert p.priority is None
    assert p.repo_path is None
    assert p.tags == []
    assert p.last_touched is None
    assert p.title == ""
    assert p.body == ""
    assert p.source_path is None


def test_project_full():
    p = Project(
        slug="evernote",
        status=ProjectStatus.PAUSED,
        repo_path="../../evernote",
        priority="P1",
        tags=["migration", "knowledge"],
        last_touched=datetime(2026, 4, 30),
        title="evernote",
        body="## 一句話\n...",
    )
    assert p.status == ProjectStatus.PAUSED
    assert p.priority == "P1"
    assert p.tags == ["migration", "knowledge"]


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
