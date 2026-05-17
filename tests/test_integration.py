"""Integration test:
Human creates task in todo/ → Agent moves to doing/ → AI replies →
auto_approve=false → Agent moves to review/ → Human approves → done/
"""

from datetime import datetime

from src.board.manager import BoardManager
from src.board.parser import parse_task_file
from src.board.writer import write_task_file, append_conversation
from src.logging.structured import StructuredLogger
from src.rules.loader import RulesLoader
from src.models import (
    ConversationEntry,
    ConversationRole,
    LogEntry,
    Priority,
    Subtask,
    SubtaskStatus,
    Task,
    TaskStatus,
)


def test_full_roundtrip(tmp_path):
    # Setup directories
    tasks_dir = tmp_path / "tasks"
    logs_dir = tmp_path / "logs"
    skills_dir = tmp_path / "skills"
    for status in ["backlog", "todo", "doing", "blocked", "review", "done"]:
        (tasks_dir / status).mkdir(parents=True)
    skills_dir.mkdir()
    (skills_dir / "rules.md").write_text("# Rules\nBe careful.", encoding="utf-8")

    manager = BoardManager(tasks_dir)
    logger = StructuredLogger(logs_dir)
    rules = RulesLoader(skills_dir)

    # 1. Rules load
    assert "Be careful" in rules.load()

    # 2. Human creates a task in todo/ (auto_approve=false → will route to review/)
    task = Task(
        id="025",
        title="搭建测试环境",
        project="infra",
        parent=None,
        priority=Priority.P0,
        tags=["infra"],
        created=datetime(2026, 4, 26, 10, 0),
        updated=datetime(2026, 4, 26, 10, 0),
        auto_approve=False,
        instructions="使用 Docker compose。",
        description="搭建一个完整的测试环境。",
        conversation=[
            ConversationEntry(
                role=ConversationRole.HUMAN,
                timestamp=datetime(2026, 4, 26, 10, 0),
                content="优先搞定数据库部分。",
            )
        ],
    )
    todo_path = tasks_dir / "todo" / "025-setup-test-env.md"
    write_task_file(task, todo_path)
    assert todo_path.exists()

    # 3. Agent parses the task
    parsed = parse_task_file(todo_path)
    assert parsed.id == "025"
    assert parsed.priority == Priority.P0
    assert parsed.project == "infra"
    assert parsed.instructions == "使用 Docker compose。"
    assert parsed.auto_approve is False

    # 4. Agent moves task to doing/
    doing_path = manager.move_task(todo_path, TaskStatus.DOING)
    assert not todo_path.exists()
    assert doing_path.exists()
    assert doing_path.parent.name == "doing"

    # 5. Agent appends AI reply
    ai_reply = ConversationEntry(
        role=ConversationRole.AI,
        timestamp=datetime(2026, 4, 26, 10, 1),
        content="收到，先搭建数据库：\n1. 创建 MySQL 实例\n2. 初始化表结构",
    )
    append_conversation(doing_path, ai_reply)

    # 6. Log the action
    logger.log(
        LogEntry(
            task_id="025",
            action="task_started",
            detail="开始搭建测试环境",
            status="success",
        )
    )

    # 7. Re-parse and verify conversation
    reparsed = parse_task_file(doing_path)
    assert len(reparsed.conversation) == 2
    assert reparsed.conversation[1].role == ConversationRole.AI
    assert "MySQL 实例" in reparsed.conversation[1].content

    # 8. Agent finishes work; auto_approve=false → moves to review/
    review_path = manager.move_task(doing_path, TaskStatus.REVIEW)
    assert review_path.parent.name == "review"
    assert review_path.exists()

    # 9. Active tasks list now includes the review item
    active = manager.list_active_tasks()
    assert len(active) == 1
    assert active[0] == review_path

    # 10. Human approves → moves to done/YYYY-MM/
    done_path = manager.move_task(review_path, TaskStatus.DONE)
    assert done_path.exists()
    today = datetime.now()
    assert done_path.parent.name == today.strftime("%Y-%m")

    # 11. Verify logs
    logs = logger.get_task_logs("025")
    assert len(logs) == 1
    assert logs[0]["action"] == "task_started"

    # 12. Verify active tasks list is empty after archival
    active = manager.list_active_tasks()
    assert len(active) == 0
