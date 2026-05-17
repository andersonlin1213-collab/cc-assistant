from __future__ import annotations

import logging
import threading
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import Callable

from src.agent.context import ContextBuilder
from src.agent.cycle_state import CycleState
from src.agent.llm.base import LLMClient
from src.agent.llm.router import ProviderUnavailable
from src.agent.llm.types import (
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from src.agent.tool_bridge import ToolBridge
from src.board.manager import BoardManager
from src.board.parser import (
    TaskFileMalformed,
    enrich_minimal_task,
    is_pending_placeholder_turn,
    parse_task_file,
)
from src.board.writer import (
    append_conversation,
    append_placeholder,
    append_system_entry,
    append_unparseable_file_marker,
    write_task_file,
)
from src.logging.structured import StructuredLogger
from src.models import (
    ConversationEntry,
    ConversationRole,
    LogEntry,
    ProjectStatus,
    Task,
    TaskIntent,
    TaskStatus,
    Who,
)
from src.rules.loader import RulesLoader
from src.tools.base import Tool


_log = logging.getLogger(__name__)


class Orchestrator:
    """Runs one Completion-Promise-Pattern cycle per call.

    Cycle = parse task -> build messages -> LLM-tool inner loop -> append AI reply
    -> decide next status -> move file -> commit. Each cycle reconstructs context
    from scratch (rules.md + task file); no LLM state is preserved across cycles.
    """

    MAX_TOOL_USE_ROUNDS = 10

    def __init__(
        self,
        tasks_dir: Path,
        skills_dir: Path,
        logs_dir: Path,
        llm: LLMClient,
        tools: list[Tool],
        suppress_self: Callable[[], AbstractContextManager],
    ) -> None:
        self.tasks_dir = tasks_dir
        self.logs_dir = logs_dir
        self.manager = BoardManager(tasks_dir)
        self.rules = RulesLoader(skills_dir)
        self.logger = StructuredLogger(logs_dir)
        self.context_builder = ContextBuilder()
        self.bridge = ToolBridge(tools)
        # Accept either an LLMRouter (production: lets per-task provider
        # routing happen) or a plain LLMClient (tests & one-off paths:
        # wrapped in a trivial single-client router). Downstream code only
        # ever calls `self.router.select(task).chat(...)`, so the two paths
        # are identical from there.
        from src.agent.llm.router import LLMRouter, _SingleClientRouter
        if isinstance(llm, LLMRouter):
            self.router = llm
        else:
            self.router = _SingleClientRouter(llm)
        self.suppress_self = suppress_self
        # Per-path mutex: prevents concurrent cycles for the same task file
        # when watchdog and the scheduler both fire simultaneously.
        self._in_flight: set[str] = set()
        self._in_flight_lock = threading.Lock()
        # Dedup parser_warning emissions: same file re-parsed each cycle
        # produces the same warning set. Without dedup the log gets spammed
        # every save. Key is source_path; value is the set of warning
        # strings last emitted. New cycles only emit warnings whose string
        # is NOT already in the cached set, so a fixed file silently drops
        # old entries and a newly-introduced anomaly still surfaces.
        self._last_parse_warnings: dict[str, frozenset[str]] = {}

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    async def run_cycle(self, path: Path, dry_run: bool = False) -> None:
        """Execute one cycle for the task at `path`. Idempotent and crash-safe.

        No-op if path does not exist (file may already have been moved by an
        earlier cycle) or if the task is in a terminal column (done/, review/).
        """
        if not path.exists():
            return

        key = str(path)
        with self._in_flight_lock:
            if key in self._in_flight:
                return  # another thread is already processing this path
            self._in_flight.add(key)

        try:
            current_status = self._status_from_path(path)
            # Auto-enrich title-only minimal tasks so users can drop a file with
            # just `title:` and a body. The write-back is wrapped in suppress_self
            # so it doesn't re-trigger this watcher event. No-op for any file
            # that already has id/created/updated.
            with self.suppress_self():
                try:
                    enrich_minimal_task(path, self.tasks_dir)
                except OSError as e:
                    self.logger.log_system(
                        action="enrich_failed",
                        detail=f"path={path} err={e}",
                        status="error",
                    )
                    return
            try:
                task = parse_task_file(path)
            except TaskFileMalformed as e:
                # User likely created a draft on mobile without filling the
                # template. Log + write a visible marker into the file so
                # the user sees the problem in Obsidian (not just buried in
                # logs/agent.jsonl). Daemon picks the file back up once the
                # frontmatter is fixed and the user removes the notice.
                self.logger.log_system(
                    action="task_malformed",
                    detail=f"path={path} reason={e}",
                    status="error",
                )
                try:
                    with self.suppress_self():
                        append_unparseable_file_marker(path, str(e))
                except Exception as marker_err:  # pylint: disable=broad-except
                    # Never let a marker-write failure crash the watcher.
                    self.logger.log_system(
                        action="task_malformed_marker_failed",
                        detail=f"path={path} err={marker_err!r}",
                        status="error",
                    )
                return

            # Surface forgive-then-warn anomalies. Parser already produced a
            # best-effort Task; these entries make the silent-fail edge cases
            # observable in logs so we stop deducing them from behavior.
            # Dedup against the prior cycle's set for this path: a doing/
            # file that triggers a warning would otherwise log it on every
            # save (mtime tick + scheduler poll), drowning out new ones.
            current_warnings = frozenset(task.parse_warnings)
            cache_key = str(path)
            previous_warnings = self._last_parse_warnings.get(cache_key, frozenset())
            for warning in task.parse_warnings:
                if warning in previous_warnings:
                    continue
                self.logger.log(LogEntry(
                    task_id=task.id,
                    action="parser_warning",
                    detail=f"path={path} {warning}",
                    status="warning",
                ))
            self._last_parse_warnings[cache_key] = current_warnings

            # Plan 5b: intent mechanical action — no LLM call.
            # Must run BEFORE the DONE/REVIEW short-circuit so that
            # `intent: approve` on review/ and similar combos can fire.
            if task.intent is not None:
                self._apply_intent(path, task, current_status, dry_run=dry_run)
                return

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

            # Multi-project filter: skip tasks whose project card is paused
            # or archived. Tasks already in doing/ are exempt — paused means
            # "don't start new", not "kill in flight". Runs AFTER intent
            # handling so user-driven approve/reject/resume/pause still work
            # on paused projects.
            if self._skip_for_paused_project(task, current_status):
                self.logger.log(LogEntry(
                    task_id=task.id, action="cycle_skipped",
                    detail=f"project={task.project} status=paused/archived",
                ))
                return

            # Plan 5b: skip cycle when task is not assigned to AI.
            if task.who != Who.CLAUDE:
                self.logger.log(LogEntry(
                    task_id=task.id, action="cycle_skipped",
                    detail=f"who={task.who.value}",
                ))
                return

            if current_status in (TaskStatus.DONE, TaskStatus.REVIEW):
                return

            self.logger.log(LogEntry(
                task_id=task.id, action="cycle_start",
                detail=f"status={current_status.value}",
            ))

            llm_failed = False
            try:
                final_text, cycle_state = await self._run_llm_loop(task, dry_run=dry_run)
            except ProviderUnavailable as e:
                # Configuration issue, not a model failure: the requested
                # provider isn't reachable (missing API key, claude CLI not
                # on PATH, etc.). Surface it inline as a [系统] entry so
                # the user fixes the config (or task frontmatter) without
                # having to tail logs. Then scaffold a fresh placeholder
                # so the next save with the fix actually triggers a cycle.
                self.logger.log(LogEntry(
                    task_id=task.id, action="provider_unavailable",
                    detail=f"path={path} {e}", status="error",
                ))
                try:
                    with self.suppress_self():
                        append_system_entry(
                            path,
                            f"无法跑这一轮:provider 不可用 — {e}\n\n"
                            "可能原因之一:\n"
                            "- 代理(v2rayN/clash)挂了 → 重启代理\n"
                            "- `.env` 缺凭据(`ANTHROPIC_API_KEY`)或 `LLM_PROVIDER` 配错\n"
                            "- 任务卡 frontmatter `provider:` 写了未配置的 provider\n\n"
                            "修好后保存这张卡触发重试。",
                        )
                        append_placeholder(path)
                except Exception as write_err:  # pylint: disable=broad-except
                    self.logger.log_system(
                        action="provider_unavailable_marker_failed",
                        detail=f"path={path} err={write_err!r}",
                        status="error",
                    )
                return
            except Exception as e:  # pylint: disable=broad-except
                self.logger.log(LogEntry(
                    task_id=task.id, action="cycle_error",
                    detail=str(e), status="error",
                ))
                final_text = f"[Error] {e}"
                cycle_state = CycleState()
                llm_failed = True

            if llm_failed:
                # On LLM failure, do not auto-advance status.
                # Append the error reply but keep the file where it was.
                next_status = current_status
            else:
                next_status = self._decide_next_status(current_status, task, cycle_state)

            if dry_run:
                self.logger.log(LogEntry(
                    task_id=task.id, action="cycle_dry_run_complete",
                    detail=(
                        f"would_move={current_status.value}->{next_status.value} "
                        f"would_append=[{final_text[:80]}]"
                    ),
                ))
                return

            # Mutate filesystem inside suppress_self to avoid retriggering ourselves.
            new_path = path
            try:
                with self.suppress_self():
                    self._append_ai_reply(path, final_text)
                    if next_status != current_status:
                        new_path = self.manager.move_task(path, next_status)
                    # Scaffold the next [我] turn so the user can just overwrite
                    # the placeholder line and save. Idempotent — safe even if
                    # downstream code calls it again.
                    append_placeholder(new_path)
            except Exception as e:  # pylint: disable=broad-except
                self.logger.log(LogEntry(
                    task_id=task.id, action="cycle_error",
                    detail=f"fs_mutation_failed: {e}", status="error",
                ))
                raise

            self.logger.log(LogEntry(
                task_id=task.id, action="cycle_complete",
                detail=f"final_status={next_status.value} path={new_path}",
            ))
        finally:
            with self._in_flight_lock:
                self._in_flight.discard(key)

    async def on_poll(self) -> None:
        """Scheduled scan: run a cycle for each task in todo/ and doing/."""
        for status in (TaskStatus.TODO, TaskStatus.DOING):
            for path in self.manager.list_tasks(status):
                try:
                    await self.run_cycle(path)
                except Exception as exc:  # pylint: disable=broad-except
                    self.logger.log_system(
                        action="poll_error",
                        detail=f"path={path} err={exc!r}",
                        status="error",
                    )

    async def replay_pending_intents(self) -> int:
        """Apply any task whose `intent` is set across all active columns.

        Closes the gap where the daemon was offline while the user (typically
        via Obsidian Sync from phone) set an intent: the watcher missed the
        change, and `on_poll` doesn't scan blocked/ or review/. Run once at
        daemon startup, before the coordinator begins.

        Returns the count of files where intent was applied or cleared.
        """
        active = (
            TaskStatus.BACKLOG,
            TaskStatus.TODO,
            TaskStatus.DOING,
            TaskStatus.BLOCKED,
            TaskStatus.REVIEW,
        )
        processed = 0
        for status in active:
            for path in self.manager.list_tasks(status):
                with self.suppress_self():
                    try:
                        enrich_minimal_task(path, self.tasks_dir)
                    except OSError as e:
                        self.logger.log_system(
                            action="replay_enrich_failed",
                            detail=f"path={path} err={e}",
                            status="error",
                        )
                        continue
                try:
                    task = parse_task_file(path)
                except Exception as e:  # pylint: disable=broad-except
                    self.logger.log_system(
                        action="replay_parse_error",
                        detail=f"path={path} err={e}",
                        status="error",
                    )
                    continue
                # One-time back-fill: pre-existing doing/ files that ended
                # with an [AI] reply (no placeholder yet) get a placeholder
                # appended so the rest-of-system invariant — every doing/
                # file ends with a pending [我] turn — holds. Skip cycle:
                # the user hasn't actually replied.
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
                        else:
                            self.logger.log_system(
                                action="replay_placeholder_backfill",
                                detail=f"path={path}",
                            )
                    continue
                if task.intent is None:
                    continue
                try:
                    await self.run_cycle(path)
                    processed += 1
                except Exception as e:  # pylint: disable=broad-except
                    self.logger.log_system(
                        action="replay_error",
                        detail=f"path={path} err={e}",
                        status="error",
                    )
        # Baseline project card states so the first post-startup user click
        # is a real diff (not a "first encounter" no-op).
        from src.board.project_handler import process_project_card
        projects_dir = self.tasks_dir / "projects"
        if projects_dir.exists():
            for card_path in sorted(projects_dir.glob("*.md")):
                with self.suppress_self():
                    try:
                        process_project_card(
                            card_path,
                            tasks_dir=self.tasks_dir,
                            logs_dir=self.logs_dir,
                            suppress_self=self.suppress_self,
                        )
                    except Exception as e:  # pylint: disable=broad-except
                        self.logger.log_system(
                            action="replay_project_card_failed",
                            detail=f"path={card_path} err={e}",
                            status="error",
                        )
        # Only log the summary when something actually happened. A quiet
        # poll (processed=0, no back-fills) should leave no trace — users
        # don't want feedback when no work was done.
        if processed > 0:
            self.logger.log_system(
                action="replay_pending_intents",
                detail=f"processed={processed}",
            )
        return processed

    # ------------------------------------------------------------------ #
    # Internals                                                          #
    # ------------------------------------------------------------------ #

    async def _run_llm_loop(
        self, task: Task, dry_run: bool = False
    ) -> tuple[str, CycleState]:
        rules = self.rules.load()
        from src.config import config as _cfg
        messages = self.context_builder.build(
            rules, task, vault_name=_cfg.obsidian_vault_name
        )

        # Plan 5b: pre-read source_files and append as a user message so the
        # LLM has the bytes in context without burning a tool-call round.
        if task.source_files:
            preload = self._read_source_files(task.source_files)
            if preload:
                messages.append(Message(role="user", content=preload))

        tool_defs = self.bridge.tool_definitions()
        cycle_state = CycleState()

        # Resolve the LLM client once per cycle. The same client handles all
        # tool-use rounds for a given task; we never bounce mid-conversation.
        # ProviderUnavailable propagates up to run_cycle, which logs and
        # short-circuits without touching the file.
        llm = self.router.select(task)

        final_text = ""
        for _ in range(self.MAX_TOOL_USE_ROUNDS):
            response = await llm.chat(messages, tools=tool_defs)
            self.logger.log(LogEntry(
                task_id=task.id, action="llm_call",
                detail=f"stop_reason={response.stop_reason}",
            ))

            if response.stop_reason != "tool_use":
                final_text = self._extract_text(response.content)
                break

            # tool_use round: execute each tool, append assistant + tool_result messages
            tool_use_blocks = [
                b for b in response.content if isinstance(b, ToolUseBlock)
            ]
            if not tool_use_blocks:
                final_text = self._extract_text(response.content)
                break

            messages.append(Message(role="assistant", content=response.content))

            tool_result_blocks: list = []
            for tu in tool_use_blocks:
                result = await self.bridge.dispatch(tu, cycle_state, dry_run=dry_run)
                self.logger.log(LogEntry(
                    task_id=task.id, action="tool_exec", tool=tu.name,
                    detail=result.output[:200] if result.success else (result.error or ""),
                    status="success" if result.success else "error",
                ))
                tool_result_blocks.append(
                    ToolResultBlock(
                        tool_use_id=tu.id,
                        content=result.output if result.success else (result.error or ""),
                        is_error=not result.success,
                    )
                )
            messages.append(Message(role="user", content=tool_result_blocks))
        else:
            # Loop exited via for-else (no break) — hit the cap
            final_text = (
                "[Cycle exceeded MAX_TOOL_USE_ROUNDS; bailing out — "
                "consider mark_blocked or mark_complete next time.]"
            )
            self.logger.log(LogEntry(
                task_id=task.id, action="cycle_capped",
                detail=f"rounds={self.MAX_TOOL_USE_ROUNDS}",
                status="error",
            ))

        return final_text, cycle_state

    @staticmethod
    def _extract_text(blocks) -> str:
        parts: list[str] = []
        for b in blocks:
            if isinstance(b, TextBlock):
                parts.append(b.text)
        return "\n\n".join(parts).strip() or "(no reply)"

    def _status_from_path(self, path: Path) -> TaskStatus:
        # Walk up parents until we hit one of the six column names.
        column_names = {s.value for s in TaskStatus}
        for parent in path.parents:
            if parent.name in column_names:
                return TaskStatus(parent.name)
        # Default to DOING if we can't tell — the file will end up there anyway.
        return TaskStatus.DOING

    def _skip_for_paused_project(self, task: Task, current_status: TaskStatus) -> bool:
        """Return True if this task should be held due to its project's status.

        Logic:
          - No project field → don't filter (back-compat).
          - Already in doing/ → don't filter (do not interrupt running work).
          - Project card missing → don't filter (avoid getting stuck on typos).
          - Project card unparseable → don't filter (handled as missing in manager).
          - Project status active → don't filter.
          - Project status paused or archived → SKIP.
        """
        if not task.project:
            return False
        if current_status == TaskStatus.DOING:
            return False
        project = self.manager.get_project(task.project)
        if project is None:
            return False
        return project.status != ProjectStatus.ACTIVE

    @staticmethod
    def _decide_next_status(
        current: TaskStatus, task: Task, state: CycleState
    ) -> TaskStatus:
        # Explicit signals win
        if state.marked_blocked:
            return TaskStatus.BLOCKED
        if state.marked_complete:
            return TaskStatus.DONE if task.auto_approve else TaskStatus.REVIEW
        # Auto-advance todo -> doing on first cycle
        if current == TaskStatus.TODO:
            return TaskStatus.DOING
        # Otherwise stay where we are
        return current

    @staticmethod
    def _read_source_files(paths: list[str], max_bytes_each: int = 50_000) -> str:
        """Pre-read source files referenced by the task into a single text block.

        Each file is truncated to `max_bytes_each` to avoid blowing the context
        window on a forgotten 100 MB log file.
        """
        chunks: list[str] = ["## Pre-read source files"]
        for raw in paths:
            p = Path(raw)
            if not p.exists():
                chunks.append(f"### `{raw}` — (not found)")
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                chunks.append(f"### `{raw}` — (read error: {e})")
                continue
            if len(text) > max_bytes_each:
                text = text[:max_bytes_each] + f"\n\n[...truncated at {max_bytes_each} bytes]"
            chunks.append(f"### `{raw}`\n```\n{text}\n```")
        return "\n\n".join(chunks)

    def _append_ai_reply(self, path: Path, text: str) -> None:
        entry = ConversationEntry(
            role=ConversationRole.AI,
            timestamp=datetime.now(),
            content=text,
        )
        append_conversation(path, entry)

    def _apply_intent(
        self,
        path: Path,
        task: Task,
        current_status: TaskStatus,
        dry_run: bool = False,
    ) -> None:
        """Mechanical action: clear intent, move file if combo is valid, log.

        No LLM call. No conversation append. Pure file shuffling driven by the
        user's frontmatter edit. When `dry_run=True`, log what would happen
        but leave the file untouched so the intent remains pending for a real
        run.
        """
        target = self.manager.target_status_for_intent(task.intent, current_status)
        intent_value = task.intent.value

        if dry_run:
            if target is None:
                self.logger.log(LogEntry(
                    task_id=task.id,
                    action="intent_dry_run_invalid",
                    detail=f"intent={intent_value} from={current_status.value}",
                    status="error",
                ))
            else:
                self.logger.log(LogEntry(
                    task_id=task.id,
                    action="intent_dry_run",
                    detail=(
                        f"would_apply intent={intent_value} "
                        f"{current_status.value}->{target.value}"
                    ),
                ))
            return

        task.intent = None
        with self.suppress_self():
            write_task_file(task, path)
            if target is None:
                self.logger.log(LogEntry(
                    task_id=task.id,
                    action="intent_invalid",
                    detail=f"intent={intent_value} from={current_status.value}",
                    status="error",
                ))
                return
            new_path = self.manager.move_task(path, target)
            self.logger.log(LogEntry(
                task_id=task.id,
                action="intent_applied",
                detail=(
                    f"intent={intent_value} "
                    f"{current_status.value}->{target.value} path={new_path}"
                ),
            ))
