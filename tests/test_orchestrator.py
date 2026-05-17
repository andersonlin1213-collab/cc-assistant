"""Orchestrator unit tests with a mocked LLM client and real Layer 1+3b modules."""

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.llm.types import (
    LLMResponse,
    Message,
    TextBlock,
    ToolUseBlock,
    Usage,
)
from src.agent.orchestrator import Orchestrator
from src.board.writer import write_task_file
from src.models import ConversationRole, Priority, Task, TaskIntent, TaskStatus, Who
from src.tools.file_ops import FileOpsTool


def _kanban(tmp_path: Path) -> Path:
    tasks = tmp_path / "tasks"
    for s in ["backlog", "todo", "doing", "blocked", "review", "done"]:
        (tasks / s).mkdir(parents=True)
    return tasks


def _make_task(**overrides) -> Task:
    defaults = dict(
        id="100",
        title="Test",
        project="",
        parent=None,
        priority=Priority.P1,
        tags=[],
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


def _llm_with_responses(*responses: LLMResponse):
    """Build a mocked LLMClient.chat that returns the given responses in order."""
    mock = MagicMock()
    mock.chat = AsyncMock(side_effect=list(responses))
    return mock


def _final_text(text: str = "All done.") -> LLMResponse:
    return LLMResponse(
        content=[TextBlock(text=text)],
        stop_reason="end_turn",
        usage=Usage(),
        model="claude-sonnet-4-6",
    )


def _tool_use(name: str, input_: dict, id_: str = "tu1", text: str = "") -> LLMResponse:
    content = [TextBlock(text=text)] if text else []
    content.append(ToolUseBlock(id=id_, name=name, input=input_))
    return LLMResponse(
        content=content,
        stop_reason="tool_use",
        usage=Usage(),
        model="claude-sonnet-4-6",
    )


@contextmanager
def _noop_suppress():
    yield


def orch_dir(tmp_path: Path) -> Path:
    return _kanban(tmp_path)


def _make_orchestrator_for(tmp_path: Path, llm) -> Orchestrator:
    """Variant of _make_orchestrator that does NOT reuse already-created dirs."""
    skills = tmp_path / "skills"
    if not skills.exists():
        skills.mkdir()
        (skills / "rules.md").write_text("# Rules\n", encoding="utf-8")
    logs = tmp_path / "logs"
    if not logs.exists():
        logs.mkdir()

    return Orchestrator(
        tasks_dir=tmp_path / "tasks",
        skills_dir=skills,
        logs_dir=logs,
        llm=llm,
        tools=[FileOpsTool()],
        suppress_self=_noop_suppress,
    )


# ------------------------------------------------------------------ #
# Test cases                                                         #
# ------------------------------------------------------------------ #


async def test_run_cycle_skips_when_path_missing(tmp_path):
    """A path that doesn't exist (e.g., already moved) is a no-op."""
    _kanban(tmp_path)
    llm = _llm_with_responses(_final_text())
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(tmp_path / "tasks" / "todo" / "ghost.md")

    llm.chat.assert_not_called()


async def test_simple_text_cycle_appends_ai_reply(tmp_path):
    """A single end_turn response appends one AI conversation entry."""
    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-test.md"
    write_task_file(_make_task(id="100"), todo_path)

    llm = _llm_with_responses(_final_text("Acknowledged."))
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(todo_path)

    # File auto-advances todo -> doing on first cycle
    moved = (tasks_dir / "doing" / "100-test.md")
    assert moved.exists()
    from src.board.parser import PLACEHOLDER_TEXT, parse_task_file
    parsed = parse_task_file(moved)
    # AI reply + scaffolded placeholder for next [我] turn
    assert len(parsed.conversation) == 2
    assert parsed.conversation[0].content == "Acknowledged."
    assert parsed.conversation[0].role is ConversationRole.AI
    assert parsed.conversation[1].content == PLACEHOLDER_TEXT
    assert parsed.conversation[1].role is ConversationRole.HUMAN


async def test_tool_use_loop(tmp_path):
    """When the LLM calls a tool, the result is fed back and the cycle continues."""
    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-tool.md"
    write_task_file(_make_task(id="100"), todo_path)

    target = tmp_path / "scratch.txt"

    llm = _llm_with_responses(
        _tool_use(
            "file_ops",
            {"operation": "write", "path": str(target), "content": "hello"},
            text="I will write a file.",
        ),
        _final_text("Wrote the file."),
    )
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(todo_path)

    assert target.exists()
    assert target.read_text(encoding="utf-8") == "hello"
    assert llm.chat.call_count == 2


async def test_mark_complete_moves_to_done_when_auto_approve(tmp_path):
    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-mc.md"
    write_task_file(_make_task(id="100", auto_approve=True), todo_path)

    llm = _llm_with_responses(
        _tool_use("mark_complete", {"reason": "all done"}, text="Task complete."),
        _final_text("OK."),
    )
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(todo_path)

    # done/ uses monthly subdirs
    today = datetime.now().strftime("%Y-%m")
    done_path = tasks_dir / "done" / today / "100-mc.md"
    assert done_path.exists()
    assert not todo_path.exists()


async def test_mark_complete_moves_to_review_when_not_auto_approve(tmp_path):
    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-rev.md"
    write_task_file(_make_task(id="100", auto_approve=False), todo_path)

    llm = _llm_with_responses(
        _tool_use("mark_complete", {"reason": "needs review"}),
        _final_text("Submitted for review."),
    )
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(todo_path)

    review_path = tasks_dir / "review" / "100-rev.md"
    assert review_path.exists()
    assert not todo_path.exists()


async def test_mark_blocked_moves_to_blocked(tmp_path):
    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-block.md"
    write_task_file(_make_task(id="100"), todo_path)

    llm = _llm_with_responses(
        _tool_use("mark_blocked", {"reason": "need credentials"}),
        _final_text("Blocked."),
    )
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(todo_path)

    blocked_path = tasks_dir / "blocked" / "100-block.md"
    assert blocked_path.exists()


async def test_already_in_doing_stays_in_doing_when_no_marks(tmp_path):
    """A task already in doing/ that finishes a cycle without control tools stays put."""
    tasks_dir = orch_dir(tmp_path)
    doing_path = tasks_dir / "doing" / "100-stay.md"
    write_task_file(_make_task(id="100"), doing_path)

    llm = _llm_with_responses(_final_text("Still working."))
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(doing_path)

    assert doing_path.exists()  # still in doing/


async def test_terminal_states_are_skipped(tmp_path):
    """A task in done/ or review/ does NOT trigger an LLM call."""
    tasks_dir = orch_dir(tmp_path)
    review_path = tasks_dir / "review" / "100-rev.md"
    write_task_file(_make_task(id="100"), review_path)

    llm = _llm_with_responses(_final_text("Should not be called."))
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(review_path)

    llm.chat.assert_not_called()
    assert review_path.exists()


async def test_max_rounds_protects_against_infinite_loop(tmp_path):
    """If the LLM keeps calling tools forever, the cycle bails after MAX_TOOL_USE_ROUNDS."""
    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-loop.md"
    write_task_file(_make_task(id="100"), todo_path)

    target = tmp_path / "x.txt"

    # Always return tool_use, never end_turn — should be capped
    looping_response = _tool_use(
        "file_ops",
        {"operation": "write", "path": str(target), "content": "loop"},
    )
    # Provide enough responses to exceed the cap; the orchestrator should stop
    # before exhausting them.
    llm = MagicMock()
    llm.chat = AsyncMock(return_value=looping_response)
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(todo_path)

    # Should not exceed the documented cap (Orchestrator.MAX_TOOL_USE_ROUNDS)
    assert llm.chat.call_count <= Orchestrator.MAX_TOOL_USE_ROUNDS


async def test_llm_failure_does_not_advance_status(tmp_path):
    """If the LLM call raises, the task stays in its current column (no auto-advance)."""
    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-fail.md"
    write_task_file(_make_task(id="100"), todo_path)

    llm = MagicMock()
    llm.chat = AsyncMock(side_effect=RuntimeError("network down"))
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(todo_path)

    # Task stays in todo/ — error did NOT advance it to doing/
    assert todo_path.exists()
    assert not (tasks_dir / "doing" / "100-fail.md").exists()

    # Error message was appended to the conversation
    from src.board.parser import PLACEHOLDER_TEXT, parse_task_file
    parsed = parse_task_file(todo_path)
    # Error reply + scaffolded placeholder for next [我] turn
    assert len(parsed.conversation) == 2
    assert "Error" in parsed.conversation[0].content
    assert "network down" in parsed.conversation[0].content
    assert parsed.conversation[0].role is ConversationRole.AI
    assert parsed.conversation[1].content == PLACEHOLDER_TEXT
    assert parsed.conversation[1].role is ConversationRole.HUMAN


async def test_run_cycle_skips_when_path_already_in_flight(tmp_path):
    """If the same path is already being processed, a second concurrent call returns immediately."""
    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-inflight.md"
    write_task_file(_make_task(id="100"), todo_path)

    llm = _llm_with_responses(_final_text("ack"))
    orch = _make_orchestrator_for(tmp_path, llm)

    # Pre-populate the in-flight set as if another thread were already processing.
    orch._in_flight.add(str(todo_path))

    await orch.run_cycle(todo_path)

    # LLM should NOT have been called — the second concurrent call returns early.
    llm.chat.assert_not_called()


def test_run_cycle_concurrent_threads_only_one_runs_llm(tmp_path):
    """Two real OS threads racing on the same task path: only one fires the
    LLM. Locks the in_flight contract under actual contention — catches
    regressions that the synthetic pre-population test above would not
    (e.g. removing the threading.Lock acquisition entirely).

    Plan 5a deferred review minor item."""
    import asyncio
    import threading
    import time

    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-race.md"
    write_task_file(_make_task(id="100"), todo_path)

    llm_call_count = 0
    count_lock = threading.Lock()

    async def slow_chat(*_args, **_kwargs):
        nonlocal llm_call_count
        with count_lock:
            llm_call_count += 1
        # Hold the cycle long enough that the second thread reliably races
        # the in_flight check while the first is still mid-cycle.
        await asyncio.sleep(0.3)
        return _final_text("ok")

    llm = MagicMock()
    llm.chat = AsyncMock(side_effect=slow_chat)
    orch = _make_orchestrator_for(tmp_path, llm)

    def runner():
        asyncio.run(orch.run_cycle(todo_path))

    t1 = threading.Thread(target=runner)
    t2 = threading.Thread(target=runner)
    t1.start()
    # Small lead so t1 reliably acquires the in_flight slot first.
    time.sleep(0.05)
    t2.start()

    # t2 should observe the in_flight set and return immediately, well before
    # t1 finishes its 300 ms LLM call.
    t2.join(timeout=1.0)
    assert not t2.is_alive(), "t2 should exit fast when in_flight is set"

    t1.join(timeout=2.0)
    assert not t1.is_alive(), "t1 should finish its single cycle"

    assert llm_call_count == 1, (
        f"only one thread should reach the LLM, got {llm_call_count}"
    )
    assert str(todo_path) not in orch._in_flight, (
        "in_flight slot must be released after the cycle completes"
    )


async def test_run_cycle_releases_in_flight_on_normal_exit(tmp_path):
    """After a successful cycle, the path is removed from in_flight so the next run can proceed."""
    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-release.md"
    write_task_file(_make_task(id="100"), todo_path)

    llm = _llm_with_responses(_final_text("done"))
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(todo_path)

    assert str(todo_path) not in orch._in_flight


async def test_run_cycle_releases_in_flight_on_exception(tmp_path):
    """Even if the LLM raises, the in-flight entry is removed."""
    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-err.md"
    write_task_file(_make_task(id="100"), todo_path)

    llm = MagicMock()
    llm.chat = AsyncMock(side_effect=RuntimeError("boom"))
    orch = _make_orchestrator_for(tmp_path, llm)

    # The Orchestrator catches LLM exceptions internally; cycle should not raise.
    await orch.run_cycle(todo_path)

    assert str(todo_path) not in orch._in_flight


async def test_run_cycle_dry_run_does_not_mutate_state(tmp_path):
    """dry_run=True: tools get dry_run flag, no file move, no commit, no AI reply append."""
    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-dry.md"
    write_task_file(_make_task(id="100"), todo_path)

    scratch = tmp_path / "scratch.txt"

    llm = _llm_with_responses(
        _tool_use(
            "file_ops",
            {"operation": "write", "path": str(scratch), "content": "should-not-write"},
        ),
        _final_text("planned"),
    )

    skills = tmp_path / "skills"
    if not skills.exists():
        skills.mkdir()
        (skills / "rules.md").write_text("# Rules\n", encoding="utf-8")
    logs = tmp_path / "logs"
    if not logs.exists():
        logs.mkdir()

    orch = Orchestrator(
        tasks_dir=tmp_path / "tasks",
        skills_dir=skills,
        logs_dir=logs,
        llm=llm,
        tools=[FileOpsTool()],
        suppress_self=_noop_suppress,
    )

    await orch.run_cycle(todo_path, dry_run=True)

    # 1. File NOT moved out of todo/
    assert todo_path.exists()
    assert not (tasks_dir / "doing" / "100-dry.md").exists()

    # 2. Tool's dry_run prevented the actual write
    assert not scratch.exists()

    # 3. No AI reply appended (conversation is unchanged)
    from src.board.parser import parse_task_file
    parsed = parse_task_file(todo_path)
    assert len(parsed.conversation) == 0


# ------------------------------------------------------------------ #
# Plan 5b: who-filter and intent mechanical path                     #
# ------------------------------------------------------------------ #


def _seed_task(tasks_dir, column, task_id="500", **overrides):
    """Write a Task into the given column folder; returns the path."""
    base = dict(
        id=task_id,
        title=f"task-{task_id}",
        created=datetime(2026, 4, 27, 9, 0),
        updated=datetime(2026, 4, 27, 9, 0),
    )
    base.update(overrides)
    task = Task(**base)
    path = tasks_dir / column / f"{task_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_task_file(task, path)
    return path


@pytest.mark.asyncio
async def test_orchestrator_skips_when_who_is_human(tmp_path):
    _kanban(tmp_path)
    llm = _llm_with_responses(_final_text())
    orch = _make_orchestrator_for(tmp_path, llm)
    path = _seed_task(tmp_path / "tasks", "todo", who=Who.HUMAN)

    await orch.run_cycle(path)

    # Task remains in todo (no LLM, no move)
    assert path.exists()
    llm.chat.assert_not_called()


@pytest.mark.asyncio
async def test_orchestrator_resumes_blocked_to_doing_via_intent(tmp_path):
    _kanban(tmp_path)
    llm = _llm_with_responses(_final_text())
    orch = _make_orchestrator_for(tmp_path, llm)
    path = _seed_task(tmp_path / "tasks", "blocked", intent=TaskIntent.RESUME)

    await orch.run_cycle(path)

    assert not path.exists()
    moved = tmp_path / "tasks" / "doing" / "500.md"
    assert moved.exists()
    # intent should be cleared after the move
    from src.board.parser import parse_task_file
    reloaded = parse_task_file(moved)
    assert reloaded.intent is None


@pytest.mark.asyncio
async def test_orchestrator_clears_invalid_intent_combo(tmp_path):
    _kanban(tmp_path)
    llm = _llm_with_responses(_final_text())
    orch = _make_orchestrator_for(tmp_path, llm)
    # resume from todo is invalid
    path = _seed_task(tmp_path / "tasks", "todo", intent=TaskIntent.RESUME, who=Who.HUMAN)

    await orch.run_cycle(path)

    # File stays put
    assert path.exists()
    # intent is cleared
    from src.board.parser import parse_task_file
    reloaded = parse_task_file(path)
    assert reloaded.intent is None


@pytest.mark.asyncio
async def test_orchestrator_dry_run_does_not_apply_intent(tmp_path):
    """`dry_run=True` must not mutate even on the intent mechanical path —
    the file stays put and `intent` remains set so a subsequent real run
    still has the user's signal to act on."""
    _kanban(tmp_path)
    llm = _llm_with_responses(_final_text())
    orch = _make_orchestrator_for(tmp_path, llm)
    path = _seed_task(
        tmp_path / "tasks", "blocked", task_id="900", intent=TaskIntent.RESUME
    )

    await orch.run_cycle(path, dry_run=True)

    assert path.exists()
    moved = tmp_path / "tasks" / "doing" / "900.md"
    assert not moved.exists()
    from src.board.parser import parse_task_file
    reloaded = parse_task_file(path)
    assert reloaded.intent == TaskIntent.RESUME


@pytest.mark.asyncio
async def test_orchestrator_preloads_source_files_into_context(tmp_path):
    """When task.source_files is set, the LLM message list includes their contents."""
    _kanban(tmp_path)
    src_a = tmp_path / "a.txt"
    src_a.write_text("HELLO_A_CONTENT", encoding="utf-8")
    path = _seed_task(
        tmp_path / "tasks",
        "doing",
        task_id="700",
        source_files=[str(src_a.resolve())],
    )

    llm = _llm_with_responses(_final_text())
    orch = _make_orchestrator_for(tmp_path, llm)
    await orch.run_cycle(path)

    llm.chat.assert_awaited()
    sent_messages = llm.chat.await_args_list[0].args[0]
    combined = "\n".join(
        m.content for m in sent_messages if isinstance(m.content, str)
    )
    assert "HELLO_A_CONTENT" in combined


@pytest.mark.asyncio
async def test_orchestrator_omits_source_file_block_when_none(tmp_path):
    """No `## Pre-read source files` block when task.source_files is empty."""
    _kanban(tmp_path)
    path = _seed_task(tmp_path / "tasks", "doing", task_id="701")

    llm = _llm_with_responses(_final_text())
    orch = _make_orchestrator_for(tmp_path, llm)
    await orch.run_cycle(path)

    sent_messages = llm.chat.await_args_list[0].args[0]
    combined = "\n".join(
        m.content for m in sent_messages if isinstance(m.content, str)
    )
    assert "## Pre-read source files" not in combined


# ------------------------------------------------------------------ #
# Plan 5b hardening: replay_pending_intents — startup catch-up       #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_replay_pending_intents_processes_stuck_blocked_task(tmp_path):
    """A blocked task with intent=resume left over from a daemon outage is
    moved on the next start, with no LLM call."""
    _kanban(tmp_path)
    llm = _llm_with_responses(_final_text())
    orch = _make_orchestrator_for(tmp_path, llm)
    path = _seed_task(
        tmp_path / "tasks", "blocked", task_id="601", intent=TaskIntent.RESUME
    )

    processed = await orch.replay_pending_intents()

    assert processed == 1
    assert not path.exists()
    moved = tmp_path / "tasks" / "doing" / "601.md"
    assert moved.exists()
    from src.board.parser import parse_task_file
    assert parse_task_file(moved).intent is None
    llm.chat.assert_not_called()


@pytest.mark.asyncio
async def test_replay_pending_intents_skips_tasks_without_intent(tmp_path):
    """Tasks with intent=None are left untouched — no spurious LLM cycles."""
    _kanban(tmp_path)
    llm = _llm_with_responses(_final_text())
    orch = _make_orchestrator_for(tmp_path, llm)
    path = _seed_task(tmp_path / "tasks", "blocked", task_id="602")

    processed = await orch.replay_pending_intents()

    assert processed == 0
    assert path.exists()
    llm.chat.assert_not_called()


@pytest.mark.asyncio
async def test_replay_does_not_log_summary_when_nothing_processed(tmp_path):
    """Quiet poll (processed=0) emits no `replay_pending_intents` log line.

    Polling fires every 30 minutes; without this guard, every quiet cycle
    would write a summary entry, churning logs/agent.jsonl forever.
    """
    _kanban(tmp_path)
    llm = _llm_with_responses(_final_text())
    orch = _make_orchestrator_for(tmp_path, llm)

    # Empty vault, nothing to do
    processed = await orch.replay_pending_intents()
    assert processed == 0

    log_path = tmp_path / "logs" / "agent.jsonl"
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            assert "replay_pending_intents" not in line, (
                f"quiet replay should not emit summary log; got: {line}"
            )


@pytest.mark.asyncio
async def test_replay_pending_intents_scans_review_column(tmp_path):
    """Replay also covers review/ (not just blocked/) — approve intents catch up too."""
    _kanban(tmp_path)
    llm = _llm_with_responses(_final_text())
    orch = _make_orchestrator_for(tmp_path, llm)
    path = _seed_task(
        tmp_path / "tasks", "review", task_id="603", intent=TaskIntent.APPROVE
    )

    processed = await orch.replay_pending_intents()

    assert processed == 1
    assert not path.exists()
    # Done tasks are archived to a monthly subdir (manager.move_task)
    done_files = list((tmp_path / "tasks" / "done").rglob("603.md"))
    assert len(done_files) == 1
    from src.board.parser import parse_task_file
    assert parse_task_file(done_files[0]).intent is None


@pytest.mark.asyncio
async def test_run_cycle_skips_malformed_draft_file_without_crashing(tmp_path):
    """A draft file (e.g. created on mobile in Obsidian without filling out the
    template) must not crash the daemon. The orchestrator logs a structured
    `task_malformed` system entry and returns; the LLM is never invoked."""
    tasks_dir = _kanban(tmp_path)
    draft = tasks_dir / "review" / "Metabade.md"
    draft.write_text(
        "---\n"
        "priority: P1\n"
        "who: claude\n"
        "project: cc-assistant-2\n"
        "intent: null\n"
        "---\n\n"
        "调研 metabase 的笔记\n",
        encoding="utf-8",
    )

    llm = _llm_with_responses(_final_text())
    orch = _make_orchestrator_for(tmp_path, llm)

    # Must not raise.
    await orch.run_cycle(draft)

    # File is left in place untouched.
    assert draft.exists()
    # LLM was never called.
    llm.chat.assert_not_called()

    # Structured log entry was written to the system log.
    import json
    agent_log = tmp_path / "logs" / "agent.jsonl"
    assert agent_log.exists(), "expected a system log entry for the malformed file"
    entries = [json.loads(line) for line in agent_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(e.get("action") == "task_malformed" for e in entries), (
        f"expected a task_malformed entry, got actions: {[e.get('action') for e in entries]}"
    )


@pytest.mark.asyncio
async def test_multi_round_placeholder_fill_cycle_chain(tmp_path):
    """End-to-end multi-round chain: this is the integration test the
    project card flagged as missing. Each cycle must (a) append an AI
    reply, (b) scaffold a fresh `[我]` placeholder, AND on the NEXT
    cycle (c) detect the user's overwrite of the placeholder and feed
    it to the LLM as the latest user turn.

    Three rounds catches the realistic regression: a parser/orchestrator
    bug where the second round's user input becomes invisible (e.g. parser
    truncates at H2, placeholder dedup mis-fires, suppress_self window
    leaks the daemon's own placeholder write back as a user turn). Single-
    cycle tests can't catch any of these — only the chain does."""
    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-chain.md"
    write_task_file(_make_task(id="100"), todo_path)

    llm = _llm_with_responses(
        _final_text("AI round 1 reply."),
        _final_text("AI round 2 reply."),
        _final_text("AI round 3 reply."),
    )
    orch = _make_orchestrator_for(tmp_path, llm)

    from src.board.parser import PLACEHOLDER_TEXT, parse_task_file
    from src.board.writer import append_conversation
    from src.models import ConversationEntry, ConversationRole as _CR

    # ---------- Round 1: todo -> doing, AI reply 1 + placeholder ----------
    await orch.run_cycle(todo_path)
    doing_path = tasks_dir / "doing" / "100-chain.md"
    assert doing_path.exists(), "task should auto-advance todo -> doing"
    parsed = parse_task_file(doing_path)
    assert len(parsed.conversation) == 2
    assert parsed.conversation[0].content == "AI round 1 reply."
    assert parsed.conversation[0].role is _CR.AI
    assert parsed.conversation[1].content == PLACEHOLDER_TEXT
    assert parsed.conversation[1].role is _CR.HUMAN

    # ---------- Simulate user editing the placeholder line ---------------
    # We can't just append — the placeholder IS the last entry. Rewrite
    # the file by overwriting the placeholder entry with real content.
    # In production this is the user typing into Obsidian and saving.
    text = doing_path.read_text(encoding="utf-8")
    text_filled_1 = text.replace(PLACEHOLDER_TEXT, "User round 1 reply.")
    assert PLACEHOLDER_TEXT not in text_filled_1, (
        "test fixture broken: placeholder substitution didn't take effect"
    )
    doing_path.write_text(text_filled_1, encoding="utf-8")

    # ---------- Round 2: AI reply 2 + new placeholder --------------------
    await orch.run_cycle(doing_path)
    parsed = parse_task_file(doing_path)
    # 1 AI + 1 user (filled) + 1 AI + 1 placeholder = 4 entries
    assert len(parsed.conversation) == 4, (
        f"expected 4 conversation entries after round 2, got "
        f"{len(parsed.conversation)}: "
        f"{[(e.role.value, e.content[:40]) for e in parsed.conversation]}"
    )
    assert parsed.conversation[1].content == "User round 1 reply."
    assert parsed.conversation[1].role is _CR.HUMAN
    assert parsed.conversation[2].content == "AI round 2 reply."
    assert parsed.conversation[2].role is _CR.AI
    assert parsed.conversation[3].content == PLACEHOLDER_TEXT

    # The LLM call for round 2 must have seen the user's round-1 reply as
    # the latest [我] turn. Inspect the messages passed to chat() — the
    # last user turn should contain "User round 1 reply.".
    second_call_args = llm.chat.call_args_list[1]
    messages = second_call_args.args[0] if second_call_args.args else second_call_args.kwargs["messages"]
    user_msgs = [m for m in messages if m.role == "user"]
    last_user_text = user_msgs[-1].content if isinstance(user_msgs[-1].content, str) else str(user_msgs[-1].content)
    assert "User round 1 reply." in last_user_text, (
        f"round-2 LLM call missed user's round-1 input. Last user msg: "
        f"{last_user_text[:200]}"
    )

    # ---------- Round 3: confirm chain holds across 3 rounds -------------
    text = doing_path.read_text(encoding="utf-8")
    text_filled_2 = text.replace(PLACEHOLDER_TEXT, "User round 2 reply.")
    doing_path.write_text(text_filled_2, encoding="utf-8")

    await orch.run_cycle(doing_path)
    parsed = parse_task_file(doing_path)
    # 1 AI + 1 user + 1 AI + 1 user + 1 AI + 1 placeholder = 6 entries
    assert len(parsed.conversation) == 6, (
        f"expected 6 conversation entries after round 3, got "
        f"{len(parsed.conversation)}"
    )
    assert parsed.conversation[3].content == "User round 2 reply."
    assert parsed.conversation[4].content == "AI round 3 reply."
    assert parsed.conversation[5].content == PLACEHOLDER_TEXT

    # Sanity: all three LLM calls actually fired.
    assert llm.chat.call_count == 3


@pytest.mark.asyncio
async def test_parser_warning_deduped_across_cycles(tmp_path):
    """A doing/ file with a lenient header gets re-parsed every cycle (mtime
    tick, scheduler poll, watcher). Without dedup the same warning lands
    in the log on every cycle and drowns out new anomalies. Cache the
    last-emitted set per path; only emit warnings not seen before."""
    tasks_dir = _kanban(tmp_path)
    task_file = tasks_dir / "doing" / "lenient.md"
    body = (
        "---\n"
        'id: "210"\n'
        "title: lenient\n"
        "created: 2026-05-05 10:00\n"
        "updated: 2026-05-05 10:00\n"
        "---\n\n"
        "## 任务描述\n"
        "正文。\n\n"
        "## 对话\n"
        "### [我] 2026-05-05T10:30:00\n"
        "ISO 带 T。\n\n"
        "### [AI] 2026-05-05 10:31\n"
        "回复。\n\n"
        "### [我] 2026-05-05 10:32\n"
        "*(在这里写下一条，保存即触发)*\n"
    )
    task_file.write_text(body, encoding="utf-8")

    llm = _llm_with_responses(_final_text(), _final_text())
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(task_file)
    await orch.run_cycle(task_file)

    import json
    task_log = tmp_path / "logs" / "210.jsonl"
    entries = [
        json.loads(line)
        for line in task_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    warnings = [e for e in entries if e.get("action") == "parser_warning"]
    assert len(warnings) == 1, (
        f"expected exactly one parser_warning across two cycles, got {len(warnings)}: "
        f"{[w.get('detail') for w in warnings]}"
    )


@pytest.mark.asyncio
async def test_parser_warning_emitted_again_when_new_anomaly_appears(tmp_path):
    """Dedup must not mask new anomalies: when the user's edit introduces a
    second lenient header, the new warning surfaces even though the first
    one is already in the cache. Otherwise newly-introduced silent-fail
    edge cases would stay invisible after the first cycle."""
    tasks_dir = _kanban(tmp_path)
    task_file = tasks_dir / "doing" / "lenient.md"
    body_v1 = (
        "---\n"
        'id: "211"\n'
        "title: lenient\n"
        "created: 2026-05-05 10:00\n"
        "updated: 2026-05-05 10:00\n"
        "---\n\n"
        "## 任务描述\n"
        "正文。\n\n"
        "## 对话\n"
        "### [我] 2026-05-05T10:30:00\n"
        "第一条 ISO 带 T。\n\n"
        "### [AI] 2026-05-05 10:31\n"
        "回复。\n\n"
        "### [我] 2026-05-05 10:32\n"
        "*(在这里写下一条，保存即触发)*\n"
    )
    task_file.write_text(body_v1, encoding="utf-8")

    llm = _llm_with_responses(_final_text(), _final_text())
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(task_file)

    # User's edit adds a SECOND lenient header (different first line, so
    # different warning string). This cycle must emit a fresh warning.
    body_v2 = body_v1 + (
        "\n### [AI] 2026-05-05T10:33:00\n"
        "第二条 ISO 带 T。\n"
    )
    task_file.write_text(body_v2, encoding="utf-8")

    await orch.run_cycle(task_file)

    import json
    task_log = tmp_path / "logs" / "211.jsonl"
    entries = [
        json.loads(line)
        for line in task_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    warnings = [e for e in entries if e.get("action") == "parser_warning"]
    # Two distinct lenient warnings (one per offending header line).
    assert len(warnings) == 2, (
        f"expected 2 parser_warning entries (one per distinct header), got "
        f"{len(warnings)}: {[w.get('detail') for w in warnings]}"
    )


@pytest.mark.asyncio
async def test_run_cycle_emits_parser_warning_for_lenient_header(tmp_path):
    """Forgive-then-warn: when the parser falls back to a lenient interpretation
    (e.g. ISO `T` separator in a conversation header), the orchestrator must
    surface a `parser_warning` log entry. Without this, the previous regime
    silently dropped the entry and we'd debug the resulting `is_pending_*`
    misbehavior by deduction. This test exists so the observability channel
    can never regress to silent."""
    tasks_dir = _kanban(tmp_path)
    task_file = tasks_dir / "doing" / "lenient.md"
    task_file.write_text(
        "---\n"
        'id: "200"\n'
        "title: lenient\n"
        "created: 2026-05-05 10:00\n"
        "updated: 2026-05-05 10:00\n"
        "---\n\n"
        "## 任务描述\n"
        "正文。\n\n"
        "## 对话\n"
        "### [我] 2026-05-05T10:30:00\n"
        "ISO 带 T 的时间戳。\n\n"
        "### [AI] 2026-05-05 10:31\n"
        "回复。\n\n"
        "### [我] 2026-05-05 10:32\n"
        "*(在这里写下一条，保存即触发)*\n",
        encoding="utf-8",
    )

    llm = _llm_with_responses(_final_text())
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(task_file)

    import json
    task_log = tmp_path / "logs" / "200.jsonl"
    assert task_log.exists()
    entries = [
        json.loads(line)
        for line in task_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    warnings = [e for e in entries if e.get("action") == "parser_warning"]
    assert warnings, (
        f"expected a parser_warning entry, got actions: "
        f"{[e.get('action') for e in entries]}"
    )
    assert any("conversation_header_lenient" in e.get("detail", "") for e in warnings)


@pytest.mark.asyncio
async def test_run_cycle_logs_provider_unavailable_and_skips(tmp_path):
    """When the LLMRouter can't satisfy a task's provider request (e.g. user
    set `provider: claude` in frontmatter but ANTHROPIC_API_KEY isn't in
    .env), the cycle must log a structured `provider_unavailable` entry,
    surface a `[系统]` notice in the conversation so the user sees it in
    Obsidian (not just in logs), and scaffold a placeholder so the next
    save with the fix actually triggers a cycle. Silent fallback to
    claude_cli would run a mysql/dingtalk task on a provider that can't
    reach those tools — it's intentional that we DON'T fall back."""
    tasks_dir = _kanban(tmp_path)
    task_file = tasks_dir / "doing" / "needs-api.md"
    task_file.write_text(
        "---\n"
        'id: "300"\n'
        "title: needs-api\n"
        "provider: claude\n"
        "created: 2026-05-05 10:00\n"
        "updated: 2026-05-05 10:00\n"
        "---\n\n"
        "## 任务描述\n"
        "需要 mysql 工具,但 API key 没配。\n",
        encoding="utf-8",
    )

    # Build a router with NO api_client so `provider: claude` can't resolve.
    from src.agent.llm.router import LLMRouter
    cli_stub = MagicMock()
    cli_stub.chat = AsyncMock()
    router = LLMRouter(api_client=None, cli_client=cli_stub, default_provider="claude_cli")

    # Reuse the orchestrator builder; pass the router via the `llm` slot —
    # Orchestrator detects LLMRouter and uses it directly.
    orch = _make_orchestrator_for(tmp_path, router)

    await orch.run_cycle(task_file)

    # CLI was never called — router refused before reaching it.
    cli_stub.chat.assert_not_called()
    # No [AI] reply (LLM never ran), but a [系统] notice + placeholder
    # were written so the user sees the failure in Obsidian.
    content = task_file.read_text(encoding="utf-8")
    assert "[AI]" not in content
    assert "### [系统]" in content, (
        f"expected [系统] notice in file, got:\n{content}"
    )
    assert "provider 不可用" in content
    assert "*(在这里写下一条" in content, "expected placeholder scaffolded"

    import json
    task_log = tmp_path / "logs" / "300.jsonl"
    assert task_log.exists()
    entries = [
        json.loads(line)
        for line in task_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(e.get("action") == "provider_unavailable" for e in entries), (
        f"expected provider_unavailable log, got: "
        f"{[e.get('action') for e in entries]}"
    )


@pytest.mark.asyncio
async def test_provider_unavailable_does_not_loop_on_repeated_save(tmp_path):
    """After provider_unavailable writes a [系统] entry + placeholder, the
    NEXT mtime tick (no user input) must hit `is_pending_placeholder_turn`
    and short-circuit BEFORE reaching the failing provider check again.
    Otherwise we'd append a fresh [系统] entry on every save and pollute
    the conversation."""
    tasks_dir = _kanban(tmp_path)
    task_file = tasks_dir / "doing" / "loop-guard.md"
    task_file.write_text(
        "---\n"
        'id: "320"\n'
        "title: loop-guard\n"
        "provider: claude\n"
        "created: 2026-05-06 10:00\n"
        "updated: 2026-05-06 10:00\n"
        "---\n\n"
        "## 任务描述\n用户已经写了真内容。\n",
        encoding="utf-8",
    )

    from src.agent.llm.router import LLMRouter
    cli_stub = MagicMock()
    cli_stub.chat = AsyncMock()
    router = LLMRouter(api_client=None, cli_client=cli_stub, default_provider="claude_cli")
    orch = _make_orchestrator_for(tmp_path, router)

    await orch.run_cycle(task_file)
    after_first = task_file.read_text(encoding="utf-8")
    first_system_count = after_first.count("### [系统]")
    assert first_system_count == 1, "expected exactly one [系统] after first cycle"

    # Second cycle without user touching the placeholder. Must NOT add a
    # second [系统] — pending_placeholder check kicks in first.
    await orch.run_cycle(task_file)
    after_second = task_file.read_text(encoding="utf-8")
    assert after_second.count("### [系统]") == 1, (
        "second cycle on unchanged file added a duplicate [系统] entry — "
        "is_pending_placeholder_turn isn't short-circuiting before the "
        "provider check"
    )


@pytest.mark.asyncio
async def test_task_malformed_writes_visible_marker(tmp_path):
    """A draft file with broken frontmatter used to be silent — only a
    log entry, nothing in Obsidian. Now we append a clearly-delimited
    text block at the end of the file so the user sees what's wrong."""
    tasks_dir = _kanban(tmp_path)
    draft = tasks_dir / "review" / "draft.md"
    draft.write_text(
        "---\n"
        "priority: P1\n"
        "intent: null\n"
        "---\n\n"
        "我打了一些字但忘了 title。\n",
        encoding="utf-8",
    )

    llm = _llm_with_responses(_final_text())
    orch = _make_orchestrator_for(tmp_path, llm)
    await orch.run_cycle(draft)

    content = draft.read_text(encoding="utf-8")
    assert "<!-- cc-assistant: file-malformed-notice -->" in content
    assert "[系统]" in content
    assert "frontmatter" in content
    # Original body preserved.
    assert "我打了一些字但忘了 title。" in content


@pytest.mark.asyncio
async def test_task_malformed_marker_is_idempotent(tmp_path):
    """Second cycle on the still-malformed file must NOT stack a second
    notice. The marker comment line is the dedup key."""
    tasks_dir = _kanban(tmp_path)
    draft = tasks_dir / "review" / "draft.md"
    draft.write_text(
        "---\n"
        "priority: P1\n"
        "---\n\n"
        "正文。\n",
        encoding="utf-8",
    )

    llm = _llm_with_responses(_final_text(), _final_text())
    orch = _make_orchestrator_for(tmp_path, llm)

    await orch.run_cycle(draft)
    after_first = draft.read_text(encoding="utf-8")
    await orch.run_cycle(draft)
    after_second = draft.read_text(encoding="utf-8")

    assert after_second.count("<!-- cc-assistant: file-malformed-notice -->") == 1
    assert after_first == after_second, "second cycle should be a no-op"


@pytest.mark.asyncio
async def test_run_cycle_routes_tag_escalated_task_to_api_client(tmp_path):
    """End-to-end routing: a task tagged `mysql` must be dispatched to the
    API client (which exposes DatabaseTool), not the CLI client. Locks in
    the tag-escalation contract from the orchestrator's perspective."""
    tasks_dir = _kanban(tmp_path)
    task_file = tasks_dir / "doing" / "tagged.md"
    task_file.write_text(
        "---\n"
        'id: "301"\n'
        "title: tagged\n"
        "tags: [mysql]\n"
        "created: 2026-05-05 10:00\n"
        "updated: 2026-05-05 10:00\n"
        "---\n\n"
        "## 任务描述\n"
        "查 mysql。\n",
        encoding="utf-8",
    )

    from src.agent.llm.router import LLMRouter
    api_stub = MagicMock()
    api_stub.chat = AsyncMock(side_effect=[_final_text("API answered.")])
    cli_stub = MagicMock()
    cli_stub.chat = AsyncMock()
    router = LLMRouter(api_client=api_stub, cli_client=cli_stub, default_provider="claude_cli")

    orch = _make_orchestrator_for(tmp_path, router)
    await orch.run_cycle(task_file)

    api_stub.chat.assert_called_once()
    cli_stub.chat.assert_not_called()


# ------------------------------------------------------------------ #
# Plan 5c: multi-project portfolio — project-status filter           #
# ------------------------------------------------------------------ #

import asyncio


def _write_project_card(tasks_dir: Path, slug: str, status: str) -> None:
    proj_dir = tasks_dir / "projects"
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / f"{slug}.md").write_text(
        f"---\ntype: project\nslug: {slug}\nstatus: {status}\n---\n# {slug}\n",
        encoding="utf-8",
    )


def _write_task_into(tasks_dir: Path, column: str, project: str = "") -> Path:
    column_dir = tasks_dir / column
    column_dir.mkdir(parents=True, exist_ok=True)
    task = _make_task(id="999", title="t", project=project)
    p = column_dir / "999-t.md"
    write_task_file(task, p)
    return p


def _orchestrator_with_mock_llm(tasks_dir: Path, tmp_path: Path):
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "rules.md").write_text("# rules\n", encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()

    llm = _llm_with_responses(_final_text("done"))
    return Orchestrator(
        tasks_dir=tasks_dir,
        skills_dir=skills,
        logs_dir=logs,
        llm=llm,
        tools=[],
        suppress_self=_noop_suppress,
    ), llm


def test_run_cycle_skips_todo_task_when_project_paused(tmp_path):
    tasks = _kanban(tmp_path)
    _write_project_card(tasks, "evernote", "paused")
    path = _write_task_into(tasks, "todo", project="evernote")

    orch, llm = _orchestrator_with_mock_llm(tasks, tmp_path)
    asyncio.run(orch.run_cycle(path))

    # File untouched: task still in todo/, no LLM call made.
    assert path.exists()
    assert llm.chat.await_count == 0


def test_run_cycle_skips_todo_task_when_project_archived(tmp_path):
    tasks = _kanban(tmp_path)
    _write_project_card(tasks, "evernote", "archived")
    path = _write_task_into(tasks, "todo", project="evernote")

    orch, llm = _orchestrator_with_mock_llm(tasks, tmp_path)
    asyncio.run(orch.run_cycle(path))

    assert path.exists()
    assert llm.chat.await_count == 0


def test_run_cycle_processes_todo_task_when_project_active(tmp_path):
    tasks = _kanban(tmp_path)
    _write_project_card(tasks, "evernote", "active")
    path = _write_task_into(tasks, "todo", project="evernote")

    orch, llm = _orchestrator_with_mock_llm(tasks, tmp_path)
    asyncio.run(orch.run_cycle(path))

    # Cycle ran (LLM was called) and the file has moved to doing/.
    assert llm.chat.await_count == 1
    assert not path.exists()
    assert any((tasks / "doing").glob("*.md"))


def test_run_cycle_processes_task_with_no_project_field(tmp_path):
    """Tasks without a project: field run unfiltered (back-compat)."""
    tasks = _kanban(tmp_path)
    path = _write_task_into(tasks, "todo", project="")

    orch, llm = _orchestrator_with_mock_llm(tasks, tmp_path)
    asyncio.run(orch.run_cycle(path))

    assert llm.chat.await_count == 1


def test_run_cycle_processes_task_when_project_card_missing(tmp_path):
    """If the project card doesn't exist, don't filter — log + run.

    Avoids daemon getting stuck on a typo'd project slug.
    """
    tasks = _kanban(tmp_path)
    path = _write_task_into(tasks, "todo", project="nonexistent")

    orch, llm = _orchestrator_with_mock_llm(tasks, tmp_path)
    asyncio.run(orch.run_cycle(path))

    assert llm.chat.await_count == 1


def test_run_cycle_does_not_filter_doing_tasks_when_project_paused(tmp_path):
    """Tasks already in doing/ keep running even after their project is paused.

    Spec: paused 不打斷正在跑的任務.
    """
    tasks = _kanban(tmp_path)
    _write_project_card(tasks, "evernote", "paused")
    path = _write_task_into(tasks, "doing", project="evernote")

    orch, llm = _orchestrator_with_mock_llm(tasks, tmp_path)
    asyncio.run(orch.run_cycle(path))

    assert llm.chat.await_count == 1


def test_intent_still_works_on_paused_project(tmp_path):
    """Intent operations (approve/reject/pause/resume) must work on paused projects.

    Spec: filter only blocks LLM-driven auto-advancement, not user-driven intents.
    """
    tasks = _kanban(tmp_path)
    _write_project_card(tasks, "evernote", "paused")

    # Put a task in review/ with intent: approve. Expectation: intent runs,
    # task moves to done/, even though the project is paused.
    review_dir = tasks / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    task = _make_task(id="999", title="t", project="evernote", intent=TaskIntent.APPROVE)
    path = review_dir / "999-t.md"
    write_task_file(task, path)

    orch, llm = _orchestrator_with_mock_llm(tasks, tmp_path)
    asyncio.run(orch.run_cycle(path))

    # Task moved out of review/ to done/, no LLM call (intent is mechanical).
    assert not path.exists()
    assert llm.chat.await_count == 0
    done_files = list((tasks / "done").rglob("*.md"))
    assert len(done_files) == 1


def test_run_cycle_enriches_minimal_task_before_parsing(tmp_path):
    """A title-only file in todo/ becomes a fully-formed task on first cycle.

    End-to-end: drop a minimal file → run_cycle → file gains id, created,
    updated; LLM is called once.
    """
    import asyncio
    import frontmatter

    tasks = _kanban(tmp_path)
    minimal = tasks / "todo" / "新需求.md"
    minimal.write_text(
        "---\ntitle: 写一句 pong\n---\n## 任务描述\n回 pong\n",
        encoding="utf-8",
    )

    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "rules.md").write_text("# rules\n", encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()

    llm = _llm_with_responses(_final_text("pong"))
    orch = Orchestrator(
        tasks_dir=tasks,
        skills_dir=skills,
        logs_dir=logs,
        llm=llm,
        tools=[],
        suppress_self=_noop_suppress,
    )
    asyncio.run(orch.run_cycle(minimal))

    # File now has full frontmatter; LLM was called exactly once.
    final_path = minimal if minimal.exists() else next((tasks / "doing").glob("*.md"))
    post = frontmatter.loads(final_path.read_text(encoding="utf-8"))
    assert str(post.metadata["id"]) == "001"
    assert post.metadata["title"] == "写一句 pong"
    assert "created" in post.metadata
    assert "updated" in post.metadata
    assert llm.chat.await_count == 1


def test_replay_pending_intents_enriches_minimal_tasks(tmp_path):
    """Daemon startup replay must enrich title-only files it scans.

    Setup: a minimal title-only task with `intent: resume` in blocked/.
    Without enrichment, parse_task_file would still succeed (with synthesized
    empty id) — but enrichment writes the proper fields back to disk, which
    is the contract guaranteed by replay.
    """
    import asyncio
    import frontmatter

    tasks = _kanban(tmp_path)
    minimal = tasks / "blocked" / "to-resume.md"
    minimal.write_text(
        "---\ntitle: 续一下\nintent: resume\n---\n## 任务描述\n继续\n",
        encoding="utf-8",
    )

    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "rules.md").write_text("# rules\n", encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()

    llm = _llm_with_responses(_final_text("ok"))
    orch = Orchestrator(
        tasks_dir=tasks,
        skills_dir=skills,
        logs_dir=logs,
        llm=llm,
        tools=[],
        suppress_self=_noop_suppress,
    )
    asyncio.run(orch.replay_pending_intents())

    # File should be enriched: even after intent moved it, the destination
    # file's frontmatter has id/created/updated filled.
    candidates = list((tasks / "doing").glob("*.md")) + list((tasks / "blocked").glob("*.md"))
    assert candidates, "task should still exist somewhere after replay"
    post = frontmatter.loads(candidates[0].read_text(encoding="utf-8"))
    assert str(post.metadata["id"]) == "001"
    assert "created" in post.metadata


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


def test_run_cycle_processes_bare_file_in_todo(tmp_path):
    """End-to-end: a body-only file in todo/ becomes a fully-formed task
    on first cycle. Title is synthesized from the filename."""
    import asyncio
    import frontmatter
    from src.board.parser import PLACEHOLDER_TEXT

    tasks = _kanban(tmp_path)
    bare = tasks / "todo" / "集成测试.md"
    bare.write_text("回 ok 即可\n", encoding="utf-8")

    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "rules.md").write_text("# rules\n", encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()

    llm = _llm_with_responses(_final_text("ok"))
    orch = Orchestrator(
        tasks_dir=tasks,
        skills_dir=skills,
        logs_dir=logs,
        llm=llm,
        tools=[],
        suppress_self=_noop_suppress,
    )
    asyncio.run(orch.run_cycle(bare))

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
    post = frontmatter.loads(text)
    assert post.metadata["title"] == "集成测试"
    assert str(post.metadata["id"]) == "001"
    # Cycle ran: AI reply + placeholder appended
    assert "ok" in text
    assert PLACEHOLDER_TEXT in text
    assert llm.chat.await_count == 1


def test_project_card_checkbox_click_spawns_task_and_updates_card(tmp_path):
    """E2E: tick a `[x]` in `## 下一步` → file appears in tasks/todo/ and
    project card line gains a `[[wikilink]]` prefix.

    First scan baselines without spawning, then a second scan with the box
    flipped triggers the spawn.
    """
    from contextlib import contextmanager
    from src.board.project_handler import process_project_card

    tasks = _kanban(tmp_path)
    projects = tasks / "projects"
    projects.mkdir()
    logs = tmp_path / "logs"
    logs.mkdir()

    @contextmanager
    def _ss():
        yield

    card = projects / "demo.md"
    card.write_text(
        "## 下一步 (Next actions)\n"
        "- [ ] 第一件事\n"
        "- [ ] 第二件事\n",
        encoding="utf-8",
    )

    # First scan — baseline only.
    process_project_card(card, tasks, logs, _ss)
    assert list((tasks / "todo").glob("*.md")) == [], "no tasks should spawn on first scan"

    # User ticks the first box.
    card.write_text(
        "## 下一步 (Next actions)\n"
        "- [x] 第一件事\n"
        "- [ ] 第二件事\n",
        encoding="utf-8",
    )

    process_project_card(card, tasks, logs, _ss)

    spawned = list((tasks / "todo").glob("*.md"))
    assert len(spawned) == 1, f"expected 1 task file, got {[p.name for p in spawned]}"
    spawned_path = spawned[0]

    # Parse to validate (title is YAML-quoted; raw `in` check would miss).
    from src.board.parser import parse_task_file
    parsed = parse_task_file(spawned_path)
    assert parsed.title == "第一件事"
    assert parsed.project == "demo"

    card_text = card.read_text(encoding="utf-8")
    assert "[[" in card_text
    assert "第一件事" in card_text


def test_startup_replay_baselines_and_spawns_prechecked_items(tmp_path):
    """On daemon startup, all existing project card checklists are baselined
    into the state file. Items that are already checked (`- [x]`) spawn tasks
    immediately — the user wrote them pre-checked as a one-step flow."""
    import asyncio
    import json

    tasks = _kanban(tmp_path)
    projects = tasks / "projects"
    projects.mkdir()
    (projects / "alpha.md").write_text(
        "## 下一步 (Next actions)\n- [ ] thing-a\n- [x] already-done\n",
        encoding="utf-8",
    )
    (projects / "beta.md").write_text(
        "## 下一步 (Next actions)\n- [ ] thing-b\n",
        encoding="utf-8",
    )

    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "rules.md").write_text("# rules\n", encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()

    llm = _llm_with_responses(_final_text("ok"))
    orch = Orchestrator(
        tasks_dir=tasks,
        skills_dir=skills,
        logs_dir=logs,
        llm=llm,
        tools=[],
        suppress_self=_noop_suppress,
    )

    asyncio.run(orch.replay_pending_intents())

    # State file populated for both slugs
    state = json.loads((logs / "project_checkbox_state.json").read_text(encoding="utf-8"))
    assert "alpha" in state
    assert "beta" in state
    assert state["alpha"]["unchecked_items"] == ["thing-a"]
    assert state["alpha"]["checked_items"] == ["already-done"]

    # alpha's pre-checked "already-done" spawned; beta's unchecked "thing-b" did not.
    spawned = list((tasks / "todo").glob("*.md"))
    assert len(spawned) == 1
    body = spawned[0].read_text(encoding="utf-8")
    assert "already-done" in body
    # LLM not called — project card processing is pure file mutation.
    assert llm.chat.await_count == 0


async def test_on_poll_logs_err_detail_when_run_cycle_raises(tmp_path):
    """When `run_cycle` raises, the `poll_error` system log line must
    include the exception repr — not just the path. The 5/2→5/3 dogfood
    debugging session burned time because the daemon swallowed the real
    error and only printed `path=...`, forcing a second run with manual
    `print(exc)` to find the cause.
    """
    import json as _json
    tasks_dir = orch_dir(tmp_path)
    todo_path = tasks_dir / "todo" / "100-poll-err.md"
    write_task_file(_make_task(id="100"), todo_path)

    llm = _llm_with_responses(_final_text("ok"))
    orch = _make_orchestrator_for(tmp_path, llm)

    sentinel = "kaboom-detail-xyz"

    async def boom(_path):
        raise RuntimeError(sentinel)

    orch.run_cycle = boom  # bypass the real cycle for this poll iteration

    await orch.on_poll()

    log_path = tmp_path / "logs" / "agent.jsonl"
    assert log_path.exists(), "agent.jsonl should be written by log_system"
    lines = [
        _json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    poll_errors = [e for e in lines if e["action"] == "poll_error"]
    assert poll_errors, "poll_error entry must be logged"
    detail = poll_errors[0]["detail"]
    assert "RuntimeError" in detail
    assert sentinel in detail
    assert "err=" in detail
