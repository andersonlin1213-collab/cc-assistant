from datetime import datetime
from pathlib import Path
from src.board.writer import write_task_file, append_conversation
from src.board.parser import parse_task_string, parse_task_file
from src.models import (
    Task,
    Priority,
    Subtask,
    SubtaskStatus,
    ConversationEntry,
    ConversationRole,
    Who,
    TaskType,
    TaskIntent,
)


def _make_task(**overrides) -> Task:
    defaults = dict(
        id="001",
        title="Test task",
        project="",
        parent=None,
        priority=Priority.P1,
        tags=["test"],
        created=datetime(2026, 4, 26, 14, 0),
        updated=datetime(2026, 4, 26, 14, 0),
        auto_approve=True,
        depends_on=[],
        instructions="",
        subtasks=[],
        description="A test task.",
        conversation=[],
    )
    defaults.update(overrides)
    return Task(**defaults)


def test_write_and_roundtrip(tmp_path):
    """Write a task to file, parse it back, fields match."""
    task = _make_task(
        project="test-project",
        instructions="Use TDD.",
        subtasks=[
            Subtask(id="001-1", title="Step one", status=SubtaskStatus.DONE),
            Subtask(
                id="001-2",
                title="Step two",
                status=SubtaskStatus.BLOCKED,
                blocking_reason="Awaiting user input",
            ),
        ],
        conversation=[
            ConversationEntry(
                role=ConversationRole.HUMAN,
                timestamp=datetime(2026, 4, 26, 14, 0),
                content="Do this.",
            ),
        ],
    )
    path = tmp_path / "001-test.md"
    write_task_file(task, path)

    parsed = parse_task_string(path.read_text(encoding="utf-8"))
    assert parsed.id == "001"
    assert parsed.project == "test-project"
    assert parsed.instructions == "Use TDD."
    assert len(parsed.subtasks) == 2
    assert parsed.subtasks[0].status == SubtaskStatus.DONE
    assert parsed.subtasks[1].status == SubtaskStatus.BLOCKED
    assert parsed.subtasks[1].blocking_reason == "Awaiting user input"
    assert parsed.description == "A test task."
    assert len(parsed.conversation) == 1
    assert parsed.conversation[0].content == "Do this."


def test_write_with_parent(tmp_path):
    """parent field round-trips correctly."""
    task = _make_task(id="025-1-1", parent="025-1")
    path = tmp_path / "025-1-1.md"
    write_task_file(task, path)

    parsed = parse_task_string(path.read_text(encoding="utf-8"))
    assert parsed.parent == "025-1"


def test_append_conversation(tmp_path):
    """Append a conversation entry to an existing task file."""
    task = _make_task()
    path = tmp_path / "001-test.md"
    write_task_file(task, path)

    entry = ConversationEntry(
        role=ConversationRole.AI,
        timestamp=datetime(2026, 4, 26, 14, 5),
        content="I will do this now.",
    )
    append_conversation(path, entry)

    parsed = parse_task_string(path.read_text(encoding="utf-8"))
    assert len(parsed.conversation) == 1
    assert parsed.conversation[0].role == ConversationRole.AI
    assert parsed.conversation[0].content == "I will do this now."


def test_write_preserves_chinese(tmp_path):
    """Chinese characters preserved in roundtrip."""
    task = _make_task(title="部署后端", description="把代码部署上去。")
    path = tmp_path / "001-deploy.md"
    write_task_file(task, path)

    content = path.read_text(encoding="utf-8")
    assert "部署后端" in content
    assert "把代码部署上去" in content


def test_write_title_with_colon_roundtrip(tmp_path):
    """Title containing a colon must round-trip without breaking YAML parsing."""
    task = _make_task(title="Feature: implement OAuth")
    path = tmp_path / "001.md"
    write_task_file(task, path)
    parsed = parse_task_string(path.read_text(encoding="utf-8"))
    assert parsed.title == "Feature: implement OAuth"


def test_write_numeric_parent_preserves_id(tmp_path):
    """Numeric-only parent ID must preserve leading zeros across roundtrip."""
    task = _make_task(id="001-1", parent="001")
    path = tmp_path / "001-1.md"
    write_task_file(task, path)
    parsed = parse_task_string(path.read_text(encoding="utf-8"))
    assert parsed.parent == "001"


def test_write_subtask_fields_with_colons(tmp_path):
    """Subtask title and blocking_reason must round-trip even with colons."""
    task = _make_task(
        subtasks=[
            Subtask(
                id="001-1",
                title="Setup: configure DB",
                status=SubtaskStatus.BLOCKED,
                blocking_reason="needs: A or B",
            )
        ],
    )
    path = tmp_path / "001.md"
    write_task_file(task, path)
    parsed = parse_task_string(path.read_text(encoding="utf-8"))
    assert parsed.subtasks[0].title == "Setup: configure DB"
    assert parsed.subtasks[0].blocking_reason == "needs: A or B"


def test_writer_round_trips_new_fields(tmp_path: Path):
    task = Task(
        id="400",
        title="round trip",
        created=datetime(2026, 4, 27, 9, 0),
        updated=datetime(2026, 4, 27, 10, 0),
        who=Who.BOTH,
        when="明天",
        type=TaskType.SIMPLE,
        intent=TaskIntent.APPROVE,
        measure="1) a\n2) b",
        why="动机",
        source_files=["src/x.py", "docs/y.md"],
        status_reason="阻塞原因",
    )
    target = tmp_path / "400-rt.md"
    write_task_file(task, target)

    reloaded = parse_task_file(target)
    assert reloaded.who == Who.BOTH
    assert reloaded.when == "明天"
    assert reloaded.type == TaskType.SIMPLE
    assert reloaded.intent == TaskIntent.APPROVE
    assert reloaded.measure.strip() == "1) a\n2) b"
    assert reloaded.why == "动机"
    assert reloaded.source_files == ["src/x.py", "docs/y.md"]
    assert reloaded.status_reason == "阻塞原因"


def test_writer_emits_fields_in_fixed_order(tmp_path: Path):
    task = Task(
        id="401",
        title="order",
        project="proj",
        parent="400",
        priority=Priority.P0,
        tags=["a"],
        created=datetime(2026, 4, 27, 9, 0),
        updated=datetime(2026, 4, 27, 9, 0),
        auto_approve=False,
        depends_on=["399"],
        instructions="do it",
        who=Who.HUMAN,
        when="今晚",
        type=TaskType.SIMPLE,
        intent=TaskIntent.RESUME,
        measure="ok",
        why="动机",
        source_files=["a.py"],
        status_reason="阻塞中",
        subtasks=[Subtask(id="401-1", title="s", status=SubtaskStatus.TODO)],
    )
    target = tmp_path / "401.md"
    write_task_file(task, target)
    text = target.read_text(encoding="utf-8")

    expected_order = [
        "id:", "title:", "project:", "parent:", "priority:", "tags:",
        "who:", "when:", "type:", "intent:",
        "created:", "updated:", "auto_approve:", "depends_on:",
        "measure:", "why:", "source_files:", "status_reason:",
        "instructions:", "subtasks:",
    ]
    last_index = -1
    for key in expected_order:
        idx = text.find("\n" + key)
        assert idx > last_index, f"key {key!r} out of order in:\n{text}"
        last_index = idx


def test_writer_skips_default_value_fields(tmp_path: Path):
    """A task with only required fields produces minimal frontmatter — no empty/default keys."""
    task = Task(
        id="999",
        title="minimal",
        created=datetime(2026, 4, 27, 9, 0),
        updated=datetime(2026, 4, 27, 9, 0),
    )
    target = tmp_path / "999.md"
    write_task_file(task, target)
    text = target.read_text(encoding="utf-8")

    # Required fields are present
    assert 'id: "999"' in text
    assert "title:" in text
    assert "\ncreated:" in text
    assert "\nupdated:" in text

    # Default-valued fields must be absent so the Properties panel stays clean
    skipped_keys = [
        "project:", "parent:", "priority:", "tags:",
        "who:", "when:", "type:", "intent:",
        "auto_approve:", "depends_on:",
        "measure:", "why:", "source_files:", "status_reason:",
        "instructions:", "subtasks:",
    ]
    for key in skipped_keys:
        assert f"\n{key}" not in text, (
            f"default-valued {key!r} should be skipped from frontmatter; got:\n{text}"
        )


def test_writer_skips_subset_of_defaults(tmp_path: Path):
    """When some fields are set and others default, only set ones appear."""
    task = Task(
        id="998",
        title="partial",
        created=datetime(2026, 4, 27, 9, 0),
        updated=datetime(2026, 4, 27, 9, 0),
        project="cc-assistant",
        intent=TaskIntent.APPROVE,
    )
    target = tmp_path / "998.md"
    write_task_file(task, target)
    text = target.read_text(encoding="utf-8")

    assert "\nproject:" in text
    assert "\nintent: approve" in text
    # These are still defaults — must be absent
    assert "\nparent:" not in text
    assert "\nwhen:" not in text
    assert "\ntype:" not in text
    assert "\ndepends_on:" not in text
    assert "\nsubtasks:" not in text
    assert "\nmeasure:" not in text


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
        "---\nid: \"1\"\ntitle: t\ncreated: 2026-05-02 07:00\nupdated: 2026-05-02 07:00\n---\n## 对话\n### [AI] 2026-05-02 07:32\nreply\n",
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
        "---\nid: \"1\"\ntitle: t\ncreated: 2026-05-02 07:00\nupdated: 2026-05-02 07:00\n---\n## 对话\n### [AI] 2026-05-02 07:32\nreply\n",
        encoding="utf-8",
    )

    append_placeholder(p)
    text_after_first = p.read_text(encoding="utf-8")
    append_placeholder(p)
    text_after_second = p.read_text(encoding="utf-8")

    assert text_after_first == text_after_second
    # Exactly one occurrence of the placeholder body
    assert text_after_second.count(PLACEHOLDER_TEXT) == 1


def test_append_system_entry_roundtrips(tmp_path):
    """`append_system_entry` writes a `### [系统]` block parseable by
    parse_task_file as a SYSTEM ConversationEntry."""
    from src.board.parser import parse_task_file
    from src.board.writer import append_system_entry, write_task_file
    from src.models import ConversationRole, Priority, Task
    from datetime import datetime

    path = tmp_path / "001.md"
    write_task_file(
        Task(
            id="001",
            title="t",
            priority=Priority.P1,
            created=datetime(2026, 5, 6, 10, 0),
            updated=datetime(2026, 5, 6, 10, 0),
        ),
        path,
    )

    append_system_entry(path, "provider 不可用,请检查 .env")

    parsed = parse_task_file(path)
    assert len(parsed.conversation) == 1
    assert parsed.conversation[0].role is ConversationRole.SYSTEM
    assert "provider 不可用" in parsed.conversation[0].content


def test_append_unparseable_file_marker_is_idempotent(tmp_path):
    """Writing the marker twice doesn't stack — second call sees the
    marker comment line and bails early. Otherwise every cycle on a
    persistently-broken file would keep extending it."""
    from src.board.writer import append_unparseable_file_marker

    path = tmp_path / "bad.md"
    path.write_text("一些坏掉的内容。\n", encoding="utf-8")

    append_unparseable_file_marker(path, "missing title field")
    after_first = path.read_text(encoding="utf-8")

    append_unparseable_file_marker(path, "different reason")
    after_second = path.read_text(encoding="utf-8")

    assert after_first == after_second
    assert after_first.count("<!-- cc-assistant: file-malformed-notice -->") == 1
